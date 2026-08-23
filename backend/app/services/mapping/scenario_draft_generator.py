from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Project,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
)
from app.services.auth.dependencies import Principal
from app.services.auth.permission_service import PermissionService
from app.services.governance.audit import record_audit
from app.services.governance.scenario_review import ensure_scenario_mapping_editable
from app.services.llm.prompt_runtime import (
    execute_runtime_chat,
    get_prompt_runtime,
    prepare_model_input,
)
from app.services.llm.structured_outputs import (
    ScenarioBusinessOutput,
    ScenarioTechnicalOutput,
)
from app.services.mapping.context_adapters import (
    GenerationOutputPolicy,
    ScenarioBusinessContextAdapter,
    ScenarioTechnicalContextAdapter,
    apply_generation_output_policy,
    redacted_generation_output_trace,
)
from app.services.mapping.generator_context import (
    GenerationBlockedError,
    GenerationContextEnvelope,
    GenerationStaleError,
    build_generation_context,
    compare_generation_snapshots,
    snapshot_scenario_business_generation,
    snapshot_scenario_technical_generation,
    validate_generation_actor,
)


_CLASSIFICATION_RANK = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}


async def generate_business_draft(
    db: Session,
    mapping_id: int,
    *,
    authorized_project: Project,
    actor: Principal,
    as_of: date | None = None,
    today_provider: Callable[[], date] = date.today,
) -> ScenarioBusinessMapping:
    """Generate one Scenario business AI draft through governed Context only."""

    mapping = db.get(ScenarioBusinessMapping, mapping_id)
    if mapping is None:
        raise ValueError("Scenario business mapping not found")
    if mapping.project_id != authorized_project.id:
        raise GenerationStaleError(["task.project_id"])

    validate_generation_actor(db, actor)
    snapshot = snapshot_scenario_business_generation(mapping, authorized_project)
    envelope = build_generation_context(
        db,
        snapshot=snapshot,
        authorized_project=authorized_project,
        actor=actor,
        explicit_as_of=as_of,
        adapter=ScenarioBusinessContextAdapter().project,
        today_provider=today_provider,
    )
    if not envelope.projection.readiness.can_generate:
        _record_business_generation_audit(
            db,
            envelope,
            action="generate_business_draft_blocked",
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

    runtime = get_prompt_runtime(db, "scenario_business_mapping")
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
        ScenarioBusinessOutput,
        confidentiality=_highest_confidentiality(
            envelope.projection.confidentiality_levels
        ),
        retrieval_log_id=_first_retrieval_log_id(
            envelope.trace.retrieval_log_ids
        ),
    )

    # Persist attempt-only model records, then discard ORM state retained across
    # Context/model work before opening the authoritative write transaction.
    db.commit()
    db.expire_all()

    stale_error: GenerationStaleError | None = None
    result: ScenarioBusinessMapping | None = None
    with db.begin():
        validate_generation_actor(db, actor)
        reauthorized = PermissionService(db, actor).require_project_permission(
            snapshot.project.id,
            "business.edit",
        )
        locked_project = db.scalar(
            select(Project)
            .where(Project.id == snapshot.project.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        locked_mapping = db.scalar(
            select(ScenarioBusinessMapping)
            .where(ScenarioBusinessMapping.id == snapshot.task.id)
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
            ensure_scenario_mapping_editable(
                db,
                "scenario_business",
                locked_mapping.id,
            )
            current_snapshot = snapshot_scenario_business_generation(
                locked_mapping,
                locked_project,
            )
            changed_fields = compare_generation_snapshots(
                snapshot,
                current_snapshot,
            )

        if changed_fields:
            stale_error = GenerationStaleError(changed_fields)
            _record_business_generation_audit(
                db,
                envelope,
                action="generate_business_draft_stale",
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
            scenario_name = None
            context_scenario = getattr(getattr(envelope, "context", None), "scenario", None)
            if context_scenario is not None:
                scenario_name = context_scenario.scenario_name
            _apply_business_output(
                locked_mapping,
                policy,
                scenario_name=scenario_name,
            )
            output_trace = redacted_generation_output_trace(policy)
            _record_business_generation_audit(
                db,
                envelope,
                action="generate_business_draft",
                result="success",
                actor=actor,
                extra={"output": output_trace.model_dump(mode="json")},
            )
            result = locked_mapping

    if stale_error is not None:
        raise stale_error
    if result is None:  # pragma: no cover - defensive invariant
        raise RuntimeError("Scenario business generation produced no write result")
    db.refresh(result)
    return result


def _apply_business_output(
    mapping: ScenarioBusinessMapping,
    policy: GenerationOutputPolicy,
    *,
    scenario_name: str | None,
) -> None:
    output = policy.output_fields
    for key in (
        "business_definition",
        "source_system_screenshot_required",
        "source_system_change_required",
        "external_data_required",
        "manual_supplement_required",
        "business_owner",
        "remarks",
    ):
        if key in output:
            setattr(mapping, key, output[key])
    mapping.open_questions = policy.merged_questions.text
    mapping.confidence_level = policy.confidence_level
    draft = output.get("final_content_draft")
    mapping.ai_generated_content = (
        draft
        if isinstance(draft, str) and draft.strip()
        else _business_content(mapping, scenario_name)
    )


def _record_business_generation_audit(
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
        resource_type="scenario_business_mapping",
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


async def generate_technical_draft(
    db: Session,
    lineage_id: int,
    *,
    authorized_project: Project,
    actor: Principal,
    as_of: date | None = None,
    today_provider: Callable[[], date] = date.today,
) -> ScenarioTechnicalLineage:
    """Generate one Scenario technical AI draft through governed Context only."""

    lineage = db.get(ScenarioTechnicalLineage, lineage_id)
    if lineage is None:
        raise ValueError("Scenario technical lineage not found")
    if lineage.project_id != authorized_project.id:
        raise GenerationStaleError(["task.project_id"])

    validate_generation_actor(db, actor)
    snapshot = snapshot_scenario_technical_generation(lineage, authorized_project)
    envelope = build_generation_context(
        db,
        snapshot=snapshot,
        authorized_project=authorized_project,
        actor=actor,
        explicit_as_of=as_of,
        adapter=ScenarioTechnicalContextAdapter().project,
        today_provider=today_provider,
    )
    if not envelope.projection.readiness.can_generate:
        _record_technical_generation_audit(
            db,
            envelope,
            action="generate_technical_draft_blocked",
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

    runtime = get_prompt_runtime(db, "scenario_technical_lineage")
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
        ScenarioTechnicalOutput,
        confidentiality=_highest_confidentiality(
            envelope.projection.confidentiality_levels
        ),
        retrieval_log_id=_first_retrieval_log_id(
            envelope.trace.retrieval_log_ids
        ),
    )

    # Persist attempt-only model records before the authoritative write phase.
    db.commit()
    db.expire_all()

    stale_error: GenerationStaleError | None = None
    result: ScenarioTechnicalLineage | None = None
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
        locked_lineage = db.scalar(
            select(ScenarioTechnicalLineage)
            .where(ScenarioTechnicalLineage.id == snapshot.task.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

        changed_fields: list[str]
        if locked_project is None or locked_lineage is None:
            changed_fields = [
                "project.deleted" if locked_project is None else "task.deleted"
            ]
        elif reauthorized.id != locked_project.id:
            changed_fields = ["project.authorization_scope"]
        elif locked_lineage.project_id != locked_project.id:
            changed_fields = ["task.project_id"]
        else:
            ensure_scenario_mapping_editable(
                db,
                "scenario_technical",
                locked_lineage.id,
            )
            current_snapshot = snapshot_scenario_technical_generation(
                locked_lineage,
                locked_project,
            )
            changed_fields = compare_generation_snapshots(
                snapshot,
                current_snapshot,
            )

        if changed_fields:
            stale_error = GenerationStaleError(changed_fields)
            _record_technical_generation_audit(
                db,
                envelope,
                action="generate_technical_draft_stale",
                result="stale",
                actor=actor,
                extra={"changed_fields": changed_fields},
            )
        else:
            policy = apply_generation_output_policy(
                envelope.projection,
                output,
                existing_human_questions=locked_lineage.open_questions,
            )
            physical_before = _technical_physical_source(locked_lineage)
            scenario_name = None
            context_scenario = getattr(
                getattr(envelope, "context", None),
                "scenario",
                None,
            )
            if context_scenario is not None:
                scenario_name = context_scenario.scenario_name
            _apply_technical_output(
                locked_lineage,
                policy,
                scenario_name=scenario_name,
                supporting_evidence_summaries=(
                    envelope.projection.supporting_evidence_summaries
                ),
            )
            output_trace = redacted_generation_output_trace(policy)
            _record_technical_generation_audit(
                db,
                envelope,
                action="generate_technical_draft",
                result="success",
                actor=actor,
                extra={
                    "output": output_trace.model_dump(mode="json"),
                    "physical_source_changed": (
                        _technical_physical_source(locked_lineage)
                        != physical_before
                    ),
                },
            )
            result = locked_lineage

    if stale_error is not None:
        raise stale_error
    if result is None:  # pragma: no cover - defensive invariant
        raise RuntimeError("Scenario technical generation produced no write result")
    db.refresh(result)
    return result


def _business_content(mapping, scenario_name: str | None) -> str:
    return f"{scenario_name or '当前场景'}业务口径：{mapping.business_definition or '待确认'}"


def _apply_technical_output(
    lineage: ScenarioTechnicalLineage,
    policy: GenerationOutputPolicy,
    *,
    scenario_name: str | None,
    supporting_evidence_summaries: tuple[str, ...] = (),
) -> None:
    output = policy.output_fields
    for key in (
        "source_system_name",
        "source_database_name",
        "source_schema_name",
        "source_table_english_name",
        "source_table_chinese_name",
        "source_field_english_name",
        "source_field_chinese_name",
        "processing_logic",
        "processing_logic_type",
        "tech_owner",
        "remarks",
    ):
        if key in output:
            setattr(lineage, key, output[key])
    lineage.open_questions = policy.merged_questions.text
    lineage.confidence_level = policy.confidence_level
    draft = output.get("final_content_draft")
    generated_content = (
        draft
        if isinstance(draft, str) and draft.strip()
        else _technical_content(lineage, scenario_name)
    )
    if supporting_evidence_summaries:
        generated_content = (
            f"{generated_content}\n\n目录字段与安全探查摘要：\n"
            + "\n".join(supporting_evidence_summaries)
        )
    lineage.ai_generated_content = generated_content


def _record_technical_generation_audit(
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
        resource_type="scenario_technical_lineage",
        resource_id=envelope.snapshot.task.id,
        actor_user_id=actor.user_id,
        institution_id=envelope.snapshot.project.institution_id,
        project_id=envelope.snapshot.project.id,
        after=after,
        result=result,
    )


def _technical_physical_source(
    lineage: ScenarioTechnicalLineage,
) -> tuple[str | None, str | None, str | None, str | None]:
    return (
        lineage.source_database_name,
        lineage.source_schema_name,
        lineage.source_table_english_name,
        lineage.source_field_english_name,
    )


def _technical_content(
    lineage: ScenarioTechnicalLineage,
    scenario_name: str | None,
) -> str:
    return (
        f"{scenario_name or '当前场景'}技术溯源：来源系统 {lineage.source_system_name or '待确认'}，"
        f"来源表 {lineage.source_table_english_name or '待确认'}，来源字段 {lineage.source_field_english_name or '待确认'}，"
        f"处理逻辑 {lineage.processing_logic or '待确认'}。"
    )
