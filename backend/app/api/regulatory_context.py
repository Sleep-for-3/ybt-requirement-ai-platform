from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.regulatory_context import (
    ContextMode,
    RegulatoryContext,
    RegulatoryContextRequest,
)
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.semantic.context_builder import RegulatoryContextBuilder


router = APIRouter(prefix="/projects/{project_id}", tags=["regulatory-context"])


@router.get("/regulatory-context", response_model=RegulatoryContext)
def get_regulatory_context(
    project_id: int,
    principal: CurrentPrincipal,
    as_of: date = Query(...),
    target_table_id: int | None = Query(default=None, gt=0),
    target_field_id: int | None = Query(default=None, gt=0),
    scenario_id: int | None = Query(default=None, gt=0),
    mart_field_id: int | None = Query(default=None, gt=0),
    semantic_concept_id: int | None = Query(default=None, gt=0),
    reporting_period: str | None = Query(default=None, max_length=120),
    mode: ContextMode = Query(default=ContextMode.TRUSTED),
    candidate_limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> RegulatoryContext:
    project = PermissionService(db, principal).require_project_permission(
        project_id,
        "project.view",
    )
    request = RegulatoryContextRequest(
        project_id=project_id,
        target_table_id=target_table_id,
        target_field_id=target_field_id,
        scenario_id=scenario_id,
        mart_field_id=mart_field_id,
        semantic_concept_id=semantic_concept_id,
        as_of=as_of,
        reporting_period=reporting_period,
        mode=mode,
        candidate_limit=candidate_limit,
    )
    builder = RegulatoryContextBuilder(db)
    try:
        return builder.build(request, authorized_project=project)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
