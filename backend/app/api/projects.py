from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Project, ProjectMembership
from app.schemas import ProjectCreate, ProjectRead, ProjectStatusUpdate
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.governance.audit import record_audit

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
        pass
    else:
        if payload.institution_id is None:
            raise HTTPException(status_code=400, detail="institution_id is required")
        PermissionService(db, principal).require_institution_role(payload.institution_id, {"institution_admin", "security_admin"})

    if payload.client_request_id:
        existing = db.scalar(select(Project).where(Project.creation_request_id == payload.client_request_id))
        if existing is not None:
            if existing.institution_id != payload.institution_id:
                raise HTTPException(status_code=409, detail="创建请求已用于其他机构的项目")
            return existing

    values = payload.model_dump(exclude={"client_request_id"})
    project = Project(
        **values,
        creation_request_id=payload.client_request_id,
        project_owner_id=None if principal.is_legacy_system else principal.user_id,
    )
    db.add(project)
    try:
        db.flush()
        if principal.user_id is not None:
            db.add(ProjectMembership(project_id=project.id, user_id=principal.user_id, project_role="project_manager", status="active", created_by=principal.user_id))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if payload.client_request_id:
            existing = db.scalar(select(Project).where(Project.creation_request_id == payload.client_request_id))
            if existing is not None and existing.institution_id == payload.institution_id:
                return existing
        raise HTTPException(status_code=409, detail="项目创建请求冲突，请刷新后重试") from exc
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)) -> Project:
    return PermissionService(db, principal).require_project_permission(project_id, "project.view")


@router.patch("/{project_id}/status", response_model=ProjectRead)
def update_project_status(
    project_id: int,
    payload: ProjectStatusUpdate,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if principal.is_legacy_system:
        pass
    elif project.institution_id is None:
        raise HTTPException(status_code=403, detail="需要机构管理员权限")
    else:
        PermissionService(db, principal).require_institution_role(
            project.institution_id, {"institution_admin", "security_admin"}
        )
    previous = project.project_status
    if previous == payload.project_status:
        return project
    project.project_status = payload.project_status
    record_audit(
        db,
        action="restore_project" if payload.project_status == "active" else "suspend_project",
        resource_type="project",
        resource_id=project.id,
        actor_user_id=principal.user_id,
        institution_id=project.institution_id,
        project_id=project.id,
        before={"project_status": previous},
        after={"project_status": payload.project_status},
    )
    db.commit()
    db.refresh(project)
    return project
