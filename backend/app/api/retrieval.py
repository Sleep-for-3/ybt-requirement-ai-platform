from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas import RetrievalSearchRequest, RetrievalSearchResponse
from app.services.retrieval import search_knowledge

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.post("/search", response_model=RetrievalSearchResponse)
async def search(payload: RetrievalSearchRequest, db: Session = Depends(get_db)) -> RetrievalSearchResponse:
    results = await search_knowledge(
        db,
        project_id=payload.project_id,
        query=payload.query,
        top_k=payload.top_k,
        filters=payload.filters,
    )
    return RetrievalSearchResponse(results=results)
