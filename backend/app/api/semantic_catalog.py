from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.semantic import ConceptType, SemanticStatus
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
    audit: bool = Query(default=False),
    concept_types: list[ConceptType] | None = Query(default=None, alias="type"),
    domains: list[str] | None = Query(default=None, alias="domain"),
    owners: list[str] | None = Query(default=None, alias="owner"),
    statuses: list[SemanticStatus] | None = Query(default=None, alias="status"),
    has_binding: bool | None = Query(default=None),
    has_relation: bool | None = Query(default=None),
    pending_review: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> SemanticCatalogPage:
    permission_service = PermissionService(db, principal)
    project = permission_service.require_project_permission(project_id, "project.view")
    effective_mode: CatalogMode = "audit" if audit else mode
    if effective_mode == "audit":
        permission_service.require_project_permission(project_id, "audit.read")
    permissions = permission_service.effective_project_permissions(project_id)
    try:
        return SemanticCatalogQueryService(db, project, permissions).list_catalog(
            as_of=as_of or date.today(),
            mode=effective_mode,
            query=q,
            concept_types=concept_types,
            domains=domains,
            owners=owners,
            statuses=statuses,
            has_binding=has_binding,
            has_relation=has_relation,
            pending_review=pending_review,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
