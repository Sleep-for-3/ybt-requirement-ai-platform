"""Seed a demo requirement whose frozen snapshot pins a regulatory version (R6)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import Requirement, User  # noqa: E402
from app.services.requirement_revisions import (  # noqa: E402
    append_revision, initialize_content, load_revision,
)

NAME = "R6 版本钉扎演示需求"
PIN_TITLE = "产品期限组合键管理办法"
PIN_VERSION = "2026-v1"


def main() -> None:
    with SessionLocal() as db:
        project_id = 7
        table_id = 7
        field_id = 5
        pm = db.scalar(select(User).where(User.username == "p0c-pm"))
        if pm is None:
            raise SystemExit("p0c-pm missing; run scripts/vnext2_p0c_browser_seed.py first")
        requirement = db.scalar(
            select(Requirement).where(
                Requirement.project_id == project_id, Requirement.name == NAME
            )
        )
        if requirement is None:
            requirement = Requirement(
                project_id=project_id,
                name=NAME,
                version=1,
                content_version=0,
                scope_json={
                    "target_table_id": table_id,
                    "field_ids": [field_id],
                    "scenario_id": None,
                },
            )
            db.add(requirement)
            db.commit()
            db.refresh(requirement)
        if requirement.content_version == 0:
            initialize_content(db, requirement, expected_scope=requirement.version, actor_id=pm.id)
            db.commit()
            db.refresh(requirement)
        revision = load_revision(db, project_id, requirement.id, requirement.content_version)
        content = revision.content_json
        field = content["fields"][0]
        evidence = [item for item in (field.get("evidence") or []) if isinstance(item, dict)]
        if not any(item.get("regulatory_version") == PIN_VERSION for item in evidence):
            evidence.append(
                {
                    "evidence_id": 11,
                    "title": PIN_TITLE,
                    "regulatory_version": PIN_VERSION,
                    "content": "产品标识与期限编号共同构成唯一业务键（合成制度条款，仅用于演示）。",
                }
            )
            field["evidence"] = evidence
            append_revision(
                db, requirement, content, expected=requirement.content_version, actor_id=pm.id
            )
            db.commit()
            db.refresh(requirement)
        print(
            f"requirement_id={requirement.id} content_version={requirement.content_version} "
            f"pin={PIN_TITLE}={PIN_VERSION}"
        )


if __name__ == "__main__":
    main()


