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

    mapping_rows = collect_mapping_rows(db, authorized_project, request, target)
    evidence_rows = collect_mapping_evidence_rows(db, authorized_project, mapping_rows)
    evidence_by_mapping = _evidence_by_mapping(evidence_rows)
    mappings = collect_mapping_facts(
        authorized_project,
        mapping_rows,
        evidence_by_mapping,
    )
    mapping_lineage = collect_mapping_lineage_facts(
        authorized_project,
        mapping_rows,
        evidence_by_mapping,
    )
    evidence_facts = collect_mapping_evidence_facts(
        authorized_project,
        evidence_rows,
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

    semantic.sort(key=_fact_sort_key)
    candidates.sort(key=_fact_sort_key)
    metadata.sort(key=_fact_sort_key)
    mappings.sort(key=_fact_sort_key)
    lineage = sorted([*raw_lineage, *mapping_lineage], key=_fact_sort_key)
    knowledge_evidence = sorted([*evidence_facts, *retrieved], key=_fact_sort_key)
    regulatory.sort(key=_fact_sort_key)
    historical.sort(key=_fact_sort_key)
    source_mappings, mart_mappings, business_mappings, technical_mappings = mapping_rows
    stale_lineage = sorted(
        (source_type, row.id)
        for source_type, rows in (
            ("source_to_mart_mapping", source_mappings),
            ("mart_to_ybt_mapping", mart_mappings),
            ("scenario_technical_lineage", technical_mappings),
        )
        for row in rows
        if row.lineage_status == "stale"
    )
    return CollectedContext(
        target=target,
        scenario=context_scenario,
        semantic=semantic,
        regulatory=regulatory,
        metadata=metadata,
        candidates=candidates[: request.candidate_limit],
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
            "has_semantic_binding": bool(bindings),
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
            "retrieved_knowledge_count": len(retrieved),
            "evidence_count": len(evidence_rows),
            "evidence_required": bool(mappings or regulatory),
            "supporting_evidence_count": (
                len(evidence_rows)
                + sum(bool(fact.evidence_references) for fact in regulatory)
                + len(retrieved)
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
    mart_mappings: list[MartToYbtMapping] = []
    business_mappings: list[ScenarioBusinessMapping] = []
    technical_mappings: list[ScenarioTechnicalLineage] = []
    if target.target_field_id is not None:
        mart_mappings = list(db.scalars(select(MartToYbtMapping).where(
            MartToYbtMapping.project_id == project_id,
            MartToYbtMapping.target_field_id == target.target_field_id,
        ).order_by(MartToYbtMapping.id)).all())
        business_statement = select(ScenarioBusinessMapping).where(
            ScenarioBusinessMapping.project_id == project_id,
            ScenarioBusinessMapping.target_field_id == target.target_field_id,
        )
        technical_statement = select(ScenarioTechnicalLineage).where(
            ScenarioTechnicalLineage.project_id == project_id,
            ScenarioTechnicalLineage.target_field_id == target.target_field_id,
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
        ).order_by(SourceToMartMapping.id)
    ).all())
    return source_mappings, mart_mappings, business_mappings, technical_mappings


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
    rows = list(db.scalars(statement.order_by(RegulatoryKnowledgeItem.id).limit(200)).all())
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


def _bounded(value: object | None, limit: int) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized[:limit] if normalized else None


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
