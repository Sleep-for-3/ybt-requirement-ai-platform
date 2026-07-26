from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Project, ProjectMembership
from app.schemas import ProjectCreate, ProjectRead
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRead])
def list_projects(principal: CurrentPrincipal, db: Session = Depends(get_db)) -> list[Project]:
    visible_ids = PermissionService(db, principal).visible_project_ids()
    statement = select(Project).order_by(Project.id.desc())
    if visible_ids is not None:
        statement = statement.where(Project.id.in_(visible_ids))
    return list(db.scalars(statement).all())


@router.post("", response_model=ProjectRead)
def create_project(payload: ProjectCreate, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> Project:
    if principal.is_legacy_system:
        project = Project(**payload.model_dump())
    else:
        if payload.institution_id is None:
            raise HTTPException(status_code=400, detail="institution_id is required")
        PermissionService(db, principal).require_institution_role(payload.institution_id, {"institution_admin", "security_admin"})
        project = Project(**payload.model_dump(), project_owner_id=principal.user_id)
    db.add(project)
    db.flush()
    if principal.user_id is not None:
        db.add(ProjectMembership(project_id=project.id, user_id=principal.user_id, project_role="project_manager", status="active", created_by=principal.user_id))
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> Project:
    return PermissionService(db, principal).require_project_permission(project_id, "project.view")
