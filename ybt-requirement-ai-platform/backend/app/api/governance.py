from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import InstitutionMembership, Project, ProjectMembership, User
from app.schemas.governance import ProjectMembershipCreate, ProjectMembershipRead
from app.services.auth.dependencies import RealPrincipal
from app.services.auth.permission_service import PROJECT_ROLE_PERMISSIONS, PermissionService
from app.services.governance.audit import record_audit


router = APIRouter(tags=["governance"])


@router.get("/projects/{project_id}/members", response_model=list[ProjectMembershipRead])
def list_project_members(project_id: int, principal: RealPrincipal, db: Session = Depends(get_db)) -> list[ProjectMembership]:
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    return list(db.scalars(select(ProjectMembership).where(ProjectMembership.project_id == project_id).order_by(ProjectMembership.id)).all())


@router.post("/projects/{project_id}/members", response_model=ProjectMembershipRead, status_code=201)
def add_project_member(project_id: int, payload: ProjectMembershipCreate, principal: RealPrincipal, db: Session = Depends(get_db)) -> ProjectMembership:
    project = PermissionService(db, principal).require_project_permission(project_id, "project.manage")
    if payload.project_role not in PROJECT_ROLE_PERMISSIONS:
        raise HTTPException(status_code=400, detail="Invalid project role")
    user = db.get(User, payload.user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=404, detail="User not found")
    if project.institution_id is not None:
        institution_member = db.scalar(select(InstitutionMembership.id).where(
            InstitutionMembership.institution_id == project.institution_id,
            InstitutionMembership.user_id == user.id,
            InstitutionMembership.status == "active",
        ).limit(1))
        if institution_member is None:
            raise HTTPException(status_code=400, detail="User is not an active member of the project institution")
    membership = db.scalar(select(ProjectMembership).where(ProjectMembership.project_id == project_id, ProjectMembership.user_id == user.id))
    if membership is None:
        membership = ProjectMembership(project_id=project_id, user_id=user.id, project_role=payload.project_role, status="active", created_by=principal.user_id)
        db.add(membership)
        before = {}
    else:
        before = {"project_role": membership.project_role, "status": membership.status}
        membership.project_role = payload.project_role
        membership.status = "active"
    db.flush()
    record_audit(
        db, action="permission_change", resource_type="project_membership", resource_id=membership.id,
        actor_user_id=principal.user_id, institution_id=project.institution_id, project_id=project.id,
        before=before, after={"user_id": user.id, "project_role": payload.project_role, "status": "active"},
    )
    db.commit()
    db.refresh(membership)
    return membership
