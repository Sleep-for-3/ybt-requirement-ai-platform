"""Replace only the model boundary; generators retain their final write guards."""
from app.schemas.ai_skill import SkillScope
from app.schemas.ai_skill_control import SkillContent
from app.services.ai_skills import runtime
from app.services.ai_skills.mapping_context import MAPPING_TASKS, build_mapping_envelope
from app.services.mapping.generator_context import GenerationBlockedError


async def generate_mapping_if_bound(db, actor, envelope, task_key):
    project = envelope.snapshot.project
    if project.institution_id is None:
        return None
    scope = SkillScope(scope_type="task", institution_id=project.institution_id, project_id=project.id,
        invocation_key=MAPPING_TASKS[task_key][0])
    resolved = runtime.resolve_skill(db, actor, task_key, scope)
    if resolved is None:
        return None
    if envelope.actor.user_id != actor.user_id:
        raise GenerationBlockedError(["SKILL_CONTEXT_ACTOR_MISMATCH"])
    definition, version, binding = resolved
    content = SkillContent.model_validate(version.content_json)
    try:
        compiled = build_mapping_envelope(envelope, task_key, max_input_bytes=content.context_policy.max_input_bytes)
    except ValueError as exc:
        raise GenerationBlockedError(["SKILL_MAPPING_CONTEXT_INVALID"]) from exc
    result = await runtime.execute_resolved(db, compiled, definition, version, binding)
    if result.get("candidate") is None or result["execution_metadata"]["execution_kind"] == "degraded":
        # Match Legacy's failed-attempt persistence; do not mutate any draft.
        db.commit()
        raise GenerationBlockedError(["SKILL_MAPPING_OUTPUT_INVALID"])
    output = result["candidate"]
    questions = output.get("open_questions") or []
    if isinstance(questions, str):
        questions = [questions]
    output["open_questions"] = list(dict.fromkeys([*questions, *[gap["message"] for gap in result["gaps"]]]))
    if result["gaps"]:
        output["confidence_level"] = "low"
    return output, result["execution_metadata"]
