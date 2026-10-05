"""Seed one **completed** requirement generation run into the isolated database.

F06 (a failed refresh must fall back to the last successful read, clearly marked read-only) cannot be
exercised in a browser without a prior successful, non-empty ``generation-runs`` response. The phase-4
fixture has none, and the API refuses to create one because the requirement is already confirmed
(409 "只能为当前草稿准备新的生成输入") -- which is correct product behaviour, not a bug.

This script therefore inserts the minimum completed run directly, on the throw-away database only:

* one ``RequirementGenerationInput`` whose ``input_json`` carries the fields ``input_summary`` reads
  (``content_version`` / ``field_ids`` / ``sections``);
* one ``completed`` ``RequirementGenerationItem`` per requirement field.

Re-running is a no-op (keyed by idempotency_key). Nothing here touches the business database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

IDEMPOTENCY_KEY = "f06-browser-verify-fixture"
CONTENT_VERSION = 22


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="ybt_iso_phase4_synthetic")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    args = parser.parse_args()

    password = os.environ.get("PGPASSWORD") or ""
    if not password:
        print(json.dumps({"ok": False, "error": "PGPASSWORD is not set"}, ensure_ascii=False))
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "2026-10-03"))
    from isolated_pg_guard import require_isolated_target

    require_isolated_target(
        args.database, script="seed_f06_generation_run.py", host=args.host, port=args.port,
        user=args.user, password=password, allow_existing=True,
    )

    url = f"postgresql+psycopg://{args.user}:{password}@{args.host}:{args.port}/{args.database}"
    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("AUTH_MODE", "required")
    os.environ.setdefault("TASK_QUEUE_PROVIDER", "inline")
    os.environ.setdefault("APP_SECRET_KEY", "phase4-browser-app-secret")
    os.environ.setdefault("JWT_SECRET_KEY", "phase4-browser-jwt-secret-at-least-32-chars")

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.models import (
        Project, Requirement, RequirementGenerationInput, RequirementGenerationItem, TargetField, User,
    )

    engine = create_engine(url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    steps: list[dict] = []

    def step(name: str, **payload: object) -> None:
        record = {"step": name, **payload}
        steps.append(record)
        print(json.dumps({"f06_seed": record}, ensure_ascii=False), flush=True)

    with factory() as db:
        project = db.scalar(select(Project).order_by(Project.id).limit(1))
        requirement = db.scalar(select(Requirement).where(
            Requirement.project_id == project.id).order_by(Requirement.id).limit(1))
        actor = db.scalar(select(User).where(User.username == "p4_platform_admin"))
        if project is None or requirement is None or actor is None:
            step("missing_prerequisites", ok=False)
            return 3

        field_ids = [row.id for row in db.scalars(select(TargetField).where(
            TargetField.project_id == project.id).order_by(TargetField.id)).all()]
        step("fields_ready", ok=bool(field_ids), count=len(field_ids))

        existing = db.scalar(select(RequirementGenerationInput).where(
            RequirementGenerationInput.project_id == project.id,
            RequirementGenerationInput.requirement_id == requirement.id,
            RequirementGenerationInput.idempotency_key == IDEMPOTENCY_KEY))
        if existing is not None:
            step("generation_run_exists", ok=True, input_id=int(existing.id))
            print(json.dumps({"ok": True, "steps": len(steps)}, ensure_ascii=False))
            return 0

        # ``Requirement`` has no ``current_revision_id``; the revision is identified by
        # ``content_version`` (the real API resolves it the same way via ``load_revision``).
        from app.models import RequirementRevision

        revision = db.scalar(select(RequirementRevision).where(
            RequirementRevision.requirement_id == requirement.id,
            RequirementRevision.content_version == requirement.content_version))
        if revision is None:
            step("revision_missing", ok=False, content_version=requirement.content_version)
            return 3
        revision_id = revision.id
        input_json = {
            "content_version": CONTENT_VERSION,
            "field_ids": field_ids,
            "sections": ["business", "lineage"],
        }
        material = json.dumps(input_json, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        row = RequirementGenerationInput(
            project_id=int(project.id),
            requirement_id=int(requirement.id),
            revision_id=int(revision_id),
            idempotency_key=IDEMPOTENCY_KEY,
            request_hash=hashlib.sha256(f"{IDEMPOTENCY_KEY}:{material}".encode("utf-8")).hexdigest(),
            input_hash=hashlib.sha256(material.encode("utf-8")).hexdigest(),
            input_json=input_json,
            created_by=int(actor.id),
        )
        db.add(row)
        db.flush()

        for field_id in field_ids:
            for section in ("business", "lineage"):
                db.add(RequirementGenerationItem(
                    input_id=int(row.id), field_id=int(field_id), section=section,
                    status="completed",
                    candidate_json={"summary": f"合成候选 field={field_id} section={section}"},
                    candidate_hash=hashlib.sha256(f"{row.id}:{field_id}:{section}".encode("utf-8")).hexdigest(),
                ))
        db.commit()
        step("generation_run_created", ok=True, input_id=int(row.id),
             items=len(field_ids) * 2, content_version=CONTENT_VERSION)

    print(json.dumps({"ok": all(item.get("ok") for item in steps), "steps": len(steps)},
                     ensure_ascii=False))
    return 0 if all(item.get("ok") for item in steps) else 1


if __name__ == "__main__":
    raise SystemExit(main())
