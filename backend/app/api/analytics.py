from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.analytics.metric_query_service import build_project_overview
from app.services.auth.dependencies import RealPrincipal
from app.services.auth.permission_service import PermissionService


router = APIRouter(tags=["analytics"])


@router.get("/projects/{project_id}/analytics/overview")
def analytics_overview(project_id: int, principal: RealPrincipal, cycle_id: int | None = None, db: Session = Depends(get_db)) -> dict:
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    try:
        return build_project_overview(db, project_id, cycle_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Reporting cycle not found for project") from exc
