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

from app.models import Project, SourceToMartMapping, User
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


GenerationSnapshot = SourceToMartGenerationSnapshot


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
    request = RegulatoryContextRequest(
        project_id=authorized_project.id,
        mart_field_id=snapshot.task.mart_field_id,
        as_of=resolved.as_of,
        mode=ContextMode.CANDIDATE,
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
    "ProjectGenerationSnapshot",
    "ResolvedGenerationDate",
    "SourceToMartGenerationSnapshot",
    "SourceToMartTaskSnapshot",
    "build_generation_context",
    "compare_generation_snapshots",
    "recover_queued_actor",
    "resolve_generation_as_of",
    "snapshot_project_generation",
    "snapshot_source_to_mart_generation",
    "validate_generation_actor",
]
