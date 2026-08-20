from datetime import UTC, datetime
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    KnowledgeUnit,
    MartField,
    MartTable,
    MartToYbtMapping,
    ProductScenario,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    SemanticBinding,
    SemanticConcept,
    SemanticRelation,
    SourceField,
    SourceTable,
    SourceToMartMapping,
    TargetField,
    TargetTable,
)


ENTITY_MODELS = {
    "target_table": TargetTable,
    "target_field": TargetField,
    "mart_table": MartTable,
    "mart_field": MartField,
    "source_table": SourceTable,
    "source_field": SourceField,
    "scenario": ProductScenario,
    "knowledge_unit": KnowledgeUnit,
    "source_to_mart_mapping": SourceToMartMapping,
    "mart_to_ybt_mapping": MartToYbtMapping,
    "scenario_business_mapping": ScenarioBusinessMapping,
    "scenario_technical_lineage": ScenarioTechnicalLineage,
}

SEMANTIC_MODELS = {
    "semantic_concept": SemanticConcept,
    "semantic_binding": SemanticBinding,
    "semantic_relation": SemanticRelation,
}

ALLOWED_TRANSITIONS = {
    "draft": {"ai_suggested", "confirmed", "rejected", "deprecated"},
    "ai_suggested": {"confirmed", "rejected", "deprecated"},
    "confirmed": {"deprecated"},
    "rejected": {"draft", "deprecated"},
    "deprecated": set(),
}

def get_project_entity(db: Session, project_id: int, entity_type: str, entity_id: int):
    model = ENTITY_MODELS.get(entity_type)
    if model is None:
        raise HTTPException(status_code=400, detail="Unsupported semantic binding entity_type")
    entity = db.get(model, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Semantic binding target not found")
    if int(getattr(entity, "project_id")) != project_id:
        raise HTTPException(status_code=400, detail="Semantic binding target belongs to another project")
    return entity


def get_project_semantic_resource(
    db: Session,
    project_id: int,
    resource_type: str,
    resource_id: int,
):
    model = SEMANTIC_MODELS[resource_type]
    resource = db.get(model, resource_id)
    if resource is None or resource.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found")
    return resource


def ensure_project_concept(db: Session, project_id: int, concept_id: int) -> SemanticConcept:
    return get_project_semantic_resource(db, project_id, "semantic_concept", concept_id)


def apply_status_transition(resource, new_status: str, actor: str) -> tuple[str, str]:
    old_status = resource.status
    if new_status == old_status:
        raise HTTPException(status_code=409, detail="Semantic resource already has requested status")
    if new_status not in ALLOWED_TRANSITIONS.get(old_status, set()):
        raise HTTPException(status_code=409, detail=f"Invalid semantic status transition: {old_status} -> {new_status}")
    resource.status = new_status
    if new_status == "confirmed":
        resource.confirmed_by = actor
        resource.confirmed_at = datetime.now(UTC)
    elif old_status == "confirmed":
        resource.confirmed_by = None
        resource.confirmed_at = None
    return old_status, new_status
