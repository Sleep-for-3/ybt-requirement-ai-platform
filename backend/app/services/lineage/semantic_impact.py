from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import (
    RegulatoryKnowledgeItem,
    SemanticBinding,
    SemanticConcept,
    SemanticConceptVersion,
    SemanticRelation,
    TargetField,
    TargetTable,
)


@dataclass(frozen=True)
class SemanticImpactScope:
    binding_ids: list[int]
    concept_ids: list[int]
    effective_version_ids: list[int]
    regulatory_rule_ids: list[int]
    regulatory_knowledge_item_ids: list[int]
    requirement_ids: list[int]


def resolve_semantic_impact(
    db: Session,
    *,
    project_id: int,
    source_field_ids: list[int],
    mart_field_ids: list[int],
    target_field_ids: list[int],
    mapping_entity_ids: dict[str, list[int]],
    as_of: date | None = None,
) -> SemanticImpactScope:
    """Project an existing lineage impact through governed semantic resources."""

    entity_filters = []
    for entity_type, entity_ids in {
        "source_field": source_field_ids,
        "mart_field": mart_field_ids,
        "target_field": target_field_ids,
        **mapping_entity_ids,
    }.items():
        if entity_ids:
            entity_filters.append(
                and_(SemanticBinding.entity_type == entity_type, SemanticBinding.entity_id.in_(entity_ids))
            )

    bindings = []
    if entity_filters:
        bindings = list(
            db.scalars(
                select(SemanticBinding).where(
                    SemanticBinding.project_id == project_id,
                    SemanticBinding.status.in_(("confirmed", "draft", "ai_suggested")),
                    or_(*entity_filters),
                )
            ).all()
        )

    direct_concept_ids = sorted({row.semantic_concept_id for row in bindings})
    related_regulatory_ids: set[int] = set()
    if direct_concept_ids:
        relations = list(
            db.scalars(
                select(SemanticRelation).where(
                    SemanticRelation.project_id == project_id,
                    SemanticRelation.status == "confirmed",
                    or_(
                        SemanticRelation.source_concept_id.in_(direct_concept_ids),
                        SemanticRelation.target_concept_id.in_(direct_concept_ids),
                    ),
                )
            ).all()
        )
        related_ids = {
            concept_id
            for relation in relations
            for concept_id in (relation.source_concept_id, relation.target_concept_id)
            if concept_id not in direct_concept_ids
        }
        if related_ids:
            related_regulatory_ids = set(
                db.scalars(
                    select(SemanticConcept.id).where(
                        SemanticConcept.project_id == project_id,
                        SemanticConcept.id.in_(related_ids),
                        SemanticConcept.concept_type == "regulatory_rule",
                        SemanticConcept.status.not_in(("rejected", "deprecated")),
                    )
                ).all()
            )

    concept_ids = sorted(set(direct_concept_ids) | related_regulatory_ids)
    concepts = []
    if concept_ids:
        concepts = list(
            db.scalars(
                select(SemanticConcept).where(
                    SemanticConcept.project_id == project_id,
                    SemanticConcept.id.in_(concept_ids),
                    SemanticConcept.status.not_in(("rejected", "deprecated")),
                )
            ).all()
        )
    concept_ids = sorted(row.id for row in concepts)
    regulatory_rule_ids = sorted(row.id for row in concepts if row.concept_type == "regulatory_rule")

    effective_date = as_of or datetime.now(UTC).date()
    version_ids: list[int] = []
    if concept_ids:
        version_ids = sorted(
            db.scalars(
                select(SemanticConceptVersion.id).where(
                    SemanticConceptVersion.project_id == project_id,
                    SemanticConceptVersion.semantic_concept_id.in_(concept_ids),
                    SemanticConceptVersion.status == "confirmed",
                    SemanticConceptVersion.effective_from <= effective_date,
                    or_(
                        SemanticConceptVersion.effective_to.is_(None),
                        SemanticConceptVersion.effective_to >= effective_date,
                    ),
                )
            ).all()
        )

    regulatory_knowledge_ids = {
        int(row.source_id)
        for row in concepts
        if row.concept_type == "regulatory_rule"
        and row.source_type == "regulatory_knowledge_item"
        and row.source_id is not None
    }
    if target_field_ids:
        target_rows = list(
            db.execute(
                select(TargetField, TargetTable)
                .join(TargetTable, TargetTable.id == TargetField.target_table_id)
                .where(
                    TargetField.project_id == project_id,
                    TargetTable.project_id == project_id,
                    TargetField.id.in_(target_field_ids),
                )
            ).all()
        )
        knowledge_filters = [
            and_(
                RegulatoryKnowledgeItem.target_field_code == field.field_code,
                or_(
                    RegulatoryKnowledgeItem.target_table_code.is_(None),
                    RegulatoryKnowledgeItem.target_table_code == table.table_code,
                ),
            )
            for field, table in target_rows
        ]
        if knowledge_filters:
            regulatory_knowledge_ids.update(
                db.scalars(
                    select(RegulatoryKnowledgeItem.id).where(
                        RegulatoryKnowledgeItem.project_id == project_id,
                        or_(*knowledge_filters),
                    )
                ).all()
            )
    if regulatory_knowledge_ids:
        regulatory_knowledge_ids = set(
            db.scalars(
                select(RegulatoryKnowledgeItem.id).where(
                    RegulatoryKnowledgeItem.project_id == project_id,
                    RegulatoryKnowledgeItem.id.in_(regulatory_knowledge_ids),
                )
            ).all()
        )

    return SemanticImpactScope(
        binding_ids=sorted(row.id for row in bindings),
        concept_ids=concept_ids,
        effective_version_ids=version_ids,
        regulatory_rule_ids=regulatory_rule_ids,
        regulatory_knowledge_item_ids=sorted(regulatory_knowledge_ids),
        requirement_ids=sorted(set(target_field_ids)),
    )
