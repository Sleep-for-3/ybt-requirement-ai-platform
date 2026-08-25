from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.semantic_catalog import CatalogMode, SemanticCatalogPage
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.semantic.catalog_query_service import SemanticCatalogQueryService


router = APIRouter(tags=["semantic catalog"])


@router.get(
    "/projects/{project_id}/semantic-catalog",
    response_model=SemanticCatalogPage,
)
def list_semantic_catalog(
    project_id: int,
    principal: CurrentPrincipal,
    q: str | None = Query(default=None, max_length=500),
    as_of: date | None = Query(default=None),
    mode: CatalogMode = Query(default="candidate"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> SemanticCatalogPage:
    project = PermissionService(db, principal).require_project_permission(
        project_id, "project.view"
    )
    try:
        return SemanticCatalogQueryService(db, project).list_catalog(
            as_of=as_of or date.today(),
            mode=mode,
            query=q,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

