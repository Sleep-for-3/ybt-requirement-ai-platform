"""Pinned Skill candidate execution within the existing requirement worker."""
import asyncio

from fastapi import HTTPException

from app.schemas.ai_skill import SkillScope
from app.schemas.ai_skill_control import SkillContent
from app.services.ai_skills import runtime
from app.services.ai_skills.requirement_context import build_requirement_envelope
from app.services.mapping.generator_context import recover_queued_actor


def generate_if_bound(db, row, item, project):
    if getattr(project, "institution_id", None) is None:
        return None
    actor = recover_queued_actor(db, row.created_by)
    # Reuse the complete authorization boundary even for direct internal callers.
    from app.services.requirement_generation_worker import authorize_input
    authorized = authorize_input(db, row, actor)
    if authorized.id != project.id:
        raise HTTPException(409, "需求项目范围已变化")
    scope = SkillScope(scope_type="task", institution_id=project.institution_id,
        project_id=project.id, invocation_key="requirement_fields")
    resolved = runtime.resolve_skill(db, actor, "requirement_candidate_generation", scope)
    if resolved is None:
        return None
    definition, version, binding = resolved
    content = SkillContent.model_validate(version.content_json)
    envelope = build_requirement_envelope(project, row, item, max_input_bytes=content.context_policy.max_input_bytes)
    result = asyncio.run(runtime.execute_resolved(db, envelope, definition, version, binding))
    if result["candidate"] is None or result["execution_metadata"]["execution_kind"] == "degraded":
        raise HTTPException(422, "Skill 候选未通过引用校验或模型不可用")
    candidate = result["candidate"]
    metadata = result["execution_metadata"]
    candidate["gaps"] = list(dict.fromkeys([*candidate["gaps"], *[gap["message"] for gap in result["gaps"]]]))
    if row.input_json.get("script_basis", {}).get("rules") and not candidate["script_rule_ids"]:
        candidate["gaps"].append("AI 解释尚未引用固定脚本规则，需核验解释与事实的一致性")
    candidate["execution_metadata"] = metadata
    candidate["regression_input"] = envelope.model_dump(mode="json")
    candidate["runtime"] = {"provider": metadata["provider_type"], "model": metadata["model_name"],
        "prompt_version": version.version_no, "test_provider": metadata["execution_kind"] == "mock_model",
        "execution_kind": metadata["execution_kind"]}
    return candidate
