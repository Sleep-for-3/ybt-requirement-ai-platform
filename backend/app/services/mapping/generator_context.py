"""Authorized one-build seam shared by all regulatory generators.

This module owns only identity validation, immutable task/project snapshots,
business-date resolution, the single candidate-mode Context build, and a
redacted trace envelope. Shared business facts remain exclusively owned by
``RegulatoryContextBuilder``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.models import (
    MartToYbtMapping,
    Project,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    SourceToMartMapping,
    User,
)
from app.schemas.regulatory_context import (
    ContextMode,
    RegulatoryContext,
    RegulatoryContextRequest,
)
from app.services.auth.dependencies import Principal
from app.services.semantic.context_builder import RegulatoryContextBuilder


ProjectionT = TypeVar("ProjectionT")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GenerationActorError(ValueError):
    """The direct or queued actor cannot be trusted for generation."""


class GenerationBlockedError(RuntimeError):
    """Typed generation policy blocked model execution."""

    def __init__(self, reasons: list[str]):
        self.reasons = tuple(reasons)
        super().__init__("Generation blocked: " + ", ".join(self.reasons))


class GenerationStaleError(RuntimeError):
    """The canonical task/project snapshot changed before a governed write."""

    def __init__(self, changed_fields: list[str] | None = None):
        self.changed_fields = tuple(changed_fields or [])
        detail = ", ".join(self.changed_fields) or "resource missing or changed"
        super().__init__(f"Generation snapshot is stale: {detail}")


class ResolvedGenerationDate(_FrozenModel):
    as_of: date
    source: Literal["explicit", "current_business_date"]


class ProjectGenerationSnapshot(_FrozenModel):
    id: int
    institution_id: int | None
    project_status: str
    confidentiality_level: str
    governance_workflow_enabled: bool
    updated_at: str


class SourceToMartTaskSnapshot(_FrozenModel):
    id: int
    project_id: int
    mart_field_id: int
    mapping_name: str | None
    mapping_status: str
    source_system_summary: str | None
    source_tables_summary: str | None
    source_fields_summary: str | None
    business_rule: str | None
    filter_condition: str | None
    join_condition: str | None
    priority_rule: str | None
    merge_rule: str | None
    code_mapping_rule: str | None
    null_handling_rule: str | None
    exception_rule: str | None
    quality_check_rule: str | None
    open_questions: str | None
    ai_generated_content: str | None
    final_content: str | None
    confidence_level: str
    created_by: str | None
    reviewed_by: str | None
    reviewed_at: str | None
    lineage_status: str
    lineage_last_verified_at: str | None
    lineage_change_set_id: int | None
    updated_at: str


class SourceToMartGenerationSnapshot(_FrozenModel):
    task_type: Literal["source_to_mart"] = "source_to_mart"
    project: ProjectGenerationSnapshot
    task: SourceToMartTaskSnapshot


class MartToYbtTaskSnapshot(_FrozenModel):
    id: int
    project_id: int
    target_field_id: int
    mart_field_id: int | None
    mapping_name: str | None
    mapping_status: str
    mart_table_summary: str | None
    mart_field_summary: str | None
    business_rule: str | None
    filter_condition: str | None
    join_condition: str | None
    code_mapping_rule: str | None
    null_handling_rule: str | None
    reporting_condition: str | None
    validation_rule: str | None
    open_questions: str | None
    ai_generated_content: str | None
    final_content: str | None
    confidence_level: str
    created_by: str | None
    reviewed_by: str | None
    reviewed_at: str | None
    lineage_status: str
    lineage_last_verified_at: str | None
    lineage_change_set_id: int | None
    updated_at: str


class MartToYbtGenerationSnapshot(_FrozenModel):
    task_type: Literal["mart_to_ybt"] = "mart_to_ybt"
    project: ProjectGenerationSnapshot
    task: MartToYbtTaskSnapshot


class ScenarioBusinessTaskSnapshot(_FrozenModel):
    id: int
    project_id: int
    target_field_id: int
    scenario_id: int
    business_definition: str | None
    source_system_screenshot_required: bool
    source_system_change_required: bool
    external_data_required: bool
    manual_supplement_required: bool
    business_owner: str | None
    business_confirm_status: str
    business_confirm_at: str | None
    remarks: str | None
    ai_generated_content: str | None
    final_content: str | None
    confidence_level: str
    open_questions: str | None
    created_by: str | None
    updated_at: str


class ScenarioBusinessGenerationSnapshot(_FrozenModel):
    task_type: Literal["scenario_business"] = "scenario_business"
    project: ProjectGenerationSnapshot
    task: ScenarioBusinessTaskSnapshot


class ScenarioTechnicalTaskSnapshot(_FrozenModel):
    id: int
    project_id: int
    target_field_id: int
    scenario_id: int
    business_mapping_id: int | None
    source_system_name: str | None
    source_database_name: str | None
    source_schema_name: str | None
    source_table_english_name: str | None
    source_table_chinese_name: str | None
    source_field_english_name: str | None
    source_field_chinese_name: str | None
    processing_logic: str | None
    processing_logic_type: str | None
    tech_owner: str | None
    tech_confirm_status: str
    tech_confirm_at: str | None
    remarks: str | None
    ai_generated_content: str | None
    final_content: str | None
    confidence_level: str
    open_questions: str | None
    created_by: str | None
    lineage_status: str
    lineage_last_verified_at: str | None
    lineage_change_set_id: int | None
    updated_at: str


class ScenarioTechnicalGenerationSnapshot(_FrozenModel):
    task_type: Literal["scenario_technical"] = "scenario_technical"
    project: ProjectGenerationSnapshot
    task: ScenarioTechnicalTaskSnapshot


GenerationSnapshot = (
    SourceToMartGenerationSnapshot
    | MartToYbtGenerationSnapshot
    | ScenarioBusinessGenerationSnapshot
    | ScenarioTechnicalGenerationSnapshot
)


class GenerationTraceSummary(_FrozenModel):
    context_schema_version: str
    context_built_at: datetime
    resolved_as_of: date
    as_of_source: Literal["explicit", "current_business_date"]
    context_fact_count: int
    context_conflict_codes: list[str]
    context_question_codes: list[str]
    retrieval_log_ids: list[int]
    readiness_can_generate: bool
    readiness_confidence_cap: str
    prompt_projection_hash: str
    prompt_projection_truncated: bool


class GenerationContextEnvelope(BaseModel, Generic[ProjectionT]):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )

    actor: Principal
    snapshot: GenerationSnapshot
    resolved_date: ResolvedGenerationDate
    context: RegulatoryContext
    projection: ProjectionT
    trace: GenerationTraceSummary


def resolve_generation_as_of(
    explicit_as_of: date | None,
    *,
    task_created_at: object | None = None,
    reporting_label: object | None = None,
    today_provider: Callable[[], date] = date.today,
) -> ResolvedGenerationDate:
    """Resolve the business date without inventing a timestamp/text fallback."""

    # Current task/project models expose no reusable regulatory reporting date.
    # The named values are accepted only to make the intentional exclusion
    # explicit and testable; they are never parsed or promoted to business time.
    _ = (task_created_at, reporting_label)
    if explicit_as_of is not None:
        return ResolvedGenerationDate(as_of=explicit_as_of, source="explicit")
    return ResolvedGenerationDate(
        as_of=today_provider(),
        source="current_business_date",
    )


def snapshot_project_generation(project: Project) -> ProjectGenerationSnapshot:
    return ProjectGenerationSnapshot(
        id=project.id,
        institution_id=project.institution_id,
        project_status=project.project_status,
        confidentiality_level=project.confidentiality_level,
        governance_workflow_enabled=project.governance_workflow_enabled,
        updated_at=_required_timestamp(project.updated_at, "Project.updated_at"),
    )


def snapshot_source_to_mart_generation(
    task: SourceToMartMapping,
    project: Project,
) -> SourceToMartGenerationSnapshot:
    """Serialize every local input/editability field explicitly; never ORM state."""

    return SourceToMartGenerationSnapshot(
        project=snapshot_project_generation(project),
        task=SourceToMartTaskSnapshot(
            id=task.id,
            project_id=task.project_id,
            mart_field_id=task.mart_field_id,
            mapping_name=task.mapping_name,
            mapping_status=task.mapping_status,
            source_system_summary=task.source_system_summary,
            source_tables_summary=task.source_tables_summary,
            source_fields_summary=task.source_fields_summary,
            business_rule=task.business_rule,
            filter_condition=task.filter_condition,
            join_condition=task.join_condition,
            priority_rule=task.priority_rule,
            merge_rule=task.merge_rule,
            code_mapping_rule=task.code_mapping_rule,
            null_handling_rule=task.null_handling_rule,
            exception_rule=task.exception_rule,
            quality_check_rule=task.quality_check_rule,
            open_questions=task.open_questions,
            ai_generated_content=task.ai_generated_content,
            final_content=task.final_content,
            confidence_level=task.confidence_level,
            created_by=task.created_by,
            reviewed_by=task.reviewed_by,
            reviewed_at=_optional_timestamp(task.reviewed_at),
            lineage_status=task.lineage_status,
            lineage_last_verified_at=_optional_timestamp(task.lineage_last_verified_at),
            lineage_change_set_id=task.lineage_change_set_id,
            updated_at=_required_timestamp(task.updated_at, "SourceToMartMapping.updated_at"),
        ),
    )


def snapshot_mart_to_ybt_generation(
    task: MartToYbtMapping,
    project: Project,
) -> MartToYbtGenerationSnapshot:
    return MartToYbtGenerationSnapshot(
        project=snapshot_project_generation(project),
        task=MartToYbtTaskSnapshot(
            id=task.id,
            project_id=task.project_id,
            target_field_id=task.target_field_id,
            mart_field_id=task.mart_field_id,
            mapping_name=task.mapping_name,
            mapping_status=task.mapping_status,
            mart_table_summary=task.mart_table_summary,
            mart_field_summary=task.mart_field_summary,
            business_rule=task.business_rule,
            filter_condition=task.filter_condition,
            join_condition=task.join_condition,
            code_mapping_rule=task.code_mapping_rule,
            null_handling_rule=task.null_handling_rule,
            reporting_condition=task.reporting_condition,
            validation_rule=task.validation_rule,
            open_questions=task.open_questions,
            ai_generated_content=task.ai_generated_content,
            final_content=task.final_content,
            confidence_level=task.confidence_level,
            created_by=task.created_by,
            reviewed_by=task.reviewed_by,
            reviewed_at=_optional_timestamp(task.reviewed_at),
            lineage_status=task.lineage_status,
            lineage_last_verified_at=_optional_timestamp(task.lineage_last_verified_at),
            lineage_change_set_id=task.lineage_change_set_id,
            updated_at=_required_timestamp(task.updated_at, "MartToYbtMapping.updated_at"),
        ),
    )


def snapshot_scenario_business_generation(
    task: ScenarioBusinessMapping,
    project: Project,
) -> ScenarioBusinessGenerationSnapshot:
    return ScenarioBusinessGenerationSnapshot(
        project=snapshot_project_generation(project),
        task=ScenarioBusinessTaskSnapshot(
            id=task.id,
            project_id=task.project_id,
            target_field_id=task.target_field_id,
            scenario_id=task.scenario_id,
            business_definition=task.business_definition,
            source_system_screenshot_required=task.source_system_screenshot_required,
            source_system_change_required=task.source_system_change_required,
            external_data_required=task.external_data_required,
            manual_supplement_required=task.manual_supplement_required,
            business_owner=task.business_owner,
            business_confirm_status=task.business_confirm_status,
            business_confirm_at=_optional_timestamp(task.business_confirm_at),
            remarks=task.remarks,
            ai_generated_content=task.ai_generated_content,
            final_content=task.final_content,
            confidence_level=task.confidence_level,
            open_questions=task.open_questions,
            created_by=task.created_by,
            updated_at=_required_timestamp(
                task.updated_at,
                "ScenarioBusinessMapping.updated_at",
            ),
        ),
    )


def snapshot_scenario_technical_generation(
    task: ScenarioTechnicalLineage,
    project: Project,
) -> ScenarioTechnicalGenerationSnapshot:
    return ScenarioTechnicalGenerationSnapshot(
        project=snapshot_project_generation(project),
        task=ScenarioTechnicalTaskSnapshot(
            id=task.id,
            project_id=task.project_id,
            target_field_id=task.target_field_id,
            scenario_id=task.scenario_id,
            business_mapping_id=task.business_mapping_id,
            source_system_name=task.source_system_name,
            source_database_name=task.source_database_name,
            source_schema_name=task.source_schema_name,
            source_table_english_name=task.source_table_english_name,
            source_table_chinese_name=task.source_table_chinese_name,
            source_field_english_name=task.source_field_english_name,
            source_field_chinese_name=task.source_field_chinese_name,
            processing_logic=task.processing_logic,
            processing_logic_type=task.processing_logic_type,
            tech_owner=task.tech_owner,
            tech_confirm_status=task.tech_confirm_status,
            tech_confirm_at=_optional_timestamp(task.tech_confirm_at),
            remarks=task.remarks,
            ai_generated_content=task.ai_generated_content,
            final_content=task.final_content,
            confidence_level=task.confidence_level,
            open_questions=task.open_questions,
            created_by=task.created_by,
            lineage_status=task.lineage_status,
            lineage_last_verified_at=_optional_timestamp(task.lineage_last_verified_at),
            lineage_change_set_id=task.lineage_change_set_id,
            updated_at=_required_timestamp(
                task.updated_at,
                "ScenarioTechnicalLineage.updated_at",
            ),
        ),
    )


def compare_generation_snapshots(
    before: GenerationSnapshot,
    after: GenerationSnapshot,
) -> list[str]:
    """Return deterministic dotted paths whose canonical values changed."""

    before_values = _flatten_snapshot(before.model_dump(mode="json"))
    after_values = _flatten_snapshot(after.model_dump(mode="json"))
    return sorted(
        key
        for key in before_values.keys() | after_values.keys()
        if before_values.get(key) != after_values.get(key)
    )


def validate_generation_actor(db: Session, actor: Principal) -> Principal:
    """Validate a frozen direct actor while preserving all identity fields."""

    if actor.is_legacy_system:
        return actor
    if not isinstance(actor.user_id, int) or isinstance(actor.user_id, bool) or actor.user_id <= 0:
        raise GenerationActorError("Non-legacy generation requires a positive user_id")
    user = db.get(User, actor.user_id)
    if user is None or user.status != "active":
        raise GenerationActorError("Generation actor must resolve to an active User")
    return actor


def recover_queued_actor(db: Session, persisted_user_id: int | None) -> Principal:
    """Recover only an active non-legacy actor from a queued positive user id."""

    if (
        not isinstance(persisted_user_id, int)
        or isinstance(persisted_user_id, bool)
        or persisted_user_id <= 0
    ):
        raise GenerationActorError("Queued generation requires a positive persisted user id")
    user = db.get(User, persisted_user_id)
    if user is None or user.status != "active":
        raise GenerationActorError("Queued generation actor must resolve to an active User")
    return Principal(user.id, user.username, user.display_name, False)


def build_generation_context(
    db: Session,
    *,
    snapshot: GenerationSnapshot,
    actor: Principal,
    authorized_project: Project,
    explicit_as_of: date | None,
    adapter: Callable[[RegulatoryContext, GenerationSnapshot], ProjectionT],
    today_provider: Callable[[], date] = date.today,
) -> GenerationContextEnvelope[ProjectionT]:
    """Build exactly one governed Context and only then invoke the pure adapter."""

    validated_actor = validate_generation_actor(db, actor)
    current_project = snapshot_project_generation(authorized_project)
    if current_project != snapshot.project:
        raise GenerationStaleError(
            compare_generation_snapshots(
                snapshot,
                snapshot.model_copy(update={"project": current_project}),
            )
        )
    if snapshot.task.project_id != authorized_project.id:
        raise GenerationStaleError(["task.project_id"])

    resolved = resolve_generation_as_of(
        explicit_as_of,
        today_provider=today_provider,
    )
    request = _context_request_for_snapshot(
        snapshot,
        project_id=authorized_project.id,
        as_of=resolved.as_of,
    )
    context = RegulatoryContextBuilder(db).build(
        request,
        authorized_project=authorized_project,
    )
    projection = adapter(context, snapshot)
    readiness = getattr(projection, "readiness")
    trace = GenerationTraceSummary(
        context_schema_version=context.context_schema_version,
        context_built_at=context.build_metadata.built_at,
        resolved_as_of=resolved.as_of,
        as_of_source=resolved.source,
        context_fact_count=context.build_metadata.fact_count,
        context_conflict_codes=sorted({item.code for item in context.conflicts}),
        context_question_codes=sorted({item.question_code for item in context.open_questions}),
        retrieval_log_ids=context.build_metadata.retrieval_log_ids,
        readiness_can_generate=readiness.can_generate,
        readiness_confidence_cap=readiness.confidence_cap,
        prompt_projection_hash=str(getattr(projection, "projection_hash")),
        prompt_projection_truncated=bool(getattr(projection, "truncated")),
    )
    return GenerationContextEnvelope[ProjectionT](
        actor=validated_actor,
        snapshot=snapshot,
        resolved_date=resolved,
        context=context,
        projection=projection,
        trace=trace,
    )


def _context_request_for_snapshot(
    snapshot: GenerationSnapshot,
    *,
    project_id: int,
    as_of: date,
) -> RegulatoryContextRequest:
    common = {
        "project_id": project_id,
        "as_of": as_of,
        "mode": ContextMode.CANDIDATE,
    }
    if isinstance(snapshot, SourceToMartGenerationSnapshot):
        return RegulatoryContextRequest(
            **common,
            mart_field_id=snapshot.task.mart_field_id,
        )
    if isinstance(snapshot, MartToYbtGenerationSnapshot):
        return RegulatoryContextRequest(
            **common,
            target_field_id=snapshot.task.target_field_id,
            mart_field_id=snapshot.task.mart_field_id,
        )
    if isinstance(snapshot, ScenarioBusinessGenerationSnapshot):
        return RegulatoryContextRequest(
            **common,
            target_field_id=snapshot.task.target_field_id,
            scenario_id=snapshot.task.scenario_id,
        )
    if isinstance(snapshot, ScenarioTechnicalGenerationSnapshot):
        return RegulatoryContextRequest(
            **common,
            target_field_id=snapshot.task.target_field_id,
            scenario_id=snapshot.task.scenario_id,
        )
    raise TypeError(f"Unsupported generation snapshot: {type(snapshot).__name__}")


def _required_timestamp(value: object, field_name: str) -> str:
    normalized = _optional_timestamp(value)
    if normalized is None:
        raise ValueError(f"{field_name} is required for the canonical snapshot")
    return normalized


def _optional_timestamp(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _flatten_snapshot(value: object, prefix: str = "") -> dict[str, object]:
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key in sorted(value):
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten_snapshot(value[key], child_prefix))
        return result
    return {prefix: value}


__all__ = [
    "GenerationActorError",
    "GenerationBlockedError",
    "GenerationContextEnvelope",
    "GenerationSnapshot",
    "GenerationStaleError",
    "GenerationTraceSummary",
    "MartToYbtGenerationSnapshot",
    "MartToYbtTaskSnapshot",
    "ProjectGenerationSnapshot",
    "ResolvedGenerationDate",
    "ScenarioBusinessGenerationSnapshot",
    "ScenarioBusinessTaskSnapshot",
    "ScenarioTechnicalGenerationSnapshot",
    "ScenarioTechnicalTaskSnapshot",
    "SourceToMartGenerationSnapshot",
    "SourceToMartTaskSnapshot",
    "build_generation_context",
    "compare_generation_snapshots",
    "recover_queued_actor",
    "resolve_generation_as_of",
    "snapshot_project_generation",
    "snapshot_mart_to_ybt_generation",
    "snapshot_scenario_business_generation",
    "snapshot_scenario_technical_generation",
    "snapshot_source_to_mart_generation",
    "validate_generation_actor",
]
