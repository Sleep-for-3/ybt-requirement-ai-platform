from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CatalogColumn,
    MappingEvidenceReference,
    ProductScenario,
    Project,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    TargetField,
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
    validate_generation_actor,
)
from app.services.retrieval import HybridRetriever


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


async def generate_technical_draft(db: Session, lineage_id: int) -> ScenarioTechnicalLineage:
    lineage = db.get(ScenarioTechnicalLineage, lineage_id)
    if lineage is None:
        raise ValueError("Scenario technical lineage not found")
    field = db.get(TargetField, lineage.target_field_id)
    scenario = db.get(ProductScenario, lineage.scenario_id)
    evidence = list(db.scalars(select(MappingEvidenceReference).where(
        MappingEvidenceReference.mapping_type == "scenario_technical",
        MappingEvidenceReference.mapping_id == lineage.id,
    ).order_by(MappingEvidenceReference.id)).all())
    evidence_text = "\n".join(item.evidence_summary or item.quoted_content or item.source_name for item in evidence)
    runtime=get_prompt_runtime(db,"scenario_technical_lineage");retrieval_log,knowledge=HybridRetriever(db).search(lineage.project_id,field.field_name if field else "",lineage.target_field_id,lineage.scenario_id,None,10);knowledge_text="\n".join(f"[{item['knowledge_unit_id']}] {item['content']}" for item in knowledge);context=_context(field,scenario,lineage,"\n".join(filter(None,[evidence_text,knowledge_text])));model_input=prepare_model_input(runtime,context,[item["confidentiality_level"] for item in knowledge],db=db,project_id=lineage.project_id);output = await execute_runtime_chat(db,lineage.project_id,runtime,model_input,ScenarioTechnicalOutput,retrieval_log_id=retrieval_log.id)
    physical_keys = {"source_database_name", "source_schema_name", "source_table_english_name", "source_field_english_name"}
    for key in ["source_system_name", "source_database_name", "source_schema_name", "source_table_english_name", "source_table_chinese_name", "source_field_english_name", "source_field_chinese_name", "processing_logic", "processing_logic_type", "tech_owner", "remarks"]:
        if output.get(key) is not None:
            if key in physical_keys and not _physical_value_allowed(db, lineage, key, output[key], output):
                continue
            setattr(lineage, key, output[key])
    lineage.open_questions = _text(output.get("open_questions")) or lineage.open_questions
    lineage.confidence_level = output.get("confidence_level") or lineage.confidence_level
    lineage.ai_generated_content = output.get("final_content_draft") or _technical_content(lineage, scenario)
    if evidence_text:
        lineage.ai_generated_content = f"{lineage.ai_generated_content}\n\n目录字段与安全探查摘要：\n{evidence_text}"
    record_audit(db, action="generate_technical_draft", resource_type="scenario_technical_lineage", resource_id=lineage.id, project_id=lineage.project_id, after={"confidence_level": lineage.confidence_level, "claim_type": output.get("claim_type", "evidence_supported" if evidence else "inferred"), "citation_count": len(output.get("citations") or evidence), "physical_source_changed": False})
    db.commit()
    db.refresh(lineage)
    return lineage


def _context(field, scenario, model, evidence_text: str | None = None, other_scenarios=None) -> str:
    return (
        f"目标字段：{field.field_code if field else '-'} / {field.field_name if field else '-'}\n"
        f"监管原始定义：{(field.regulatory_original_definition or field.regulatory_description) if field else '-'}\n"
        f"监管定义细化：{field.regulatory_refined_definition if field else '-'}\n"
        f"EAST 映射：{field.east_definition if field else '-'}\n"
        f"产品场景：{scenario.scenario_name if scenario else '-'}\n"
        f"当前人工信息：{model.__dict__}\n"
        f"已绑定目录字段、数据探查、SQL 血缘、历史口径和人工证据（优先引用）：{evidence_text or '无'}\n"
        f"同字段其他场景口径：{[item.final_content or item.ai_generated_content for item in (other_scenarios or [])]}"
    )


def _business_content(mapping, scenario_name: str | None) -> str:
    return f"{scenario_name or '当前场景'}业务口径：{mapping.business_definition or '待确认'}"


def _technical_content(lineage, scenario) -> str:
    return (
        f"{scenario.scenario_name if scenario else '当前场景'}技术溯源：来源系统 {lineage.source_system_name or '待确认'}，"
        f"来源表 {lineage.source_table_english_name or '待确认'}，来源字段 {lineage.source_field_english_name or '待确认'}，"
        f"处理逻辑 {lineage.processing_logic or '待确认'}。"
    )


def _text(value) -> str | None:
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return value if isinstance(value, str) else None


def _physical_value_allowed(db, lineage, key: str, value: str, output: dict) -> bool:
    current = getattr(lineage, key, None)
    if current:
        return str(current).lower() == str(value).lower()
    candidates = {
        "source_schema_name": output.get("source_schema_name") or lineage.source_schema_name,
        "source_table_english_name": output.get("source_table_english_name") or lineage.source_table_english_name,
        "source_field_english_name": output.get("source_field_english_name") or lineage.source_field_english_name,
    }
    candidates[key] = value
    if not all(candidates.values()):
        return False
    query = select(CatalogColumn.id).where(
        CatalogColumn.project_id == lineage.project_id,
        CatalogColumn.enabled.is_(True),
        CatalogColumn.schema_name == candidates["source_schema_name"],
        CatalogColumn.table_name == candidates["source_table_english_name"],
        CatalogColumn.column_name == candidates["source_field_english_name"],
    )
    return db.scalar(query.limit(1)) is not None
