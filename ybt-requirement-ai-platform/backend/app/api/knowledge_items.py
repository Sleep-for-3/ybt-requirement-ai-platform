from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import ProductScenario, Project, RegulatoryKnowledgeItem
from app.schemas import (
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    RegulatoryKnowledgeItemCreate,
    RegulatoryKnowledgeItemRead,
    ScoredKnowledgeItem,
)

router = APIRouter(tags=["regulatory knowledge"])

KNOWLEDGE_TYPES = {"regulatory_qa", "historical_mapping", "east_mapping", "business_research", "field_explanation", "manual_note"}


@router.post("/projects/{project_id}/knowledge/items", response_model=RegulatoryKnowledgeItemRead)
def create_knowledge_item(project_id: int, payload: RegulatoryKnowledgeItemCreate, db: Session = Depends(get_db)) -> RegulatoryKnowledgeItem:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    _validate_payload(db, project_id, payload)
    item = RegulatoryKnowledgeItem(project_id=project_id, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/projects/{project_id}/knowledge/items", response_model=list[RegulatoryKnowledgeItemRead])
def list_knowledge_items(
    project_id: int,
    target_field_code: str | None = None,
    scenario_id: int | None = None,
    knowledge_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[RegulatoryKnowledgeItem]:
    statement = select(RegulatoryKnowledgeItem).where(RegulatoryKnowledgeItem.project_id == project_id)
    if target_field_code:
        statement = statement.where(RegulatoryKnowledgeItem.target_field_code == target_field_code)
    if scenario_id is not None:
        statement = statement.where(RegulatoryKnowledgeItem.scenario_id == scenario_id)
    if knowledge_type:
        statement = statement.where(RegulatoryKnowledgeItem.knowledge_type == knowledge_type)
    return list(db.scalars(statement.order_by(RegulatoryKnowledgeItem.id.desc()).limit(limit)).all())


@router.post("/projects/{project_id}/knowledge/search", response_model=KnowledgeSearchResponse)
def search_knowledge(project_id: int, payload: KnowledgeSearchRequest, db: Session = Depends(get_db)) -> KnowledgeSearchResponse:
    statement = select(RegulatoryKnowledgeItem).where(RegulatoryKnowledgeItem.project_id == project_id)
    for column, value in [
        (RegulatoryKnowledgeItem.target_table_code, payload.target_table_code),
        (RegulatoryKnowledgeItem.target_field_code, payload.target_field_code),
        (RegulatoryKnowledgeItem.target_field_name, payload.target_field_name),
        (RegulatoryKnowledgeItem.scenario_id, payload.scenario_id),
        (RegulatoryKnowledgeItem.knowledge_type, payload.knowledge_type),
    ]:
        if value is not None:
            statement = statement.where(column == value)
    rows = list(db.scalars(statement.order_by(RegulatoryKnowledgeItem.id.desc()).limit(500)).all())
    scored = sorted(((item, _keyword_score(item, payload.query)) for item in rows), key=lambda pair: (pair[1], pair[0].id), reverse=True)
    return KnowledgeSearchResponse(
        items=[
            ScoredKnowledgeItem(**RegulatoryKnowledgeItemRead.model_validate(item).model_dump(), score=score)
            for item, score in scored[: payload.top_k]
        ]
    )


def _validate_payload(db: Session, project_id: int, payload: RegulatoryKnowledgeItemCreate) -> None:
    if payload.knowledge_type not in KNOWLEDGE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid knowledge_type")
    if payload.scenario_id is not None:
        scenario = db.get(ProductScenario, payload.scenario_id)
        if scenario is None or scenario.project_id != project_id:
            raise HTTPException(status_code=400, detail="Scenario belongs to another project")


def _keyword_score(item: RegulatoryKnowledgeItem, query: str | None) -> float:
    if not query or not query.strip():
        return 1.0
    terms = [term.lower() for term in query.split() if term]
    text = " ".join(
        str(value or "") for value in [
            item.target_table_code, item.target_field_code, item.target_field_name, item.question_text,
            item.answer_text, item.institution_suggestion, item.regulatory_reply, item.business_explanation,
            " ".join(str(tag) for tag in (item.tags_json or [])),
        ]
    ).lower()
    matches = sum(1 for term in terms if term in text)
    return round((matches / max(len(terms), 1)) + (0.1 if item.target_field_code else 0), 4)
