"""Project-scoped collectors for the RegulatoryContext projection.

Collectors own SQL and return typed, bounded facts.  They accept the Project
already authorized by PermissionService; caller-supplied institution scope is
never accepted or inferred from free text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, aliased

from app.models import (
    HistoricalCaliberItem,
    KnowledgeUnit,
    LineageEdge,
    LineageNode,
    MappingEvidenceReference,
    MartField,
    MartToYbtMapping,
    ProductScenario,
    Project,
    RegulatoryKnowledgeItem,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    ScriptFile,
    ScriptFileVersion,
    SemanticBinding,
    SemanticConcept,
    SourceField,
    SourceToMartMapping,
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
    HistoricalContextValue,
    KnowledgeEvidenceContextValue,
    LineageContextValue,
    MappingContextValue,
    MetadataContextValue,
    RegulatoryContextRequest,
    RegulatoryContextValue,
    SemanticContextValue,
)
from app.services.retrieval.hybrid_retriever import HybridRetriever
from app.services.semantic.context_authority import FactState, authority_for_source
from app.services.semantic.status_policy import SemanticVisibilityMode, status_predicate
from app.services.semantic.version_service import resolve_effective_versions


CANDIDATE_TIER_CONFIRMED_BINDING_OR_MAPPING = 1
CANDIDATE_TIER_EXACT_CODE_OR_NAME = 2
CANDIDATE_TIER_SEMANTIC_EVIDENCE = 3
CANDIDATE_TIER_METADATA_KEYWORD = 4
CANDIDATE_TIER_HISTORICAL_MAPPING = 5
CANDIDATE_TIER_LINEAGE_NEIGHBORHOOD = 6
CANDIDATE_TIER_RETRIEVAL_EVIDENCE = 7

MAPPING_FAMILIES = (
    "source_to_mart",
    "mart_to_ybt",
    "scenario_business",
    "scenario_technical",
)
MAPPING_TRUSTED_STATUSES = {
    "source_to_mart": frozenset({"approved"}),
    "mart_to_ybt": frozenset({"approved"}),
    "scenario_business": frozenset({"confirmed"}),
    "scenario_technical": frozenset({"confirmed"}),
}
MAPPING_CANDIDATE_STATUSES = frozenset({"draft", "ai_suggested"})


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
        target_table_code=(
            _bounded(target_table.table_code, 500) if target_table is not None else None
        ),
        target_table_name=(
            _bounded(target_table.table_name, 500) if target_table is not None else None
        ),
        target_field_code=(
            _bounded(target_field.field_code, 500) if target_field is not None else None
        ),
        target_field_name=(
            _bounded(target_field.field_name, 500) if target_field is not None else None
        ),
    )
    context_scenario = None if scenario is None else ContextScenario(
        scenario_id=scenario.id,
        scenario_code=_bounded(scenario.scenario_code, 150),
        scenario_name=_bounded(scenario.scenario_name, 500),
        scenario_type=_bounded(scenario.scenario_type, 80),
    )
    bindings, concepts = _semantic_inputs(
        db,
        project_id,
        request,
        target,
    )
    confirmed_bindings = [binding for binding in bindings if binding.status == "confirmed"]
    candidate_bindings = [
        binding for binding in bindings if binding.status in {"draft", "ai_suggested"}
    ]
    confirmed_by_concept: dict[int, SemanticBinding] = {}
    candidate_by_concept: dict[int, list[SemanticBinding]] = {}
    for binding in sorted(
        confirmed_bindings,
        key=lambda item: _semantic_binding_sort_key(item, request, target),
    ):
        confirmed_by_concept.setdefault(int(binding.semantic_concept_id), binding)
    for binding in sorted(
        candidate_bindings,
        key=lambda item: _semantic_binding_sort_key(item, request, target),
    ):
        candidate_by_concept.setdefault(int(binding.semantic_concept_id), []).append(binding)

    semantic: list[ContextFact] = []
    candidates: list[ContextFact] = []
    versions_by_concept = resolve_effective_versions(
        db,
        [int(concept.id) for concept in concepts],
        request.as_of,
        project_id=project_id,
    )
    for concept in concepts:
        concept_id = int(concept.id)
        confirmed_binding = confirmed_by_concept.get(concept_id)
        version = versions_by_concept.get(int(concept.id))
        if version is not None:
            semantic.append(_semantic_fact(
                authorized_project,
                concept,
                version,
                confirmed_binding,
            ))
        if request.mode is ContextMode.CANDIDATE:
            concept_candidate_bindings = candidate_by_concept.get(concept_id, [])
            candidates.extend(
                _semantic_candidate_fact(authorized_project, concept, binding)
                for binding in concept_candidate_bindings
            )
            if version is None and not concept_candidate_bindings:
                candidates.append(_semantic_candidate_fact(
                    authorized_project,
                    concept,
                    confirmed_binding,
                ))

    metadata: list[ContextFact] = []
    if target_field is not None:
        metadata.append(_target_field_fact(authorized_project, target_field))

    mapping_rows = collect_mapping_rows(db, authorized_project, request, target)
    evidence_rows = collect_mapping_evidence_rows(db, authorized_project, mapping_rows)
    evidence_by_mapping = _evidence_by_mapping(evidence_rows)
    trusted_mapping_rows, candidate_mapping_rows = _partition_mapping_rows(mapping_rows)
    mappings = collect_mapping_facts(
        authorized_project,
        trusted_mapping_rows,
        evidence_by_mapping,
    )
    mapping_candidates = collect_mapping_candidate_facts(
        authorized_project,
        candidate_mapping_rows,
        evidence_by_mapping,
    )
    mapping_lineage = collect_mapping_lineage_facts(
        authorized_project,
        trusted_mapping_rows,
        evidence_by_mapping,
    )
    trusted_mapping_keys = {
        (mapping_type, int(row.id))
        for mapping_type, rows in zip(MAPPING_FAMILIES, trusted_mapping_rows, strict=True)
        for row in rows
    }
    evidence_facts = collect_mapping_evidence_facts(
        authorized_project,
        [
            row
            for row in evidence_rows
            if (row.mapping_type, int(row.mapping_id)) in trusted_mapping_keys
        ],
    )
    source_mappings, mart_mappings, business_mappings, technical_mappings = trusted_mapping_rows
    stale_lineage = sorted(
        (source_type, int(row.id))
        for source_type, rows in (
            ("source_to_mart_mapping", source_mappings),
            ("mart_to_ybt_mapping", mart_mappings),
            ("scenario_technical_lineage", technical_mappings),
        )
        for row in rows
        if row.lineage_status == "stale"
    )
    raw_lineage = collect_raw_lineage(
        db,
        authorized_project,
        target,
    )
    regulatory = collect_regulatory_knowledge(
        db,
        authorized_project,
        target,
        context_scenario,
    )
    retrieved = collect_retrieved_knowledge(
        db,
        authorized_project,
        request,
        target,
        context_scenario,
        target_field,
    )
    historical = collect_historical_context(
        db,
        authorized_project,
        target,
        context_scenario,
    )
    if request.mode is ContextMode.CANDIDATE:
        candidates.extend(mapping_candidates)
        candidates.extend(collect_source_mart_candidates(
            db,
            authorized_project,
            target,
            target_field,
            mappings,
            raw_lineage,
            retrieved,
        ))

    semantic.sort(key=_fact_sort_key)
    candidates = sorted(candidates, key=_candidate_sort_key)[: request.candidate_limit]
    metadata.sort(key=_fact_sort_key)
    mappings.sort(key=_fact_sort_key)
    lineage = sorted([*raw_lineage, *mapping_lineage], key=_fact_sort_key)
    knowledge_evidence = sorted([*evidence_facts, *retrieved], key=_fact_sort_key)
    regulatory.sort(key=_fact_sort_key)
    historical.sort(key=_fact_sort_key)
    return CollectedContext(
        target=target,
        scenario=context_scenario,
        semantic=semantic,
        regulatory=regulatory,
        metadata=metadata,
        candidates=candidates,
        mappings=mappings,
        lineage=lineage,
        knowledge_evidence=knowledge_evidence,
        historical=historical,
        collector_names=[
            "metadata_semantic",
            "mapping_families",
            "mapping_evidence",
            "raw_and_mapping_lineage",
            "regulatory_knowledge",
            "retrieved_knowledge",
            "historical_caliber",
        ],
        signals={
            "has_semantic_binding": bool(confirmed_bindings),
            "has_semantic_version": bool(semantic),
            "source_mapping_count": len(source_mappings),
            "mart_mapping_count": len(mart_mappings),
            "business_mapping_count": len(business_mappings),
            "technical_mapping_count": len(technical_mappings),
            "lineage_count": len(lineage),
            "verified_lineage_count": sum(
                fact.state is FactState.VERIFIED for fact in lineage
            ),
            "stale_lineage": stale_lineage,
            "regulatory_knowledge_count": len(regulatory),
            "retrieved_knowledge_count": sum(
                fact.fact_type == "retrieved_knowledge" for fact in retrieved
            ),
            "evidence_count": len(evidence_rows),
            "evidence_required": bool(mappings or regulatory),
            "supporting_evidence_count": (
                len(evidence_rows)
                + sum(bool(fact.evidence_references) for fact in regulatory)
                + sum(fact.fact_type == "retrieved_knowledge" for fact in retrieved)
            ),
            "historical_count": len(historical),
            "semantic_definitions": [
                (fact.source_type, fact.source_id, fact.value.definition)
                for fact in semantic
                if fact.value.definition
            ],
            "historical_definitions": [
                (fact.source_type, fact.source_id, fact.value.definition)
                for fact in historical
                if fact.value.definition
            ],
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


def _semantic_binding_sort_key(
    binding: SemanticBinding,
    request: RegulatoryContextRequest,
    target: ContextTarget,
) -> tuple[int, int]:
    """Prefer the explicitly requested target identity, then stable binding id."""

    requested_identities = [
        (entity_type, int(identifier))
        for entity_type, identifier in (
            ("target_field", request.target_field_id),
            ("mart_field", request.mart_field_id),
            ("target_table", request.target_table_id),
            ("scenario", request.scenario_id),
        )
        if identifier is not None
    ]
    scoped_identities = [
        (entity_type, int(identifier))
        for entity_type, identifier in (
            ("target_field", target.target_field_id),
            ("mart_field", target.mart_field_id),
            ("target_table", target.target_table_id),
            ("scenario", request.scenario_id),
        )
        if identifier is not None
    ]
    ordered_identities = [
        *requested_identities,
        *(identity for identity in scoped_identities if identity not in requested_identities),
    ]
    identity = (str(binding.entity_type), int(binding.entity_id))
    try:
        target_rank = ordered_identities.index(identity)
    except ValueError:
        target_rank = len(ordered_identities)
    return target_rank, int(binding.id)


def collect_mapping_rows(
    db: Session,
    authorized_project: Project,
    request: RegulatoryContextRequest,
    target: ContextTarget,
) -> tuple[
    list[SourceToMartMapping],
    list[MartToYbtMapping],
    list[ScenarioBusinessMapping],
    list[ScenarioTechnicalLineage],
]:
    """Load the four mapping families through project-bounded set queries."""

    project_id = int(authorized_project.id)
    source_statuses = set(MAPPING_TRUSTED_STATUSES["source_to_mart"])
    mart_statuses = set(MAPPING_TRUSTED_STATUSES["mart_to_ybt"])
    business_statuses = set(MAPPING_TRUSTED_STATUSES["scenario_business"])
    technical_statuses = set(MAPPING_TRUSTED_STATUSES["scenario_technical"])
    if request.mode is ContextMode.CANDIDATE:
        source_statuses.update(MAPPING_CANDIDATE_STATUSES)
        mart_statuses.update(MAPPING_CANDIDATE_STATUSES)
        business_statuses.update(MAPPING_CANDIDATE_STATUSES)
        technical_statuses.update(MAPPING_CANDIDATE_STATUSES)
    mart_mappings: list[MartToYbtMapping] = []
    business_mappings: list[ScenarioBusinessMapping] = []
    technical_mappings: list[ScenarioTechnicalLineage] = []
    if target.target_field_id is not None:
        mart_mappings = list(db.scalars(select(MartToYbtMapping).where(
            MartToYbtMapping.project_id == project_id,
            MartToYbtMapping.target_field_id == target.target_field_id,
            MartToYbtMapping.mapping_status.in_(sorted(mart_statuses)),
        ).order_by(MartToYbtMapping.id)).all())
        business_statement = select(ScenarioBusinessMapping).where(
            ScenarioBusinessMapping.project_id == project_id,
            ScenarioBusinessMapping.target_field_id == target.target_field_id,
            ScenarioBusinessMapping.business_confirm_status.in_(sorted(business_statuses)),
        )
        technical_statement = select(ScenarioTechnicalLineage).where(
            ScenarioTechnicalLineage.project_id == project_id,
            ScenarioTechnicalLineage.target_field_id == target.target_field_id,
            ScenarioTechnicalLineage.tech_confirm_status.in_(sorted(technical_statuses)),
        )
        if request.scenario_id is not None:
            business_statement = business_statement.where(
                ScenarioBusinessMapping.scenario_id == request.scenario_id
            )
            technical_statement = technical_statement.where(
                ScenarioTechnicalLineage.scenario_id == request.scenario_id
            )
        business_mappings = list(db.scalars(
            business_statement.order_by(ScenarioBusinessMapping.id)
        ).all())
        technical_mappings = list(db.scalars(
            technical_statement.order_by(ScenarioTechnicalLineage.id)
        ).all())

    mart_field_ids = {
        int(mapping.mart_field_id)
        for mapping in mart_mappings
        if mapping.mart_field_id is not None
    }
    if target.mart_field_id is not None:
        mart_field_ids.add(int(target.mart_field_id))
    source_mappings = [] if not mart_field_ids else list(db.scalars(
        select(SourceToMartMapping).where(
            SourceToMartMapping.project_id == project_id,
            SourceToMartMapping.mart_field_id.in_(sorted(mart_field_ids)),
            SourceToMartMapping.mapping_status.in_(sorted(source_statuses)),
        ).order_by(SourceToMartMapping.id)
    ).all())
    return source_mappings, mart_mappings, business_mappings, technical_mappings


def _partition_mapping_rows(
    mapping_rows: tuple[
        list[SourceToMartMapping],
        list[MartToYbtMapping],
        list[ScenarioBusinessMapping],
        list[ScenarioTechnicalLineage],
    ],
) -> tuple[tuple[list, list, list, list], tuple[list, list, list, list]]:
    trusted: list[list] = []
    candidates: list[list] = []
    for mapping_type, rows in zip(MAPPING_FAMILIES, mapping_rows, strict=True):
        trusted_statuses = MAPPING_TRUSTED_STATUSES[mapping_type]
        trusted.append([
            row for row in rows if _mapping_row_status(mapping_type, row) in trusted_statuses
        ])
        candidates.append([
            row
            for row in rows
            if _mapping_row_status(mapping_type, row) in MAPPING_CANDIDATE_STATUSES
        ])
    return tuple(trusted), tuple(candidates)


def collect_mapping_evidence_rows(
    db: Session,
    authorized_project: Project,
    mapping_rows: tuple[
        list[SourceToMartMapping],
        list[MartToYbtMapping],
        list[ScenarioBusinessMapping],
        list[ScenarioTechnicalLineage],
    ],
) -> list[MappingEvidenceReference]:
    """Batch evidence across mapping families without relying on colliding ids."""

    clauses = []
    for mapping_type, rows in zip(
        ("source_to_mart", "mart_to_ybt", "scenario_business", "scenario_technical"),
        mapping_rows,
        strict=True,
    ):
        identifiers = sorted({int(row.id) for row in rows})
        if identifiers:
            clauses.append(and_(
                MappingEvidenceReference.mapping_type == mapping_type,
                MappingEvidenceReference.mapping_id.in_(identifiers),
            ))
    if not clauses:
        return []
    return list(db.scalars(select(MappingEvidenceReference).where(
        MappingEvidenceReference.project_id == authorized_project.id,
        or_(*clauses),
    ).order_by(
        MappingEvidenceReference.mapping_type,
        MappingEvidenceReference.mapping_id,
        MappingEvidenceReference.id,
    )).all())


def collect_mapping_facts(
    project: Project,
    mapping_rows: tuple[
        list[SourceToMartMapping],
        list[MartToYbtMapping],
        list[ScenarioBusinessMapping],
        list[ScenarioTechnicalLineage],
    ],
    evidence_by_mapping: dict[tuple[str, int], list[MappingEvidenceReference]],
) -> list[ContextFact]:
    facts: list[ContextFact] = []
    source_rows, mart_rows, business_rows, technical_rows = mapping_rows
    for row in source_rows:
        facts.append(_mapping_fact(
            project,
            row,
            mapping_type="source_to_mart",
            source_type="source_to_mart_mapping",
            state=FactState.APPROVED if row.mapping_status == "approved" else FactState.DRAFT,
            status=row.mapping_status,
            source_entity_ids=[],
            target_entity_ids=[row.mart_field_id],
            rule_text=row.final_content or row.business_rule,
            evidence=evidence_by_mapping.get(("source_to_mart", row.id), []),
        ))
    for row in mart_rows:
        facts.append(_mapping_fact(
            project,
            row,
            mapping_type="mart_to_ybt",
            source_type="mart_to_ybt_mapping",
            state=FactState.APPROVED if row.mapping_status == "approved" else FactState.DRAFT,
            status=row.mapping_status,
            source_entity_ids=[row.mart_field_id] if row.mart_field_id is not None else [],
            target_entity_ids=[row.target_field_id],
            rule_text=row.final_content or row.business_rule,
            evidence=evidence_by_mapping.get(("mart_to_ybt", row.id), []),
        ))
    for row in business_rows:
        facts.append(_mapping_fact(
            project,
            row,
            mapping_type="scenario_business",
            source_type="scenario_business_mapping",
            state=(
                FactState.CONFIRMED
                if row.business_confirm_status == "confirmed"
                else FactState.DRAFT
            ),
            status=row.business_confirm_status,
            source_entity_ids=[row.scenario_id],
            target_entity_ids=[row.target_field_id],
            rule_text=row.final_content or row.business_definition,
            evidence=evidence_by_mapping.get(("scenario_business", row.id), []),
        ))
    for row in technical_rows:
        facts.append(_mapping_fact(
            project,
            row,
            mapping_type="scenario_technical",
            source_type="scenario_technical_lineage",
            state=(
                FactState.CONFIRMED
                if row.tech_confirm_status == "confirmed"
                else FactState.DRAFT
            ),
            status=row.tech_confirm_status,
            source_entity_ids=[row.scenario_id],
            target_entity_ids=[row.target_field_id],
            rule_text=row.final_content or row.processing_logic,
            evidence=evidence_by_mapping.get(("scenario_technical", row.id), []),
        ))
    return facts


def collect_mapping_candidate_facts(
    project: Project,
    mapping_rows: tuple[list, list, list, list],
    evidence_by_mapping: dict[tuple[str, int], list[MappingEvidenceReference]],
) -> list[ContextFact]:
    """Project draft/AI mapping rows only as explicit review candidates."""

    facts: list[ContextFact] = []
    for mapping_type, rows in zip(MAPPING_FAMILIES, mapping_rows, strict=True):
        for row in rows:
            status = _mapping_row_status(mapping_type, row)
            if status not in MAPPING_CANDIDATE_STATUSES:
                continue
            observed_at = _aware_datetime(row.updated_at or row.created_at)
            references = _mapping_evidence_refs(
                evidence_by_mapping.get((mapping_type, int(row.id)), [])
            )
            source_type = "resolver_candidate"
            provenance = ContextProvenance(
                project_id=project.id,
                institution_id=project.institution_id,
                source_model=type(row).__name__,
                source_type=source_type,
                source_id=row.id,
                evidence_references=references,
                observed_at=observed_at,
                confidentiality_level=_confidentiality(project),
            )
            rule_text = (
                getattr(row, "final_content", None)
                or getattr(row, "business_rule", None)
                or getattr(row, "business_definition", None)
                or getattr(row, "processing_logic", None)
            )
            score = 0.65 if status == "ai_suggested" else 0.55
            facts.append(ContextFact(
                fact_type="mapping_candidate",
                value=CandidateContextValue(
                    candidate_type=mapping_type,
                    candidate_id=row.id,
                    name=_bounded(
                        getattr(row, "mapping_name", None)
                        or f"{mapping_type} #{row.id}",
                        500,
                    ),
                    match_reason=f"{status} mapping requires explicit review",
                    score=score,
                    rank_tier=CANDIDATE_TIER_SEMANTIC_EVIDENCE,
                    evidence_excerpt=_bounded(rule_text, 1000),
                ),
                authority=authority_for_source(source_type),
                state=FactState(status),
                source_type=source_type,
                source_id=row.id,
                evidence_references=references,
                observed_at=observed_at,
                confidence=score,
                provenance=provenance,
            ))
    return facts


def collect_mapping_lineage_facts(
    project: Project,
    mapping_rows: tuple[
        list[SourceToMartMapping],
        list[MartToYbtMapping],
        list[ScenarioBusinessMapping],
        list[ScenarioTechnicalLineage],
    ],
    evidence_by_mapping: dict[tuple[str, int], list[MappingEvidenceReference]],
) -> list[ContextFact]:
    facts: list[ContextFact] = []
    source_rows, mart_rows, _, technical_rows = mapping_rows
    for row in source_rows:
        facts.append(_mapping_lineage_fact(
            project,
            row,
            source_type="verified_lineage",
            source_entity_type="source_to_mart_mapping",
            source_entity_id=row.id,
            target_entity_type="mart_field",
            target_entity_id=row.mart_field_id,
            transformation=row.final_content or row.business_rule,
            evidence=evidence_by_mapping.get(("source_to_mart", row.id), []),
        ))
    for row in mart_rows:
        facts.append(_mapping_lineage_fact(
            project,
            row,
            source_type="verified_lineage",
            source_entity_type="mart_field" if row.mart_field_id is not None else "mart_to_ybt_mapping",
            source_entity_id=row.mart_field_id or row.id,
            target_entity_type="target_field",
            target_entity_id=row.target_field_id,
            transformation=row.final_content or row.business_rule,
            evidence=evidence_by_mapping.get(("mart_to_ybt", row.id), []),
        ))
    for row in technical_rows:
        facts.append(_mapping_lineage_fact(
            project,
            row,
            source_type="scenario_technical_lineage",
            source_entity_type="scenario",
            source_entity_id=row.scenario_id,
            target_entity_type="target_field",
            target_entity_id=row.target_field_id,
            transformation=row.final_content or row.processing_logic,
            evidence=evidence_by_mapping.get(("scenario_technical", row.id), []),
        ))
    return facts


def collect_mapping_evidence_facts(
    project: Project,
    rows: list[MappingEvidenceReference],
) -> list[ContextFact]:
    facts: list[ContextFact] = []
    for row in rows:
        source_type = _source_type_for_mapping_type(row.mapping_type)
        observed_at = _aware_datetime(row.created_at)
        evidence = _mapping_evidence_refs([row])
        provenance = ContextProvenance(
            project_id=project.id,
            institution_id=project.institution_id,
            source_model="MappingEvidenceReference",
            source_type=source_type,
            source_id=row.id,
            evidence_references=evidence,
            observed_at=observed_at,
            confidentiality_level=project.confidentiality_level,
        )
        facts.append(ContextFact(
            fact_type="mapping_evidence",
            value=KnowledgeEvidenceContextValue(
                evidence_reference_id=row.id,
                knowledge_type=row.evidence_type,
                title=_bounded(row.source_name, 500),
                excerpt=_bounded(row.quoted_content or row.evidence_summary, 4000),
                source_file_name=_bounded(row.source_name, 500),
                source_location=_bounded(row.location_text, 1000),
                confidentiality_level=project.confidentiality_level,
            ),
            authority=authority_for_source(source_type),
            state=FactState.OBSERVED,
            source_type=source_type,
            source_id=row.id,
            evidence_references=evidence,
            observed_at=observed_at,
            confidence=1.0,
            provenance=provenance,
        ))
    return facts


def collect_raw_lineage(
    db: Session,
    authorized_project: Project,
    target: ContextTarget,
) -> list[ContextFact]:
    """Project raw lineage with only predicates present on its real models."""

    source_node = aliased(LineageNode)
    target_node = aliased(LineageNode)
    scope_clauses = []
    for column_name, identifier in (
        ("target_field_id", target.target_field_id),
        ("target_table_id", target.target_table_id),
        ("mart_field_id", target.mart_field_id),
    ):
        if identifier is not None:
            scope_clauses.extend([
                getattr(source_node, column_name) == identifier,
                getattr(target_node, column_name) == identifier,
            ])
    if not scope_clauses:
        return []
    rows = db.execute(select(
        LineageEdge,
        source_node,
        target_node,
        ScriptFileVersion,
        ScriptFile,
    ).join(
        source_node,
        source_node.id == LineageEdge.source_node_id,
    ).join(
        target_node,
        target_node.id == LineageEdge.target_node_id,
    ).join(
        ScriptFileVersion,
        ScriptFileVersion.id == LineageEdge.script_file_version_id,
    ).join(
        ScriptFile,
        ScriptFile.id == ScriptFileVersion.script_file_id,
    ).where(
        LineageEdge.project_id == authorized_project.id,
        source_node.project_id == authorized_project.id,
        target_node.project_id == authorized_project.id,
        ScriptFileVersion.project_id == authorized_project.id,
        ScriptFile.project_id == authorized_project.id,
        or_(*scope_clauses),
    ).order_by(LineageEdge.id)).all()

    facts: list[ContextFact] = []
    for edge, source, destination, version, script in rows:
        verified = (
            edge.enabled is True
            and source.unresolved_flag is False
            and destination.unresolved_flag is False
            and str(edge.confidence_level).lower() == "high"
            and script.enabled is True
            and int(version.version_no) == int(script.current_version_no)
        )
        observed_at = _aware_datetime(edge.updated_at or edge.created_at)
        source_type = "verified_lineage"
        evidence = [
            ContextEvidenceReference(
                evidence_type="script_file_version",
                evidence_id=version.id,
                citation=_bounded(script.relative_path, 1000),
                source_location=_bounded(script.relative_path, 1000),
            )
        ]
        provenance = ContextProvenance(
            project_id=authorized_project.id,
            institution_id=authorized_project.institution_id,
            source_model="LineageEdge",
            source_type=source_type,
            source_id=edge.id,
            evidence_references=evidence,
            version_no=version.version_no,
            observed_at=observed_at,
            confidentiality_level=_confidentiality(authorized_project),
        )
        facts.append(ContextFact(
            fact_type="raw_lineage_edge",
            value=LineageContextValue(
                lineage_edge_id=edge.id,
                source_entity_type=source.node_type,
                source_entity_id=_lineage_node_identity(source),
                target_entity_type=destination.node_type,
                target_entity_id=_lineage_node_identity(destination),
                transformation_rule=_bounded(_raw_lineage_rule(edge), 12000),
                lineage_status="verified" if verified else "observed",
                verified_at=None,
            ),
            authority=authority_for_source(source_type),
            state=FactState.VERIFIED if verified else FactState.OBSERVED,
            source_type=source_type,
            source_id=edge.id,
            evidence_references=evidence,
            version_no=version.version_no,
            observed_at=observed_at,
            confidence=_confidence(edge.confidence_level),
            provenance=provenance,
        ))
    return facts


def collect_regulatory_knowledge(
    db: Session,
    authorized_project: Project,
    target: ContextTarget,
    scenario: ContextScenario | None,
) -> list[ContextFact]:
    """Project only RegulatoryKnowledgeItem rows owned by the authorized project."""

    match_clauses = []
    if target.target_table_code:
        match_clauses.append(RegulatoryKnowledgeItem.target_table_code == target.target_table_code)
    if target.target_field_code:
        match_clauses.append(RegulatoryKnowledgeItem.target_field_code == target.target_field_code)
    if target.target_field_name:
        match_clauses.append(RegulatoryKnowledgeItem.target_field_name == target.target_field_name)
    if not match_clauses:
        return []
    statement = select(RegulatoryKnowledgeItem).where(
        RegulatoryKnowledgeItem.project_id == authorized_project.id,
        or_(*match_clauses),
    )
    if scenario is not None:
        statement = statement.where(or_(
            RegulatoryKnowledgeItem.scenario_id.is_(None),
            RegulatoryKnowledgeItem.scenario_id == scenario.scenario_id,
        ))
    rows = sorted(
        db.scalars(statement.order_by(RegulatoryKnowledgeItem.id)).all(),
        key=lambda row: _regulatory_relevance_sort_key(row, target, scenario),
    )[:200]
    facts: list[ContextFact] = []
    for row in rows:
        requirement_text = next((
            str(value).strip()
            for value in (
                row.regulatory_reply,
                row.answer_text,
                row.business_explanation,
                row.institution_suggestion,
                row.question_text,
            )
            if value and str(value).strip()
        ), None)
        if requirement_text is None:
            continue
        observed_at = _aware_datetime(row.updated_at or row.created_at)
        source_type = "regulatory_knowledge_item"
        location = _source_location(row.source_sheet_name, row.source_cell_range)
        evidence = []
        if row.source_document_name or location:
            evidence.append(ContextEvidenceReference(
                evidence_type="regulatory_knowledge_item",
                evidence_id=row.id,
                citation=_bounded(row.source_document_name, 1000),
                source_location=_bounded(location, 1000),
            ))
        provenance = ContextProvenance(
            project_id=authorized_project.id,
            institution_id=authorized_project.institution_id,
            source_model="RegulatoryKnowledgeItem",
            source_type=source_type,
            source_id=row.id,
            evidence_references=evidence,
            observed_at=observed_at,
            confidentiality_level=_confidentiality(authorized_project),
        )
        facts.append(ContextFact(
            fact_type="regulatory_knowledge",
            value=RegulatoryContextValue(
                regulatory_source_id=row.id,
                regulation_code=_bounded(row.target_table_code, 150),
                title=_bounded(
                    row.question_text or row.target_field_name or row.knowledge_type,
                    500,
                ),
                requirement_text=_bounded(requirement_text, 12000),
                article_reference=_bounded(
                    _source_location(row.source_sheet_name, row.source_cell_range),
                    500,
                ),
                target_field_id=target.target_field_id,
            ),
            authority=authority_for_source(source_type),
            state=FactState.UNVERIFIED,
            source_type=source_type,
            source_id=row.id,
            evidence_references=evidence,
            observed_at=observed_at,
            confidence=0.7,
            provenance=provenance,
        ))
    return facts


def collect_retrieved_knowledge(
    db: Session,
    authorized_project: Project,
    request: RegulatoryContextRequest,
    target: ContextTarget,
    scenario: ContextScenario | None,
    target_field: TargetField | None,
) -> list[ContextFact]:
    """Reuse HybridRetriever as the sole KnowledgeUnit visibility boundary."""

    query = " ".join(filter(None, [
        target.target_table_code,
        target.target_table_name,
        target.target_field_code,
        target.target_field_name,
        target_field.field_definition if target_field is not None else None,
        target_field.regulatory_description if target_field is not None else None,
        scenario.scenario_name if scenario is not None else None,
        request.reporting_period,
    ])).strip()
    if not query:
        return []
    retrieval_log, items = HybridRetriever(db).search(
        authorized_project.id,
        query,
        target_field_id=target.target_field_id,
        scenario_id=scenario.scenario_id if scenario is not None else None,
        top_k=min(max(request.candidate_limit, 20), 100),
        retrieval_mode="keyword_only",
    )
    item_ids = sorted({int(item["knowledge_unit_id"]) for item in items})
    units_by_id = {} if not item_ids else {
        int(unit.id): unit
        for unit in db.scalars(select(KnowledgeUnit).where(
            KnowledgeUnit.id.in_(item_ids)
        ).order_by(KnowledgeUnit.id)).all()
    }
    facts: list[ContextFact] = []
    for item in items:
        unit_id = int(item["knowledge_unit_id"])
        unit = units_by_id.get(unit_id)
        if unit is None:
            continue
        observed_at = _aware_datetime(unit.updated_at or unit.created_at)
        source_type = "retrieved_knowledge"
        location = _source_location(
            item.get("source_sheet_name"),
            item.get("source_cell_range"),
            item.get("source_page_no"),
        ) or f"knowledge-unit:{unit_id}"
        evidence = [ContextEvidenceReference(
            evidence_type="knowledge_unit",
            evidence_id=unit_id,
            citation=_bounded(item.get("citation_id"), 1000),
            source_location=_bounded(location, 1000),
        )]
        confidentiality = str(item.get("confidentiality_level") or "internal")
        provenance = ContextProvenance(
            project_id=authorized_project.id,
            institution_id=authorized_project.institution_id,
            source_model="KnowledgeUnit",
            source_type=source_type,
            source_id=unit_id,
            evidence_references=evidence,
            observed_at=observed_at,
            retrieval_log_id=retrieval_log.id,
            confidentiality_level=confidentiality,
        )
        facts.append(ContextFact(
            fact_type="retrieved_knowledge",
            value=KnowledgeEvidenceContextValue(
                knowledge_unit_id=unit_id,
                knowledge_type=item["knowledge_type"],
                title=_bounded(item.get("title"), 500),
                excerpt=_bounded(item.get("content"), 4000),
                source_file_name=_bounded(item.get("source_file_name"), 500),
                source_location=_bounded(location, 1000),
                document_id=item.get("document_id"),
                document_version_id=item.get("document_version_id"),
                confidentiality_level=confidentiality,
                retrieval_score=float(item.get("final_score") or 0.0),
            ),
            authority=authority_for_source(source_type),
            state=FactState.RETRIEVED,
            source_type=source_type,
            source_id=unit_id,
            evidence_references=evidence,
            observed_at=observed_at,
            confidence=float(item.get("final_score") or 0.0),
            provenance=provenance,
        ))
    if not facts:
        observed_at = _aware_datetime(retrieval_log.created_at)
        source_type = "knowledge_retrieval"
        location = f"retrieval-log:{retrieval_log.id}"
        evidence = [ContextEvidenceReference(
            evidence_type="retrieval_log",
            evidence_id=retrieval_log.id,
            source_location=location,
        )]
        confidentiality = _confidentiality(authorized_project)
        provenance = ContextProvenance(
            project_id=authorized_project.id,
            institution_id=authorized_project.institution_id,
            source_model="RetrievalLog",
            source_type=source_type,
            source_id=retrieval_log.id,
            evidence_references=evidence,
            observed_at=observed_at,
            retrieval_log_id=retrieval_log.id,
            confidentiality_level=confidentiality,
        )
        facts.append(ContextFact(
            fact_type="knowledge_retrieval_empty",
            value=KnowledgeEvidenceContextValue(
                evidence_reference_id=retrieval_log.id,
                knowledge_type="retrieval_attempt",
                title="No matching knowledge returned",
                source_location=location,
                confidentiality_level=confidentiality,
                retrieval_score=0.0,
            ),
            authority=authority_for_source(source_type),
            state=FactState.RETRIEVED,
            source_type=source_type,
            source_id=retrieval_log.id,
            evidence_references=evidence,
            observed_at=observed_at,
            confidence=0.0,
            provenance=provenance,
        ))
    return facts


def collect_historical_context(
    db: Session,
    authorized_project: Project,
    target: ContextTarget,
    scenario: ContextScenario | None,
) -> list[ContextFact]:
    match_clauses = []
    if target.target_field_id is not None:
        match_clauses.append(HistoricalCaliberItem.matched_target_field_id == target.target_field_id)
    if target.target_field_code:
        match_clauses.append(HistoricalCaliberItem.target_field_code == target.target_field_code)
    if target.target_field_name:
        match_clauses.append(HistoricalCaliberItem.target_field_name == target.target_field_name)
    if not match_clauses:
        return []
    statement = select(HistoricalCaliberItem).where(
        HistoricalCaliberItem.project_id == authorized_project.id,
        or_(*match_clauses),
    )
    if scenario is not None:
        statement = statement.where(or_(
            HistoricalCaliberItem.matched_scenario_id == scenario.scenario_id,
            HistoricalCaliberItem.scenario_name == scenario.scenario_name,
            and_(
                HistoricalCaliberItem.matched_scenario_id.is_(None),
                HistoricalCaliberItem.scenario_name.is_(None),
            ),
        ))
    rows = list(db.scalars(statement.order_by(HistoricalCaliberItem.id).limit(200)).all())
    facts: list[ContextFact] = []
    for row in rows:
        observed_at = _aware_datetime(row.created_at)
        source_type = "historical_caliber"
        location = _source_location(row.source_sheet_name, row.source_cell_range) or "historical-caliber"
        evidence = [ContextEvidenceReference(
            evidence_type="historical_caliber",
            evidence_id=row.id,
            source_location=_bounded(location, 1000),
        )]
        provenance = ContextProvenance(
            project_id=authorized_project.id,
            institution_id=authorized_project.institution_id,
            source_model="HistoricalCaliberItem",
            source_type=source_type,
            source_id=row.id,
            evidence_references=evidence,
            observed_at=observed_at,
            confidentiality_level=_confidentiality(authorized_project),
        )
        match_status = row.match_status if row.match_status in {"matched", "ambiguous", "unmatched"} else "unmatched"
        facts.append(ContextFact(
            fact_type="historical_caliber",
            value=HistoricalContextValue(
                historical_item_id=row.id,
                title=_bounded(row.target_field_name or row.scenario_name, 500),
                definition=_bounded(row.business_content or row.technical_content, 12000),
                source_location=_bounded(location, 1000),
                content_hash=_bounded(row.content_hash, 150),
                match_status=match_status,
            ),
            authority=authority_for_source(source_type),
            state=FactState.HISTORICAL,
            source_type=source_type,
            source_id=row.id,
            evidence_references=evidence,
            observed_at=observed_at,
            confidence=0.5,
            provenance=provenance,
        ))
    return facts


def collect_source_mart_candidates(
    db: Session,
    authorized_project: Project,
    target: ContextTarget,
    target_field: TargetField | None,
    mappings: list[ContextFact],
    raw_lineage: list[ContextFact],
    retrieved: list[ContextFact],
) -> list[ContextFact]:
    """Rank every matching Source/Mart candidate before applying output caps."""

    project_id = int(authorized_project.id)
    source_fields = list(db.scalars(select(SourceField).where(
        SourceField.project_id == project_id,
    ).order_by(SourceField.id)).all())
    mart_fields = list(db.scalars(select(MartField).where(
        MartField.project_id == project_id,
    ).order_by(MartField.id)).all())
    binding_keys = {
        (str(entity_type), int(entity_id))
        for entity_type, entity_id in db.execute(select(
            SemanticBinding.entity_type,
            SemanticBinding.entity_id,
        ).where(
            SemanticBinding.project_id == project_id,
            SemanticBinding.status == "confirmed",
            SemanticBinding.entity_type.in_(("source_field", "mart_field")),
        )).all()
    }
    mapped_mart_ids: set[int] = set()
    evidence_keys: set[tuple[str, int]] = set()
    for fact in mappings:
        if fact.state is FactState.APPROVED:
            if fact.value.mapping_type == "source_to_mart":
                mapped_mart_ids.update(int(value) for value in fact.value.target_entity_ids)
            elif fact.value.mapping_type == "mart_to_ybt":
                mapped_mart_ids.update(int(value) for value in fact.value.source_entity_ids)
        for reference in fact.evidence_references:
            if reference.evidence_id is not None and reference.evidence_type in {
                "source_field",
                "mart_field",
            }:
                evidence_keys.add((reference.evidence_type, int(reference.evidence_id)))

    lineage_keys: set[tuple[str, int]] = set()
    for fact in raw_lineage:
        for entity_type, entity_id in (
            (fact.value.source_entity_type, fact.value.source_entity_id),
            (fact.value.target_entity_type, fact.value.target_entity_id),
        ):
            if entity_type in {"source_field", "mart_field"}:
                lineage_keys.add((entity_type, int(entity_id)))

    historical_statement = select(HistoricalCaliberItem).where(
        HistoricalCaliberItem.project_id == project_id,
    )
    historical_scope = []
    if target.target_field_id is not None:
        historical_scope.append(
            HistoricalCaliberItem.matched_target_field_id == target.target_field_id
        )
    if target.target_field_code:
        historical_scope.append(
            HistoricalCaliberItem.target_field_code == target.target_field_code
        )
    if target.target_field_name:
        historical_scope.append(
            HistoricalCaliberItem.target_field_name == target.target_field_name
        )
    historical_rows = [] if not historical_scope else list(db.scalars(
        historical_statement.where(or_(*historical_scope)).order_by(HistoricalCaliberItem.id)
    ).all())
    historical_source_names = {
        _normalized_identifier(value)
        for row in historical_rows
        for value in (row.source_field_name, row.mart_field_name)
        if value and _normalized_identifier(value)
    }
    retrieval_text = _normalized_identifier(" ".join(
        " ".join(filter(None, [fact.value.title, fact.value.excerpt]))
        for fact in retrieved
    ))
    target_code = _normalized_identifier(target.target_field_code)
    target_name = _normalized_identifier(target.target_field_name)
    target_metadata = [
        value
        for value in (
            target.target_field_code,
            target.target_field_name,
            target_field.field_definition if target_field is not None else None,
            target_field.regulatory_description if target_field is not None else None,
            target_field.regulatory_original_definition if target_field is not None else None,
            target_field.regulatory_refined_definition if target_field is not None else None,
        )
        if value
    ]

    facts: list[ContextFact] = []
    for candidate_type, rows in (("source_field", source_fields), ("mart_field", mart_fields)):
        for row in rows:
            key = (candidate_type, int(row.id))
            code = row.field_code
            name = row.field_name
            normalized_code = _normalized_identifier(code)
            normalized_name = _normalized_identifier(name)
            tier: int | None = None
            reason: str | None = None
            if key in binding_keys or (
                candidate_type == "mart_field" and row.id in mapped_mart_ids
            ):
                tier = CANDIDATE_TIER_CONFIRMED_BINDING_OR_MAPPING
                reason = "confirmed_binding_or_mapping"
            elif (
                normalized_code and normalized_code == target_code
            ) or (
                normalized_name and normalized_name == target_name
            ):
                tier = CANDIDATE_TIER_EXACT_CODE_OR_NAME
                reason = "exact_code_or_name"
            elif key in evidence_keys:
                tier = CANDIDATE_TIER_SEMANTIC_EVIDENCE
                reason = "semantic_evidence"
            elif _metadata_keyword_match(
                [code, name, getattr(row, "field_comment", None), getattr(row, "description", None)],
                target_metadata,
            ):
                tier = CANDIDATE_TIER_METADATA_KEYWORD
                reason = "metadata_keyword"
            elif normalized_code in historical_source_names or normalized_name in historical_source_names:
                tier = CANDIDATE_TIER_HISTORICAL_MAPPING
                reason = "historical_mapping"
            elif key in lineage_keys:
                tier = CANDIDATE_TIER_LINEAGE_NEIGHBORHOOD
                reason = "lineage_neighborhood"
            elif retrieval_text and (
                (normalized_code and normalized_code in retrieval_text)
                or (normalized_name and normalized_name in retrieval_text)
            ):
                tier = CANDIDATE_TIER_RETRIEVAL_EVIDENCE
                reason = "retrieval_evidence"
            if tier is None or reason is None:
                continue
            facts.append(_source_mart_candidate_fact(
                authorized_project,
                row,
                candidate_type=candidate_type,
                tier=tier,
                reason=reason,
            ))
    return sorted(facts, key=_candidate_sort_key)


def _source_mart_candidate_fact(
    project: Project,
    row: SourceField | MartField,
    *,
    candidate_type: str,
    tier: int,
    reason: str,
) -> ContextFact:
    observed_at = _aware_datetime(row.updated_at or row.created_at)
    source_type = "resolver_candidate"
    score = {
        CANDIDATE_TIER_CONFIRMED_BINDING_OR_MAPPING: 1.0,
        CANDIDATE_TIER_EXACT_CODE_OR_NAME: 0.95,
        CANDIDATE_TIER_SEMANTIC_EVIDENCE: 0.85,
        CANDIDATE_TIER_METADATA_KEYWORD: 0.75,
        CANDIDATE_TIER_HISTORICAL_MAPPING: 0.65,
        CANDIDATE_TIER_LINEAGE_NEIGHBORHOOD: 0.55,
        CANDIDATE_TIER_RETRIEVAL_EVIDENCE: 0.45,
    }[tier]
    description = getattr(row, "field_comment", None) or getattr(row, "description", None)
    provenance = ContextProvenance(
        project_id=project.id,
        institution_id=project.institution_id,
        source_model=type(row).__name__,
        source_type=source_type,
        source_id=row.id,
        observed_at=observed_at,
        confidentiality_level=_confidentiality(project),
    )
    return ContextFact(
        fact_type="source_mart_candidate",
        value=CandidateContextValue(
            candidate_type=candidate_type,
            candidate_id=row.id,
            code=_bounded(row.field_code, 500),
            name=_bounded(row.field_name, 500),
            match_reason=reason,
            score=score,
            rank_tier=tier,
            evidence_excerpt=_bounded(description, 1000),
        ),
        authority=authority_for_source(source_type),
        state=FactState.AI_SUGGESTED,
        source_type=source_type,
        source_id=row.id,
        observed_at=observed_at,
        confidence=score,
        provenance=provenance,
    )


def _mapping_fact(
    project: Project,
    row: object,
    *,
    mapping_type: str,
    source_type: str,
    state: FactState,
    status: str,
    source_entity_ids: list[int],
    target_entity_ids: list[int],
    rule_text: str | None,
    evidence: list[MappingEvidenceReference],
) -> ContextFact:
    observed_at = _aware_datetime(getattr(row, "updated_at", None) or getattr(row, "created_at", None))
    references = _mapping_evidence_refs(evidence)
    provenance = ContextProvenance(
        project_id=project.id,
        institution_id=project.institution_id,
        source_model=type(row).__name__,
        source_type=source_type,
        source_id=row.id,
        evidence_references=references,
        observed_at=observed_at,
        confidentiality_level=_confidentiality(project),
    )
    return ContextFact(
        fact_type=f"{mapping_type}_mapping",
        value=MappingContextValue(
            mapping_type=mapping_type,
            mapping_id=row.id,
            mapping_name=_bounded(getattr(row, "mapping_name", None), 500),
            source_entity_ids=[int(value) for value in source_entity_ids if value is not None],
            target_entity_ids=[int(value) for value in target_entity_ids if value is not None],
            rule_text=_bounded(rule_text, 12000),
            mapping_status=status,
            lineage_status=getattr(row, "lineage_status", None),
        ),
        authority=authority_for_source(source_type),
        state=state,
        source_type=source_type,
        source_id=row.id,
        evidence_references=references,
        observed_at=observed_at,
        confidence=_confidence(getattr(row, "confidence_level", None)),
        provenance=provenance,
    )


def _mapping_lineage_fact(
    project: Project,
    row: object,
    *,
    source_type: str,
    source_entity_type: str,
    source_entity_id: int,
    target_entity_type: str,
    target_entity_id: int,
    transformation: str | None,
    evidence: list[MappingEvidenceReference],
) -> ContextFact:
    lineage_status = str(getattr(row, "lineage_status", "not_linked") or "not_linked")
    raw_verified_at = getattr(row, "lineage_last_verified_at", None)
    verified = lineage_status == "verified" and raw_verified_at is not None
    verified_at = _aware_datetime(raw_verified_at) if raw_verified_at is not None else None
    observed_at = _aware_datetime(getattr(row, "updated_at", None) or getattr(row, "created_at", None))
    references = _mapping_evidence_refs(evidence)
    provenance = ContextProvenance(
        project_id=project.id,
        institution_id=project.institution_id,
        source_model=type(row).__name__,
        source_type=source_type,
        source_id=row.id,
        evidence_references=references,
        observed_at=observed_at,
        confidentiality_level=_confidentiality(project),
    )
    return ContextFact(
        fact_type="mapping_lineage",
        value=LineageContextValue(
            source_entity_type=source_entity_type,
            source_entity_id=int(source_entity_id),
            target_entity_type=target_entity_type,
            target_entity_id=int(target_entity_id),
            transformation_rule=_bounded(transformation, 12000),
            lineage_status=lineage_status,
            verified_at=verified_at,
        ),
        authority=authority_for_source(source_type),
        state=FactState.VERIFIED if verified else FactState.OBSERVED,
        source_type=source_type,
        source_id=row.id,
        evidence_references=references,
        observed_at=observed_at,
        confidence=_confidence(getattr(row, "confidence_level", None)),
        provenance=provenance,
    )


def _evidence_by_mapping(
    rows: list[MappingEvidenceReference],
) -> dict[tuple[str, int], list[MappingEvidenceReference]]:
    result: dict[tuple[str, int], list[MappingEvidenceReference]] = {}
    for row in rows:
        result.setdefault((row.mapping_type, int(row.mapping_id)), []).append(row)
    return result


def _mapping_evidence_refs(
    rows: list[MappingEvidenceReference],
) -> list[ContextEvidenceReference]:
    return [ContextEvidenceReference(
        evidence_type=row.evidence_type,
        evidence_id=(int(row.evidence_id) if row.evidence_id and row.evidence_id > 0 else None),
        citation=_bounded(row.source_name, 1000),
        source_location=_bounded(row.location_text, 1000),
    ) for row in rows]


def _source_type_for_mapping_type(mapping_type: str) -> str:
    try:
        return {
            "source_to_mart": "source_to_mart_mapping",
            "mart_to_ybt": "mart_to_ybt_mapping",
            "scenario_business": "scenario_business_mapping",
            "scenario_technical": "scenario_technical_lineage",
        }[mapping_type]
    except KeyError as exc:
        raise ValueError(f"unsupported mapping evidence type: {mapping_type}") from exc


def _mapping_row_status(mapping_type: str, row: object) -> str:
    field_name = {
        "source_to_mart": "mapping_status",
        "mart_to_ybt": "mapping_status",
        "scenario_business": "business_confirm_status",
        "scenario_technical": "tech_confirm_status",
    }[mapping_type]
    return str(getattr(row, field_name))


def _lineage_node_identity(node: LineageNode) -> int:
    for attribute in (
        "catalog_column_id",
        "source_field_id",
        "mart_field_id",
        "target_field_id",
        "catalog_table_id",
        "source_table_id",
        "mart_table_id",
        "target_table_id",
        "script_file_id",
    ):
        value = getattr(node, attribute, None)
        if value is not None:
            return int(value)
    return int(node.id)


def _raw_lineage_rule(edge: LineageEdge) -> str | None:
    parts = [
        value
        for value in (
            edge.transformation_expression,
            edge.join_condition,
            edge.filter_condition,
            edge.aggregation_rule,
            edge.code_mapping_rule,
        )
        if value and str(value).strip()
    ]
    return "\n".join(str(value).strip() for value in parts) or None


def _source_location(
    sheet_name: object | None,
    cell_range: object | None,
    page_no: object | None = None,
) -> str | None:
    parts = []
    if sheet_name:
        parts.append(str(sheet_name).strip())
    if cell_range:
        parts.append(str(cell_range).strip())
    if page_no is not None:
        parts.append(f"page:{page_no}")
    return ":".join(part for part in parts if part) or None


def _regulatory_relevance_sort_key(
    row: RegulatoryKnowledgeItem,
    target: ContextTarget,
    scenario: ContextScenario | None,
) -> tuple[int, int, int]:
    """Rank all matching regulatory rows before the bounded projection cap."""

    row_field_code = _normalized_identifier(row.target_field_code)
    row_field_name = _normalized_identifier(row.target_field_name)
    row_table_code = _normalized_identifier(row.target_table_code)
    if row_field_code and row_field_code == _normalized_identifier(target.target_field_code):
        tier = 1
    elif row_field_name and row_field_name == _normalized_identifier(target.target_field_name):
        tier = 2
    elif row_table_code and row_table_code == _normalized_identifier(target.target_table_code):
        tier = 3
    else:
        tier = 4
    scenario_rank = (
        0
        if scenario is not None and row.scenario_id == scenario.scenario_id
        else 1
    )
    return tier, scenario_rank, int(row.id)


def _bounded(value: object | None, limit: int) -> str | None:
    return _compact_text(value, limit)


def _compact_text(value: object | None, limit: int) -> str | None:
    """Trim edges and deterministically signal Contract truncation."""

    if limit < 1:
        raise ValueError("text limit must be positive")
    if value is None:
        return None
    trimmed = str(value).strip()
    if not trimmed:
        return None
    if len(trimmed) <= limit:
        return trimmed
    return f"{trimmed[: limit - 1]}…"


def _compact_aliases(
    values: object | None,
    *,
    item_limit: int = 500,
    max_items: int = 100,
) -> list[str]:
    """Bound alias items before Pydantic while preserving stable first occurrence."""

    result: list[str] = []
    seen: set[str] = set()
    for raw in list(values or []):
        alias = _compact_text(raw, item_limit)
        if alias is None:
            continue
        key = alias.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(alias)
        if len(result) == max_items:
            break
    return result


def _confidentiality(project: Project) -> str:
    return str(project.confidentiality_level or "internal")


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
            definition=_bounded(version.definition, 12000),
            aliases=_compact_aliases(version.aliases_json),
            business_domain=_bounded(version.business_domain, 500),
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
            code=_bounded(concept.concept_code, 500),
            name=_bounded(concept.concept_name, 500),
            match_reason="explicit_candidate_mode",
            score=_confidence(concept.confidence_level),
            rank_tier=(
                CANDIDATE_TIER_CONFIRMED_BINDING_OR_MAPPING
                if binding is not None and binding.status == "confirmed"
                else CANDIDATE_TIER_SEMANTIC_EVIDENCE
            ),
            evidence_excerpt=_bounded(concept.definition, 1000),
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
        attributes.append(ContextAttribute(
            name="field_type",
            value=_bounded(field.field_type, 2000),
        ))
    return ContextFact(
        fact_type="target_field_metadata",
        value=MetadataContextValue(
            entity_type="target_field",
            entity_id=field.id,
            code=_bounded(field.field_code, 500),
            name=_bounded(field.field_name, 500),
            description=_bounded(
                field.regulatory_description or field.field_definition,
                4000,
            ),
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


def _candidate_sort_key(fact: ContextFact) -> tuple[int, str, int]:
    value = fact.value
    if not isinstance(value, CandidateContextValue):
        return 100, fact.fact_type, fact.source_id or 0
    return value.rank_tier, value.candidate_type, value.candidate_id


def _metadata_keyword_match(
    candidate_values: list[object | None],
    target_values: list[object | None],
) -> bool:
    candidate_texts = [
        _normalized_identifier(value)
        for value in candidate_values
        if value and _normalized_identifier(value)
    ]
    target_texts = [
        _normalized_identifier(value)
        for value in target_values
        if value and _normalized_identifier(value)
    ]
    for candidate_text in candidate_texts:
        candidate_grams = {
            candidate_text[index:index + 4]
            for index in range(max(len(candidate_text) - 3, 0))
        }
        for target_text in target_texts:
            if candidate_grams & {
                target_text[index:index + 4]
                for index in range(max(len(target_text) - 3, 0))
            }:
                return True
    return False


def _normalized_identifier(value: object | None) -> str:
    return "".join(
        character
        for character in str(value or "").casefold()
        if character.isalnum()
    )


def _confidence(value: str | None) -> float:
    return {"low": 0.4, "medium": 0.7, "high": 1.0}.get(str(value or "").lower(), 0.5)


def _aware_datetime(value: object | None) -> datetime:
    if not isinstance(value, datetime):
        return datetime(1970, 1, 1, tzinfo=UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "CANDIDATE_TIER_CONFIRMED_BINDING_OR_MAPPING",
    "CANDIDATE_TIER_EXACT_CODE_OR_NAME",
    "CANDIDATE_TIER_HISTORICAL_MAPPING",
    "CANDIDATE_TIER_LINEAGE_NEIGHBORHOOD",
    "CANDIDATE_TIER_METADATA_KEYWORD",
    "CANDIDATE_TIER_RETRIEVAL_EVIDENCE",
    "CANDIDATE_TIER_SEMANTIC_EVIDENCE",
    "CollectedContext",
    "collect_base_context",
]
