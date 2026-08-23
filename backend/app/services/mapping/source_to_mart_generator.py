"""Governed Source-to-Mart draft generation.

Shared facts cross the model boundary only through the single immutable
``RegulatoryContext`` projection built by :mod:`generator_context`. The
database row remains optimistic: no task lock is held while Context or the
model is running, and a fresh short transaction reauthorizes and compares the
canonical local snapshot before applying any output.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project, SourceToMartMapping
from app.services.auth.dependencies import Principal
from app.services.auth.permission_service import PermissionService
from app.services.governance.audit import record_audit
from app.services.llm.prompt_runtime import (
    execute_runtime_chat,
    get_prompt_runtime,
    prepare_model_input,
)
from app.services.llm.structured_outputs import SourceToMartOutput
from app.services.mapping.context_adapters import (
    GenerationOutputPolicy,
    SourceToMartContextAdapter,
    apply_generation_output_policy,
    redacted_generation_output_trace,
)
from app.services.mapping.generator_context import (
    GenerationBlockedError,
    GenerationContextEnvelope,
    GenerationStaleError,
    build_generation_context,
    compare_generation_snapshots,
    snapshot_source_to_mart_generation,
    validate_generation_actor,
)


_CLASSIFICATION_RANK = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}


async def generate_source_to_mart_draft(
    db: Session,
    mapping_id: int,
    *,
    authorized_project: Project,
    actor: Principal,
    as_of: date | None = None,
    today_provider: Callable[[], date] = date.today,
) -> SourceToMartMapping:
    """Generate one Source-to-Mart AI draft through governed Context only."""

    mapping = db.get(SourceToMartMapping, mapping_id)
    if mapping is None:
        raise ValueError("Source-to-mart mapping not found")
    if mapping.project_id != authorized_project.id:
        raise GenerationStaleError(["task.project_id"])

    validate_generation_actor(db, actor)
    snapshot = snapshot_source_to_mart_generation(mapping, authorized_project)
    envelope = build_generation_context(
        db,
        snapshot=snapshot,
        authorized_project=authorized_project,
        actor=actor,
        explicit_as_of=as_of,
        adapter=SourceToMartContextAdapter().project,
        today_provider=today_provider,
    )
    if not envelope.projection.readiness.can_generate:
        _record_generation_audit(
            db,
            envelope,
            action="generate_source_to_mart_blocked",
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

    runtime = get_prompt_runtime(db, "source_to_mart_mapping")
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
        SourceToMartOutput,
        confidentiality=_highest_confidentiality(
            envelope.projection.confidentiality_levels
        ),
        retrieval_log_id=_first_retrieval_log_id(
            envelope.trace.retrieval_log_ids
        ),
    )

    # Persist the model attempt independently, then discard every ORM value
    # retained across Context/model work before opening the authoritative write.
    db.commit()
    db.expire_all()

    stale_error: GenerationStaleError | None = None
    result: SourceToMartMapping | None = None
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
            select(SourceToMartMapping)
            .where(SourceToMartMapping.id == snapshot.task.id)
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
            current_snapshot = snapshot_source_to_mart_generation(
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
                action="generate_source_to_mart_stale",
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
                action="generate_source_to_mart",
                result="success",
                actor=actor,
                extra={"output": output_trace.model_dump(mode="json")},
            )
            result = locked_mapping

    if stale_error is not None:
        raise stale_error
    if result is None:  # pragma: no cover - defensive invariant
        raise RuntimeError("Source-to-mart generation produced no write result")
    db.refresh(result)
    return result


def _apply_output(
    mapping: SourceToMartMapping,
    policy: GenerationOutputPolicy,
) -> None:
    output = policy.output_fields
    mapping.source_system_summary = (
        output.get("source_system_summary") or mapping.source_system_summary
    )
    mapping.source_tables_summary = (
        output.get("source_tables_summary") or mapping.source_tables_summary
    )
    mapping.source_fields_summary = (
        output.get("source_fields_summary") or mapping.source_fields_summary
    )
    mapping.business_rule = (
        output.get("business_rule")
        or output.get("business_to_mart_rule")
        or mapping.business_rule
    )
    mapping.filter_condition = (
        output.get("filter_condition") or mapping.filter_condition
    )
    mapping.join_condition = output.get("join_condition") or mapping.join_condition
    mapping.priority_rule = output.get("priority_rule") or mapping.priority_rule
    mapping.merge_rule = output.get("merge_rule") or mapping.merge_rule
    mapping.code_mapping_rule = (
        output.get("code_mapping_rule") or mapping.code_mapping_rule
    )
    mapping.null_handling_rule = (
        output.get("null_handling_rule") or mapping.null_handling_rule
    )
    mapping.exception_rule = output.get("exception_rule") or mapping.exception_rule
    mapping.quality_check_rule = (
        output.get("quality_check_rule") or mapping.quality_check_rule
    )
    mapping.open_questions = policy.merged_questions.text
    mapping.confidence_level = policy.confidence_level
    mapping.ai_generated_content = _business_final_content(mapping, output)


def _business_final_content(
    mapping: SourceToMartMapping,
    output: Mapping[str, object],
) -> str:
    draft = output.get("final_content_draft")
    if isinstance(draft, str) and draft and not _looks_like_raw_sql(draft):
        return f"业务系统到监管集市口径：\n{draft}"
    lines = [
        "业务系统到监管集市口径：",
        f"来源业务系统：{mapping.source_system_summary or '待确认'}",
        f"来源表：{mapping.source_tables_summary or '待确认'}",
        f"来源字段：{mapping.source_fields_summary or '待确认'}",
        f"业务规则：{mapping.business_rule or '待确认'}",
        f"过滤条件：{mapping.filter_condition or '待确认'}",
        f"关联条件：{mapping.join_condition or '待确认'}",
        f"优先级规则：{mapping.priority_rule or '待确认'}",
        f"多系统合并规则：{mapping.merge_rule or '待确认'}",
        f"码值转换：{mapping.code_mapping_rule or '待确认'}",
        f"空值处理：{mapping.null_handling_rule or '待确认'}",
        f"异常处理：{mapping.exception_rule or '待确认'}",
        f"质量校验规则：{mapping.quality_check_rule or '待确认'}",
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
        resource_type="source_to_mart_mapping",
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
