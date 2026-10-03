"""B18: one version identity that the frontend, API, worker and beat can all compare.

A release is only trustworthy when every component reports the same application commit, build
time and migration head. Values come from the deployment environment (APP_COMMIT / BUILD_TIME /
SERVICE_COMPONENT), with the packaged build-info.json as a fallback, and the schema head is read
from the live database rather than hard-coded.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

BUILD_INFO_PATH = Path(__file__).resolve().parents[2] / "build-info.json"

COMPONENTS = ("api", "worker", "beat", "frontend")
UNKNOWN = "unknown"


def _packaged_build_info() -> dict[str, Any]:
    try:
        return json.loads(BUILD_INFO_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def component_name() -> str:
    value = (os.environ.get("SERVICE_COMPONENT") or "").strip().lower()
    return value if value in COMPONENTS else "api"


def app_commit() -> str:
    value = (os.environ.get("APP_COMMIT") or "").strip()
    if value:
        return value
    packaged = _packaged_build_info()
    return str(packaged.get("app_commit") or UNKNOWN)


def build_time() -> str:
    value = (os.environ.get("BUILD_TIME") or "").strip()
    if value:
        return value
    packaged = _packaged_build_info()
    return str(packaged.get("build_time") or UNKNOWN)


def schema_head(db: Session) -> str | None:
    """The migration revision the database is actually on, or None when unreadable."""
    try:
        return db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except Exception:  # noqa: BLE001 - a missing table must not break a health/version probe
        return None


def version_report(db: Session, *, component: str | None = None) -> dict[str, Any]:
    return {
        "component": component or component_name(),
        "app_commit": app_commit(),
        "build_time": build_time(),
        "schema_head": schema_head(db),
        "image_digest": (os.environ.get("IMAGE_DIGEST") or UNKNOWN),
    }


def versions_match(*reports: dict[str, Any]) -> bool:
    """True only when every report shares commit, build time and schema head.

    An ``unknown`` identity can never prove consistency, so it is treated as a mismatch rather
    than a value that happens to be equal everywhere.
    """

    if len(reports) < 2:
        return True
    keys = ("app_commit", "build_time", "schema_head")
    first = reports[0]
    for key in keys:
        if not first.get(key) or first.get(key) == UNKNOWN:
            return False
    return all(all(report.get(key) == first.get(key) for key in keys) for report in reports[1:])
