from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.project_readiness import build_onboarding_state, build_project_readiness

router = APIRouter(prefix="/projects/{project_id}", tags=["project-readiness"])


@router.get("/readiness")
def get_project_readiness(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    PermissionService(db, principal).require_project_permission(project_id, "deployment.readiness.view")
    try:
        return build_project_readiness(db, project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/onboarding")
def get_project_onboarding(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> dict:
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    try:
        return build_onboarding_state(db, project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
