"""Project-scoped collectors for the RegulatoryContext projection.

Collectors own SQL and return typed, bounded facts.  They accept the Project
already authorized by PermissionService; caller-supplied institution scope is
never accepted or inferred from free text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import (
    MartField,
    ProductScenario,
    Project,
    SemanticBinding,
    SemanticConcept,
    TargetField,
    TargetTable,
)
from app.schemas.regulatory_context import (
    CandidateContextValue,
    ContextAttribute,
    ContextEvidenceReference,
    ContextFact,
    ContextMode,
    ContextProvenance,
    ContextScenario,
    ContextTarget,
    EffectivePeriod,
    MetadataContextValue,
    RegulatoryContextRequest,
    SemanticContextValue,
)
from app.services.semantic.context_authority import FactState, authority_for_source
from app.services.semantic.status_policy import SemanticVisibilityMode, status_predicate
from app.services.semantic.version_service import resolve_effective_version


@dataclass
class CollectedContext:
    target: ContextTarget = field(default_factory=ContextTarget)
    scenario: ContextScenario | None = None
    semantic: list[ContextFact] = field(default_factory=list)
    regulatory: list[ContextFact] = field(default_factory=list)
    metadata: list[ContextFact] = field(default_factory=list)
    candidates: list[ContextFact] = field(default_factory=list)
    mappings: list[ContextFact] = field(default_factory=list)
    lineage: list[ContextFact] = field(default_factory=list)
    knowledge_evidence: list[ContextFact] = field(default_factory=list)
    historical: list[ContextFact] = field(default_factory=list)
    quality: list[ContextFact] = field(default_factory=list)
    collector_names: list[str] = field(default_factory=list)
    signals: dict[str, object] = field(default_factory=dict)

    def all_facts(self) -> list[ContextFact]:
        return [
            *self.semantic,
            *self.regulatory,
            *self.metadata,
            *self.candidates,
            *self.mappings,
            *self.lineage,
            *self.knowledge_evidence,
            *self.historical,
            *self.quality,
        ]


def collect_base_context(
    db: Session,
    authorized_project: Project,
    request: RegulatoryContextRequest,
) -> CollectedContext:
    """Collect target metadata and date-effective governed semantic facts."""

    project_id = int(authorized_project.id)
    target_table, target_field, mart_field = _target_scope(db, project_id, request)
    scenario = _scenario_scope(db, project_id, request.scenario_id)
    target = ContextTarget(
        target_table_id=target_table.id if target_table is not None else request.target_table_id,
        target_field_id=target_field.id if target_field is not None else request.target_field_id,
        mart_field_id=mart_field.id if mart_field is not None else request.mart_field_id,
        semantic_concept_id=request.semantic_concept_id,
        target_table_code=target_table.table_code if target_table is not None else None,
        target_table_name=target_table.table_name if target_table is not None else None,
        target_field_code=target_field.field_code if target_field is not None else None,
        target_field_name=target_field.field_name if target_field is not None else None,
    )
    context_scenario = None if scenario is None else ContextScenario(
        scenario_id=scenario.id,
        scenario_code=scenario.scenario_code,
        scenario_name=scenario.scenario_name,
        scenario_type=scenario.scenario_type,
    )
    bindings, concepts = _semantic_inputs(
        db,
        project_id,
        request,
        target,
    )
    binding_by_concept: dict[int, SemanticBinding] = {}
    for binding in bindings:
        binding_by_concept.setdefault(int(binding.semantic_concept_id), binding)

    semantic: list[ContextFact] = []
    candidates: list[ContextFact] = []
    for concept in concepts:
        binding = binding_by_concept.get(int(concept.id))
        version = resolve_effective_version(
            db,
            int(concept.id),
            request.as_of,
            project_id=project_id,
        )
        if version is not None:
            semantic.append(_semantic_fact(authorized_project, concept, version, binding))
        elif request.mode is ContextMode.CANDIDATE:
            candidates.append(_semantic_candidate_fact(authorized_project, concept, binding))

    metadata: list[ContextFact] = []
    if target_field is not None:
        metadata.append(_target_field_fact(authorized_project, target_field))

    semantic.sort(key=_fact_sort_key)
    candidates.sort(key=_fact_sort_key)
    metadata.sort(key=_fact_sort_key)
    return CollectedContext(
        target=target,
        scenario=context_scenario,
        semantic=semantic,
        metadata=metadata,
        candidates=candidates[: request.candidate_limit],
        collector_names=["metadata_semantic"],
        signals={
            "has_semantic_binding": bool(bindings),
            "has_semantic_version": bool(semantic),
        },
    )


def _target_scope(
    db: Session,
    project_id: int,
    request: RegulatoryContextRequest,
) -> tuple[TargetTable | None, TargetField | None, MartField | None]:
    target_field = None
    if request.target_field_id is not None:
        target_field = db.scalar(select(TargetField).where(
            TargetField.id == request.target_field_id,
            TargetField.project_id == project_id,
        ))
        if target_field is None:
            raise ValueError("target field does not belong to the authorized project")

    target_table_id = request.target_table_id
    if target_field is not None:
        if target_table_id is not None and target_field.target_table_id != target_table_id:
            raise ValueError("target field does not belong to the requested target table")
        target_table_id = int(target_field.target_table_id)
    target_table = None
    if target_table_id is not None:
        target_table = db.scalar(select(TargetTable).where(
            TargetTable.id == target_table_id,
            TargetTable.project_id == project_id,
        ))
        if target_table is None:
            raise ValueError("target table does not belong to the authorized project")

    mart_field = None
    if request.mart_field_id is not None:
        mart_field = db.scalar(select(MartField).where(
            MartField.id == request.mart_field_id,
            MartField.project_id == project_id,
        ))
        if mart_field is None:
            raise ValueError("mart field does not belong to the authorized project")
    return target_table, target_field, mart_field


def _scenario_scope(db: Session, project_id: int, scenario_id: int | None) -> ProductScenario | None:
    if scenario_id is None:
        return None
    scenario = db.scalar(select(ProductScenario).where(
        ProductScenario.id == scenario_id,
        ProductScenario.project_id == project_id,
        ProductScenario.enabled.is_(True),
    ))
    if scenario is None:
        raise ValueError("scenario does not belong to the authorized project")
    return scenario


def _semantic_inputs(
    db: Session,
    project_id: int,
    request: RegulatoryContextRequest,
    target: ContextTarget,
) -> tuple[list[SemanticBinding], list[SemanticConcept]]:
    mode = (
        SemanticVisibilityMode.TRUSTED
        if request.mode is ContextMode.TRUSTED
        else SemanticVisibilityMode.CANDIDATE
    )
    if request.semantic_concept_id is not None:
        concept = db.scalar(select(SemanticConcept).where(
            SemanticConcept.id == request.semantic_concept_id,
            SemanticConcept.project_id == project_id,
            status_predicate(SemanticConcept.status, mode),
        ))
        if concept is None:
            raise ValueError("semantic concept is not visible in the authorized project")
        bindings = list(db.scalars(select(SemanticBinding).where(
            SemanticBinding.project_id == project_id,
            SemanticBinding.semantic_concept_id == concept.id,
            status_predicate(SemanticBinding.status, mode),
        ).order_by(SemanticBinding.id)).all())
        return bindings, [concept]

    clauses = []
    if target.target_field_id is not None:
        clauses.append(and_(
            SemanticBinding.entity_type == "target_field",
            SemanticBinding.entity_id == target.target_field_id,
        ))
    if target.target_table_id is not None:
        clauses.append(and_(
            SemanticBinding.entity_type == "target_table",
            SemanticBinding.entity_id == target.target_table_id,
        ))
    if target.mart_field_id is not None:
        clauses.append(and_(
            SemanticBinding.entity_type == "mart_field",
            SemanticBinding.entity_id == target.mart_field_id,
        ))
    if request.scenario_id is not None:
        clauses.append(and_(
            SemanticBinding.entity_type == "scenario",
            SemanticBinding.entity_id == request.scenario_id,
        ))
    if not clauses:
        return [], []

    rows = db.execute(select(SemanticBinding, SemanticConcept).join(
        SemanticConcept,
        SemanticConcept.id == SemanticBinding.semantic_concept_id,
    ).where(
        SemanticBinding.project_id == project_id,
        SemanticConcept.project_id == project_id,
        status_predicate(SemanticBinding.status, mode),
        status_predicate(SemanticConcept.status, mode),
        or_(*clauses),
    ).order_by(
        SemanticBinding.semantic_concept_id,
        SemanticBinding.entity_type,
        SemanticBinding.entity_id,
        SemanticBinding.id,
    )).all()
    bindings: list[SemanticBinding] = []
    concepts_by_id: dict[int, SemanticConcept] = {}
    for binding, concept in rows:
        bindings.append(binding)
        concepts_by_id.setdefault(int(concept.id), concept)
    return bindings, list(concepts_by_id.values())


def _semantic_fact(
    project: Project,
    concept: SemanticConcept,
    version: object,
    binding: SemanticBinding | None,
) -> ContextFact:
    observed_at = _aware_datetime(version.updated_at or version.created_at)
    source_type = "semantic_concept_version"
    evidence = []
    if binding is not None:
        evidence.append(ContextEvidenceReference(
            evidence_type="semantic_binding",
            evidence_id=binding.id,
            citation=f"{binding.entity_type}:{binding.entity_id}",
        ))
    period = EffectivePeriod(
        effective_from=version.effective_from,
        effective_to=version.effective_to,
    )
    provenance = ContextProvenance(
        project_id=project.id,
        institution_id=project.institution_id,
        source_model="SemanticConceptVersion",
        source_type=source_type,
        source_id=version.id,
        evidence_references=evidence,
        version_no=version.version_no,
        effective_period=period,
        observed_at=observed_at,
    )
    return ContextFact(
        fact_type="semantic_concept_version",
        value=SemanticContextValue(
            semantic_concept_id=concept.id,
            semantic_concept_version_id=version.id,
            concept_type=concept.concept_type,
            concept_code=concept.concept_code,
            concept_name=version.concept_name,
            definition=version.definition,
            aliases=list(version.aliases_json or []),
            business_domain=version.business_domain,
        ),
        authority=authority_for_source(source_type),
        state=FactState.CONFIRMED,
        source_type=source_type,
        source_id=version.id,
        evidence_references=evidence,
        version_no=version.version_no,
        effective_period=period,
        observed_at=observed_at,
        confidence=_confidence(version.confidence_level),
        provenance=provenance,
    )


def _semantic_candidate_fact(
    project: Project,
    concept: SemanticConcept,
    binding: SemanticBinding | None,
) -> ContextFact:
    observed_at = _aware_datetime(concept.updated_at or concept.created_at)
    source_type = "resolver_candidate"
    evidence = [] if binding is None else [ContextEvidenceReference(
        evidence_type="semantic_binding",
        evidence_id=binding.id,
        citation=f"{binding.entity_type}:{binding.entity_id}",
    )]
    provenance = ContextProvenance(
        project_id=project.id,
        institution_id=project.institution_id,
        source_model="SemanticConcept",
        source_type=source_type,
        source_id=concept.id,
        evidence_references=evidence,
        observed_at=observed_at,
    )
    return ContextFact(
        fact_type="semantic_candidate",
        value=CandidateContextValue(
            candidate_type="semantic_concept",
            candidate_id=concept.id,
            code=concept.concept_code,
            name=concept.concept_name,
            match_reason="explicit_candidate_mode",
            score=_confidence(concept.confidence_level),
            rank_tier=1 if binding is not None and binding.status == "confirmed" else 2,
            evidence_excerpt=concept.definition,
        ),
        authority=authority_for_source(source_type),
        state=FactState.AI_SUGGESTED,
        source_type=source_type,
        source_id=concept.id,
        evidence_references=evidence,
        observed_at=observed_at,
        confidence=_confidence(concept.confidence_level),
        provenance=provenance,
    )


def _target_field_fact(project: Project, field: TargetField) -> ContextFact:
    observed_at = _aware_datetime(field.updated_at or field.created_at)
    source_type = "target_metadata"
    provenance = ContextProvenance(
        project_id=project.id,
        institution_id=project.institution_id,
        source_model="TargetField",
        source_type=source_type,
        source_id=field.id,
        observed_at=observed_at,
    )
    attributes = [
        ContextAttribute(name="target_table_id", value=field.target_table_id),
        ContextAttribute(name="required_flag", value=field.required_flag),
    ]
    if field.field_type:
        attributes.append(ContextAttribute(name="field_type", value=field.field_type))
    return ContextFact(
        fact_type="target_field_metadata",
        value=MetadataContextValue(
            entity_type="target_field",
            entity_id=field.id,
            code=field.field_code,
            name=field.field_name,
            description=field.regulatory_description or field.field_definition,
            attributes=attributes,
        ),
        authority=authority_for_source(source_type),
        state=FactState.OBSERVED,
        source_type=source_type,
        source_id=field.id,
        observed_at=observed_at,
        confidence=1.0,
        provenance=provenance,
    )


def _fact_sort_key(fact: ContextFact) -> tuple[str, str, int]:
    return fact.fact_type, fact.source_type, fact.source_id or 0


def _confidence(value: str | None) -> float:
    return {"low": 0.4, "medium": 0.7, "high": 1.0}.get(str(value or "").lower(), 0.5)


def _aware_datetime(value: object | None) -> datetime:
    if not isinstance(value, datetime):
        return datetime(1970, 1, 1, tzinfo=UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = ["CollectedContext", "collect_base_context"]
