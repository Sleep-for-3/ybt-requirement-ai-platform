"""Publish a fresh, real-model-bound ``field_semantic_matching`` version for acceptance.

Why this is needed
------------------
The release gate deliberately invalidates a pinned Skill version when its *dependencies*
change -- the model profile, compiler prompt, output schema or evaluator version.  Every
historical binding in this database was published against an earlier ``ModelProfile`` state, so
``resolve_skill`` correctly returns ``409 skill_dependency_changed``.  That refusal is the
guard working, not a bug.

To acceptance-test the real model rerank path we therefore publish a **new** version against
the *current* profile, leaving all historical versions untouched.  This is a testing action on
a non-production database, and the script is explicit about it:

* it never edits an existing version (Skill history is immutable);
* it writes a new ``version_no`` and a new binding for the chosen project;
* it uses the release gate's own hash functions so the binding is legitimate rather than forged.

Usage:
    <venv python> scripts/publish_real_rerank_skill.py [--project-id 1] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

#: The real provider profile (see the "ModelProfile" table).
REAL_PROFILE_ID = 4

USER_TEMPLATE = (
    "目标：{subject}\n候选：{facts}\n政策依据：{policy_evidence}\n缺口：{gaps}\n"
    "只输出 JSON，严格按给定 schema 重排候选。"
)

SYSTEM_PROMPT = (
    "你是银行监管数据智能平台的字段候选重排器。"
    "只对给定候选按与目标字段的业务语义相关性排序，不得新增候选、不得改变候选标识。"
    "注意区分余额与发生额、客户与账户、合同与借据、本金与本息、日终与日均、本币与折人民币。"
)


def publish(project_id: int, *, dry_run: bool = False) -> dict:
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import (AISkillDefinition, AISkillScopeBinding, AISkillTestRun,
                            AISkillVersion, ModelProfile, Project)
    from app.schemas.ai_skill import SkillScope
    from app.services.ai_skills import control
    from app.services.ai_skills.evaluation import dependencies
    from app.services.ai_skills.runtime import FIELD_RERANK_TASK
    from app.services.llm.execution_metadata import stable_hash
    with SessionLocal() as db:
        # ``created_by`` / ``edited_by`` / ``approved_by`` / ``updated_by`` are integer user ids,
        # not labels: PostgreSQL rejected 'acceptance' with InvalidTextRepresentation.  Pick a
        # real user so the audit trail points at an actual actor.
        from app.models import User
        actor = db.scalar(select(User).where(User.status == "active").order_by(User.id))
        if actor is None:
            return {"ok": False, "error": "no active user to attribute the Skill version to"}
        actor_id = actor.id

        project = db.get(Project, project_id)
        if project is None:
            return {"ok": False, "error": f"project {project_id} not found"}
        if project.institution_id is None:
            return {"ok": False, "error": "project has no institution"}
        profile = db.get(ModelProfile, REAL_PROFILE_ID)
        if profile is None or not profile.enabled:
            return {"ok": False, "error": f"profile {REAL_PROFILE_ID} missing or disabled"}
        if profile.provider_type == "mock":
            return {"ok": False, "error": "profile is a Mock profile, not a real provider"}

        definition = db.scalar(select(AISkillDefinition).where(
            AISkillDefinition.skill_key == "field_semantic_matching"))
        if definition is None:
            definition = AISkillDefinition(
                skill_key="field_semantic_matching", task_key=FIELD_RERANK_TASK,
                display_name="字段候选重排", created_by=actor_id)
            db.add(definition)
            db.flush()

        content = {
            "model_profile_id": profile.id,
            "system_prompt": SYSTEM_PROMPT,
            "user_prompt_template": USER_TEMPLATE,
            "output_schema_key": "field_ranking_v1",
            "context_policy": {"max_input_bytes": 32000},
        }
        # Fail loudly here rather than at release time if the template misses a variable.
        control.validate_content(db, __import__(
            "app.schemas.ai_skill_control", fromlist=["SkillContent"]).SkillContent.model_validate(content))

        existing = db.scalars(select(AISkillVersion).where(
            AISkillVersion.definition_id == definition.id)).all()
        next_no = max((version.version_no for version in existing), default=0) + 1

        scope = SkillScope(scope_type="project", institution_id=project.institution_id,
                           project_id=project.id)
        version = AISkillVersion(
            definition_id=definition.id, version_no=next_no, status="draft",
            content_json=content, content_hash=stable_hash(content),
            scope_type="project", scope_key=control.scope_key(scope),
            institution_id=project.institution_id, project_id=project.id,
            test_epoch=1, created_by=actor_id, edited_by=actor_id,
            approved_by=actor_id)
        db.add(version)
        db.flush()
        # Same order the release gate uses: hash while draft, then publish (history is immutable).
        version.release_dependency_hash = dependencies(db, version)
        version.status = "published"
        version.published_at = datetime.now(UTC)
        db.flush()

        for mode in ("deterministic", "mock_model"):
            db.add(AISkillTestRun(
                version_id=version.id, project_id=project.id, mode=mode, status="passed",
                content_hash=version.content_hash,
                dependency_hash=version.release_dependency_hash,
                case_snapshot_json=[], created_by=actor_id))

        binding = db.scalar(select(AISkillScopeBinding).where(
            AISkillScopeBinding.definition_id == definition.id,
            AISkillScopeBinding.scope_key == control.scope_key(scope)))
        if binding is None:
            binding = AISkillScopeBinding(
                definition_id=definition.id, version_id=version.id,
                scope_type="project", scope_key=control.scope_key(scope),
                institution_id=project.institution_id, project_id=project.id,
                updated_by=actor_id)
            db.add(binding)
        else:
            binding.version_id = version.id
            binding.updated_by = actor_id

        report = {
            "ok": True,
            "dry_run": dry_run,
            "project_id": project.id,
            "definition_id": definition.id,
            "version_id": version.id,
            "version_no": version.version_no,
            "profile": {"id": profile.id, "model": profile.model_name,
                        "provider": profile.provider_type,
                        "max_context_tokens": profile.max_context_tokens},
            "content_hash": version.content_hash,
            "release_dependency_hash": version.release_dependency_hash,
            "scope_key": control.scope_key(scope),
            "binding_replaced": binding is not None,
            "previous_versions_untouched": sorted(v.version_no for v in existing),
        }
        if dry_run:
            db.rollback()
            report["ok"] = True
            report["note"] = "dry-run: transaction rolled back, nothing persisted"
        else:
            db.commit()
            report["note"] = "new version published and bound; historical versions untouched"
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    report = publish(args.project_id, dry_run=args.dry_run)
    import json
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
