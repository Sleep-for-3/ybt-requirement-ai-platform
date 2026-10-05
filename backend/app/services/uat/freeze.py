"""N04/N05: freeze a UAT run's inputs and bind every signoff to the evidence it approved.

Two review findings are handled here:

* **N05** - the evidence package was rebuilt from the *current* schema, health and whole-project
  deliverables on every download, so the same closed run produced different bytes after the
  environment changed, and a run could be created with an empty version.  ``build_run_manifest``
  captures the run/input identity server-side at creation time and the package reads that snapshot.
* **N04** - a run could still be edited after an ``approved`` signoff (the run flipped to
  ``failed`` while the old approval stayed valid).  ``assert_run_mutable`` refuses such writes and
  ``signoff_evidence_hash`` binds each signature to a digest of the frozen evidence, so a changed
  run can no longer keep a stale approval.

Importing this module has no side effects.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ModelProfile, UatCaseResult, UatRun, UatSignoff, UatSuite
from app.models.requirement import RequirementRevision, RequirementUatLink
from app.services.version_info import version_report

# Signoff states that freeze the run.  ``rejected`` keeps the run editable so a rework loop does not
# need a new run object.
FROZEN_SIGNOFF_STATUSES = ("approved",)
MANIFEST_VERSION = 1


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return str(value)


def _requirement_identity(db: Session, run: UatRun) -> dict[str, Any] | None:
    """Requirement/suite inputs this run executes against (None for a generic system suite)."""

    link = db.scalar(select(RequirementUatLink).where(RequirementUatLink.suite_id == run.uat_suite_id))
    if link is None:
        return None
    revision = db.scalar(
        select(RequirementRevision)
        .where(RequirementRevision.requirement_id == link.requirement_id)
        .order_by(RequirementRevision.content_version.desc())
    )
    return {
        "requirement_id": link.requirement_id,
        "revision_id": link.revision_id,
        "link_id": link.id,
        "link_status": link.status,
        # The link itself pins the approved material (hash of content and of the case set).
        "content_hash": link.content_hash,
        "cases_hash": link.cases_hash,
        "content_version": getattr(revision, "content_version", None),
        "revision_hash": getattr(revision, "content_hash", None),
    }


def _model_profiles(db: Session) -> list[dict[str, Any]]:
    rows = db.scalars(select(ModelProfile).order_by(ModelProfile.id)).all()
    return [
        {
            "id": item.id,
            "name": item.name,
            "provider": getattr(item, "provider", None),
            "model_name": getattr(item, "model_name", None),
            "enabled": getattr(item, "enabled", None),
        }
        for item in rows
    ]


def build_run_manifest(db: Session, run: UatRun, *, request_id: str | None = None) -> dict[str, Any]:
    """Capture the run's identity and inputs once, at creation time."""

    suite = db.get(UatSuite, run.uat_suite_id)
    identity = version_report(db)
    return _jsonable({
        "manifest_version": MANIFEST_VERSION,
        "frozen_at": datetime.now(UTC).isoformat(),
        "request_id": request_id,
        "run": {
            "id": run.id,
            "project_id": run.project_id,
            "suite_id": run.uat_suite_id,
            "suite_name": getattr(suite, "suite_name", None),
            "suite_type": getattr(suite, "suite_type", None),
            "run_no": run.run_no,
            "environment_name": run.environment_name,
            "application_version": run.application_version,
            "git_commit_sha": run.git_commit_sha,
        },
        "release_identity": {
            "component": identity.get("component"),
            "app_commit": identity.get("app_commit"),
            "build_time": identity.get("build_time"),
            "schema_head": identity.get("schema_head"),
            "image_digest": identity.get("image_digest"),
        },
        "requirement": _requirement_identity(db, run),
        "model_profiles": _model_profiles(db),
    })


def manifest_digest(manifest: dict[str, Any] | None) -> str:
    canonical = json.dumps(manifest or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(canonical.encode("utf-8")).hexdigest()


def freeze_run_manifest(db: Session, run: UatRun, *, request_id: str | None = None) -> dict[str, Any]:
    """Freeze the manifest once.  A later call never overwrites an existing snapshot."""

    if not run.manifest_json:
        run.manifest_json = build_run_manifest(db, run, request_id=request_id)
        db.flush()
    return dict(run.manifest_json)


def results_digest(db: Session, run: UatRun) -> str:
    """Digest of the executed results + their evidence, in a stable order."""

    rows = db.scalars(
        select(UatCaseResult).where(UatCaseResult.uat_run_id == run.id).order_by(UatCaseResult.id)
    ).all()
    payload = [
        {
            "case_result_id": item.id,
            "case_id": item.uat_case_id,
            "status": item.status,
            "actual_result": item.actual_result_json,
            "evidence": item.evidence_json,
            "error_message": item.error_message,
        }
        for item in rows
    ]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(canonical.encode("utf-8")).hexdigest()


def signoff_evidence_hash(db: Session, run: UatRun) -> str:
    """N04: the digest a signature approves (frozen manifest + current results)."""

    material = {
        "manifest_digest": manifest_digest(run.manifest_json),
        "results_digest": results_digest(db, run),
        "run_status": run.status,
        "frozen_manifest": run.manifest_json or {},
    }
    canonical = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(canonical.encode("utf-8")).hexdigest()


def active_signoffs(db: Session, run: UatRun) -> list[UatSignoff]:
    return list(db.scalars(
        select(UatSignoff).where(UatSignoff.uat_run_id == run.id).order_by(UatSignoff.id)
    ).all())


def approved_signoff(db: Session, run: UatRun) -> UatSignoff | None:
    for item in active_signoffs(db, run):
        if item.signoff_status in FROZEN_SIGNOFF_STATUSES and item.revoked_at is None:
            return item
    return None


def assert_run_mutable(db: Session, run: UatRun) -> None:
    """Refuse result/evidence writes once an approved signoff exists.

    The reviewer's reproduction modified a manual result after signoff: the endpoint returned 200,
    the run flipped to ``failed``, and the original ``approved`` signature stayed valid.  Callers
    must either revoke the signature explicitly or open a new run.
    """

    signoff = approved_signoff(db, run)
    if signoff is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "uat-run-signed-off",
                "message": "该轮次已签署通过，不能修改结果或证据；请撤销签署后重签，或新建轮次。",
                "signoff_id": signoff.id,
                "evidence_hash": signoff.evidence_hash,
            },
        )


__all__ = [
    "FROZEN_SIGNOFF_STATUSES",
    "MANIFEST_VERSION",
    "approved_signoff",
    "assert_run_mutable",
    "build_run_manifest",
    "freeze_run_manifest",
    "manifest_digest",
    "results_digest",
    "signoff_evidence_hash",
]
