from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas import SourceRecommendationResponse, SourceRecommendationSelectionResponse
from app.services.recommendation import recommend_source_fields, select_recommendation

router = APIRouter(tags=["source recommendations"])


@router.post("/target-fields/{field_id}/scenarios/{scenario_id}/recommend-sources", response_model=SourceRecommendationResponse)
def recommend_sources(field_id: int, scenario_id: int, db: Session = Depends(get_db)) -> SourceRecommendationResponse:
    try:
        return SourceRecommendationResponse(recommendations=recommend_source_fields(db, field_id, scenario_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/source-recommendations/{recommendation_id}/select", response_model=SourceRecommendationSelectionResponse)
def select_source_recommendation(recommendation_id: int, db: Session = Depends(get_db)) -> SourceRecommendationSelectionResponse:
    try:
        recommendation, lineage = select_recommendation(db, recommendation_id)
        return SourceRecommendationSelectionResponse(recommendation=recommendation, lineage=lineage)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
