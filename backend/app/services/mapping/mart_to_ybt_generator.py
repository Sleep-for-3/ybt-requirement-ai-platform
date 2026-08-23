"""Governed Mart-to-YBT draft generation from one frozen Context projection."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MartToYbtMapping, Project
from app.services.auth.dependencies import Principal
from app.services.auth.permission_service import PermissionService
from app.services.governance.audit import record_audit
from app.services.llm.prompt_runtime import (
    execute_runtime_chat,
    get_prompt_runtime,
    prepare_model_input,
)
from app.services.llm.structured_outputs import MartToYbtOutput
from app.services.mapping.context_adapters import (
    GenerationOutputPolicy,
    MartToYbtContextAdapter,
    apply_generation_output_policy,
    redacted_generation_output_trace,
)
from app.services.mapping.generator_context import (
    GenerationBlockedError,
    GenerationContextEnvelope,
    GenerationStaleError,
    build_generation_context,
    compare_generation_snapshots,
    snapshot_mart_to_ybt_generation,
    validate_generation_actor,
)


_CLASSIFICATION_RANK = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}


async def generate_mart_to_ybt_draft(
    db: Session,
    mapping_id: int,
    *,
    authorized_project: Project,
    actor: Principal,
    as_of: date | None = None,
    today_provider: Callable[[], date] = date.today,
) -> MartToYbtMapping:
    """Generate a task-local draft without re-reading shared upstream facts."""

    mapping = db.get(MartToYbtMapping, mapping_id)
    if mapping is None:
        raise ValueError("Mart-to-YBT mapping not found")
    if mapping.project_id != authorized_project.id:
        raise GenerationStaleError(["task.project_id"])

    validate_generation_actor(db, actor)
    snapshot = snapshot_mart_to_ybt_generation(mapping, authorized_project)
    envelope = build_generation_context(
        db,
        snapshot=snapshot,
        authorized_project=authorized_project,
        actor=actor,
        explicit_as_of=as_of,
        adapter=MartToYbtContextAdapter().project,
        today_provider=today_provider,
    )
    if not envelope.projection.readiness.can_generate:
        _record_generation_audit(
            db,
            envelope,
            action="generate_mart_to_ybt_blocked",
            result="blocked",
            actor=actor,
            extra={
                "blocking_reasons": list(
                    envelope.projection.readiness.blocking_reasons
                ),
            },
        )
        db.commit()
        raise GenerationBlockedError(
            list(envelope.projection.readiness.blocking_reasons)
        )

    runtime = get_prompt_runtime(db, "mart_to_ybt_mapping")
    model_input = prepare_model_input(
        runtime,
        envelope.projection.prompt_text,
        envelope.projection.confidentiality_levels,
        db=db,
        project_id=snapshot.project.id,
    )
    output = await execute_runtime_chat(
        db,
        snapshot.project.id,
        runtime,
        model_input,
        MartToYbtOutput,
        confidentiality=_highest_confidentiality(
            envelope.projection.confidentiality_levels
        ),
        retrieval_log_id=_first_retrieval_log_id(
            envelope.trace.retrieval_log_ids
        ),
    )

    # Context and the model execute without a task lock. Persist the attempt,
    # expire old ORM state, then open the short authoritative write boundary.
    db.commit()
    db.expire_all()

    stale_error: GenerationStaleError | None = None
    result: MartToYbtMapping | None = None
    with db.begin():
        validate_generation_actor(db, actor)
        reauthorized = PermissionService(db, actor).require_project_permission(
            snapshot.project.id,
            "technical.edit",
        )
        locked_project = db.scalar(
            select(Project)
            .where(Project.id == snapshot.project.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        locked_mapping = db.scalar(
            select(MartToYbtMapping)
            .where(MartToYbtMapping.id == snapshot.task.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

        changed_fields: list[str]
        if locked_project is None or locked_mapping is None:
            changed_fields = [
                "project.deleted" if locked_project is None else "task.deleted"
            ]
        elif reauthorized.id != locked_project.id:
            changed_fields = ["project.authorization_scope"]
        elif locked_mapping.project_id != locked_project.id:
            changed_fields = ["task.project_id"]
        else:
            current_snapshot = snapshot_mart_to_ybt_generation(
                locked_mapping,
                locked_project,
            )
            changed_fields = compare_generation_snapshots(
                snapshot,
                current_snapshot,
            )

        if changed_fields:
            stale_error = GenerationStaleError(changed_fields)
            _record_generation_audit(
                db,
                envelope,
                action="generate_mart_to_ybt_stale",
                result="stale",
                actor=actor,
                extra={"changed_fields": changed_fields},
            )
        else:
            policy = apply_generation_output_policy(
                envelope.projection,
                output,
                existing_human_questions=locked_mapping.open_questions,
            )
            _apply_output(locked_mapping, policy)
            output_trace = redacted_generation_output_trace(policy)
            _record_generation_audit(
                db,
                envelope,
                action="generate_mart_to_ybt",
                result="success",
                actor=actor,
                extra={"output": output_trace.model_dump(mode="json")},
            )
            result = locked_mapping

    if stale_error is not None:
        raise stale_error
    if result is None:  # pragma: no cover - defensive invariant
        raise RuntimeError("Mart-to-YBT generation produced no write result")
    db.refresh(result)
    return result


def _apply_output(
    mapping: MartToYbtMapping,
    policy: GenerationOutputPolicy,
) -> None:
    output = policy.output_fields
    mapping.mart_table_summary = (
        output.get("mart_table_summary") or mapping.mart_table_summary
    )
    mapping.mart_field_summary = (
        output.get("mart_field_summary") or mapping.mart_field_summary
    )
    mapping.business_rule = (
        output.get("business_rule")
        or output.get("mart_to_ybt_rule")
        or mapping.business_rule
    )
    mapping.filter_condition = (
        output.get("filter_condition") or mapping.filter_condition
    )
    mapping.join_condition = output.get("join_condition") or mapping.join_condition
    mapping.code_mapping_rule = (
        output.get("code_mapping_rule") or mapping.code_mapping_rule
    )
    mapping.null_handling_rule = (
        output.get("null_handling_rule") or mapping.null_handling_rule
    )
    mapping.reporting_condition = (
        output.get("reporting_condition") or mapping.reporting_condition
    )
    mapping.validation_rule = (
        output.get("validation_rule") or mapping.validation_rule
    )
    mapping.open_questions = policy.merged_questions.text
    mapping.confidence_level = policy.confidence_level
    mapping.ai_generated_content = _business_final_content(mapping, output)


def _business_final_content(
    mapping: MartToYbtMapping,
    output: Mapping[str, object],
) -> str:
    draft = output.get("final_content_draft")
    if isinstance(draft, str) and draft and not _looks_like_raw_sql(draft):
        return f"监管集市到一表通口径：\n{draft}"
    lines = [
        "监管集市到一表通口径：",
        f"监管集市表：{mapping.mart_table_summary or '待确认'}",
        f"监管集市字段：{mapping.mart_field_summary or '待确认'}",
        f"业务规则：{mapping.business_rule or '待确认'}",
        f"过滤条件：{mapping.filter_condition or '待确认'}",
        f"关联条件：{mapping.join_condition or '待确认'}",
        f"码值转换：{mapping.code_mapping_rule or '待确认'}",
        f"空值处理：{mapping.null_handling_rule or '待确认'}",
        f"报送限制条件：{mapping.reporting_condition or '待确认'}",
        f"校验规则：{mapping.validation_rule or '待确认'}",
        f"待确认问题：{mapping.open_questions or '暂无'}",
    ]
    return "\n".join(lines)


def _record_generation_audit(
    db: Session,
    envelope: GenerationContextEnvelope,
    *,
    action: str,
    result: str,
    actor: Principal,
    extra: Mapping[str, object] | None = None,
) -> None:
    after = envelope.trace.model_dump(mode="json")
    after.update(dict(extra or {}))
    record_audit(
        db,
        action=action,
        resource_type="mart_to_ybt_mapping",
        resource_id=envelope.snapshot.task.id,
        actor_user_id=actor.user_id,
        institution_id=envelope.snapshot.project.institution_id,
        project_id=envelope.snapshot.project.id,
        after=after,
        result=result,
    )


def _first_retrieval_log_id(values: list[int]) -> int | None:
    return values[0] if values else None


def _highest_confidentiality(levels: list[str]) -> str:
    return max(
        levels or ["internal"],
        key=lambda value: _CLASSIFICATION_RANK.get(value, 1),
    )


def _looks_like_raw_sql(text: str) -> bool:
    stripped = text.strip().lower()
    return stripped.startswith(("select ", "with ")) and (
        " from " in stripped or "\nfrom " in stripped
    )
