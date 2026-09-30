from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import CandidateSourceRecommendation, TargetField, ProductScenario
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.rag.data_field_answer_service import project_entity
from app.schemas import SourceRecommendationResponse, SourceRecommendationSelectionResponse
from app.services.llm.execution_metadata import deterministic_execution_metadata, stable_hash
from app.services.recommendation import adopt_recommendation, recommend_source_fields, select_recommendation

router = APIRouter(tags=["source recommendations"])


def authorize_recommendation(db, principal, recommendation_id):
    item = db.get(CandidateSourceRecommendation, recommendation_id)
    if item is None:
        raise HTTPException(404, "Source recommendation not found")
    if item.recommendation_basis == "bounded_catalog_recall" and principal.user_id is None:
        raise HTTPException(401, "Authenticated user required")
    PermissionService(db, principal).require_project_permission(item.project_id, "technical.edit")
    project_entity(db, TargetField, item.target_field_id, item.project_id)
    scenario = project_entity(db, ProductScenario, item.scenario_id, item.project_id)
    if not scenario.enabled:
        raise HTTPException(409, "场景已停用，请重新选择")


@router.post("/target-fields/{field_id}/scenarios/{scenario_id}/recommend-sources", response_model=SourceRecommendationResponse)
def recommend_sources(field_id: int, scenario_id: int, db: Session = Depends(get_db)) -> SourceRecommendationResponse:
    try:
        recommendations = recommend_source_fields(db, field_id, scenario_id)
        return SourceRecommendationResponse(
            recommendations=recommendations,
            execution_metadata=deterministic_execution_metadata(
                "source_recommendation",
                context_hash=stable_hash({
                    "target_field_id": field_id,
                    "scenario_id": scenario_id,
                    "candidate_ids": [item.id for item in recommendations],
                }),
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/source-recommendations/{recommendation_id}/adopt", response_model=SourceRecommendationSelectionResponse)
def adopt_source_recommendation(recommendation_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> SourceRecommendationSelectionResponse:
    authorize_recommendation(db, principal, recommendation_id)
    try:
        recommendation, lineage = adopt_recommendation(db, recommendation_id)
        return SourceRecommendationSelectionResponse(recommendation=recommendation, lineage=lineage)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/source-recommendations/{recommendation_id}/select", response_model=SourceRecommendationSelectionResponse)
def select_source_recommendation(recommendation_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> SourceRecommendationSelectionResponse:
    authorize_recommendation(db, principal, recommendation_id)
    try:
        recommendation, lineage = select_recommendation(db, recommendation_id)
        return SourceRecommendationSelectionResponse(recommendation=recommendation, lineage=lineage)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
