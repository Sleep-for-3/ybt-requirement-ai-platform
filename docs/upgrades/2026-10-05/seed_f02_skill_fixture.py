"""Seed a minimal synthetic Skill definition and model profile into the isolated database.

F02 (Skill unsaved-changes guard + local draft recovery) cannot be exercised in a browser without at
least one editable Skill draft, and the phase-4 fixture deliberately contains none. This script adds
exactly that minimum, on the throw-away database only (N13 guard runs before any write):

* one ``ModelProfile`` so the editor's model select is populated;
* one ``AISkillDefinition`` plus a **draft** ``AISkillVersion`` whose content is a valid Skill body.

Nothing here touches the business database, and running it twice is a no-op (existence-checked).
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

SKILL_KEY = "f02_synthetic_skill"
TASK_KEY = "requirement_document_assistance"


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
        args.database, script="seed_f02_skill_fixture.py", host=args.host, port=args.port,
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

    from app.models import AISkillDefinition, AISkillVersion, ModelProfile, Project, User

    engine = create_engine(url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    steps: list[dict] = []

    def step(name: str, **payload: object) -> None:
        record = {"step": name, **payload}
        steps.append(record)
        print(json.dumps({"f02_seed": record}, ensure_ascii=False), flush=True)

    with factory() as db:
        project = db.scalar(select(Project).order_by(Project.id).limit(1))
        actor = db.scalar(select(User).where(User.username == "p4_platform_admin"))
        if project is None or actor is None:
            step("missing_prerequisites", ok=False, project=bool(project), actor=bool(actor))
            return 3

        profile = db.scalar(select(ModelProfile).order_by(ModelProfile.id).limit(1))
        if profile is None:
            profile = ModelProfile(
                profile_name="synthetic-verification-model",
                provider_type="mock",
                model_name="mock-model",
                enabled=True,
                local_only=True,
                supports_structured_output=True,
                max_context_tokens=8192,
                temperature=0.0,
                config_json={},
                created_by=int(actor.id),
            )
            db.add(profile)
            db.flush()
        step("model_profile_ready", ok=True, profile_id=int(profile.id))

        definition = db.scalar(select(AISkillDefinition).where(
            AISkillDefinition.skill_key == SKILL_KEY))
        if definition is None:
            definition = AISkillDefinition(
                skill_key=SKILL_KEY,
                task_key=TASK_KEY,
                display_name="F02 verification skill",
                description="Used to verify the Skill unsaved-changes guard and draft recovery.",
                next_version_no=2,
                created_by=int(actor.id),
            )
            db.add(definition)
            db.flush()
        step("skill_definition_ready", ok=True, definition_id=int(definition.id))

        version = db.scalar(select(AISkillVersion).where(
            AISkillVersion.definition_id == definition.id, AISkillVersion.version_no == 1))
        if version is None:
            content = {
                "system_prompt": "Synthetic verification assistant: return structured suggestions only.",
                "user_prompt_template": "field={{field_name}}\nevidence={{evidence}}",
                "model_profile_id": int(profile.id),
                "context_policy": {
                    "providers": ["script_evidence", "asset_identity"],
                    "max_input_bytes": 64000,
                    "max_depth": 4,
                    "max_paths": 20,
                    "max_policy_clauses": 12,
                    "overflow_policy": "fail_with_breakdown",
                },
            }
            material = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            version = AISkillVersion(
                definition_id=int(definition.id),
                version_no=1,
                # ``ck_ai_skill_version_positive`` requires version_no > 0 **and** lock_version > 0,
                # and ``ck_ai_skill_version_scope`` requires a project-scoped row to carry both
                # institution_id and project_id. These are real DB contracts, not fixture choices.
                status="draft",
                lock_version=1,
                test_epoch=0,
                content_json=content,
                content_hash=hashlib.sha256(material.encode("utf-8")).hexdigest(),
                created_by=int(actor.id),
                edited_by=int(actor.id),
                scope_type="project",
                # ``control.scope_key`` is the canonical form: project scope is
                # "project:{institution_id}:{project_id}", not the bare project id.
                scope_key=f"project:{int(project.institution_id)}:{int(project.id)}",
                institution_id=int(project.institution_id),
                project_id=int(project.id),
            )
            db.add(version)
            db.flush()
        db.commit()
        step("draft_version_ready", ok=True, version_id=int(version.id),
             status=version.status, version_no=int(version.version_no))

    print(json.dumps({"ok": all(item.get("ok") for item in steps), "steps": len(steps)},
                     ensure_ascii=False))
    return 0 if all(item.get("ok") for item in steps) else 1


if __name__ == "__main__":
    raise SystemExit(main())
