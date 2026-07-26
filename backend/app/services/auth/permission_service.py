from collections.abc import Iterable
from typing import Any, TypeVar

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Institution, InstitutionMembership, Project, ProjectMembership
from app.services.auth.dependencies import Principal


INSTITUTION_ROLES = {"institution_admin", "security_admin", "auditor", "member"}
PROJECT_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "project_manager": {"project.view", "project.manage", "business.edit", "business.review", "technical.edit", "technical.review", "final.review", "knowledge.manage", "catalog.manage", "audit.read", "export", "task.manage", "lineage.view", "lineage.manage", "lineage.review", "script.upload", "script.sync", "impact.view", "impact.review", "deliverable.view", "deliverable.manage", "deliverable.generate", "deliverable.review", "deliverable.export", "template.manage", "historical_caliber.import", "historical_caliber.reuse", "question.manage", "question.answer", "uat.view", "uat.manage", "uat.execute", "uat.finding.manage", "uat.signoff", "deployment.readiness.view", "deployment.readiness.manage"},
    "business_analyst": {"project.view", "business.edit", "knowledge.search", "export", "task.claim", "deliverable.view", "deliverable.generate", "question.answer", "uat.view", "uat.execute", "uat.finding.manage"},
    "technical_analyst": {"project.view", "technical.edit", "catalog.search", "profile.request", "knowledge.search", "export", "task.claim", "lineage.view", "script.upload", "impact.view", "deliverable.view", "deliverable.generate", "question.answer", "uat.view", "uat.execute", "uat.finding.manage"},
    "business_reviewer": {"project.view", "business.review", "knowledge.search", "export", "task.claim", "deliverable.view", "uat.view", "uat.signoff"},
    "technical_reviewer": {"project.view", "technical.review", "catalog.search", "knowledge.search", "export", "task.claim", "lineage.view", "lineage.review", "impact.view", "impact.review", "deliverable.view", "uat.view", "uat.signoff"},
    "final_reviewer": {"project.view", "final.review", "export", "task.claim", "deliverable.view", "deliverable.review", "deliverable.export", "uat.view", "uat.signoff"},
    "knowledge_manager": {"project.view", "knowledge.manage", "knowledge.search", "export", "task.claim", "deliverable.view", "historical_caliber.import", "historical_caliber.reuse"},
    "data_catalog_manager": {"project.view", "catalog.manage", "catalog.search", "profile.request", "export", "task.claim", "lineage.view", "lineage.manage", "script.sync", "impact.view"},
    "viewer": {"project.view", "export", "lineage.view", "deliverable.view", "uat.view"},
    "auditor": {"project.view", "audit.read", "deliverable.view", "deliverable.export", "uat.view", "deployment.readiness.view"},
}
ALL_PROJECT_PERMISSIONS = frozenset().union(*PROJECT_ROLE_PERMISSIONS.values())
AUDITOR_PROJECT_PERMISSIONS = frozenset({
    "project.view",
    "audit.read",
    "lineage.view",
    "impact.view",
    "deliverable.view",
    "deliverable.export",
    "uat.view",
    "deployment.readiness.view",
})
UAT_SIGNOFF_ROLES: dict[str, set[str]] = {
    "business_owner": {"business_reviewer", "project_manager"},
    "technical_owner": {"technical_reviewer", "project_manager"},
    "project_manager": {"project_manager"},
    "final_acceptance": {"final_reviewer", "project_manager"},
}

T = TypeVar("T")


class PermissionService:
    def __init__(self, db: Session, principal: Principal):
        self.db = db
        self.principal = principal

    def is_platform_admin(self) -> bool:
        if self.principal.is_legacy_system:
            return True
        if self.principal.user_id is None:
            return False
        return self.db.scalar(select(InstitutionMembership.id).join(
            Institution, Institution.id == InstitutionMembership.institution_id,
        ).where(
            InstitutionMembership.user_id == self.principal.user_id,
            InstitutionMembership.status == "active",
            InstitutionMembership.role.in_(["institution_admin", "security_admin"]),
            Institution.institution_type == "platform_operator",
            Institution.status == "active",
        ).limit(1)) is not None

    def require_institution_role(self, institution_id: int, roles: Iterable[str]) -> Institution:
        institution = self.db.get(Institution, institution_id)
        if institution is None or institution.status != "active":
            raise HTTPException(status_code=404, detail="Institution not found")
        if self.is_platform_admin():
            return institution
        membership = self.db.scalar(select(InstitutionMembership).where(
            InstitutionMembership.institution_id == institution_id,
            InstitutionMembership.user_id == self.principal.user_id,
            InstitutionMembership.status == "active",
        ))
        if membership is None:
            raise HTTPException(status_code=404, detail="Institution not found")
        if membership.role not in set(roles):
            raise HTTPException(status_code=403, detail="Insufficient institution role")
        return institution

    def require_project_role(self, project_id: int, roles: Iterable[str]) -> Project:
        project = self._visible_project(project_id)
        if self.is_platform_admin() or self._is_institution_admin(project):
            return project
        membership = self._project_membership(project_id)
        if membership is None:
            raise HTTPException(status_code=404, detail="Project not found")
        if membership.project_role not in set(roles):
            raise HTTPException(status_code=403, detail="Insufficient project role")
        return project

    def require_project_permission(self, project_id: int, permission: str) -> Project:
        project = self._visible_project(project_id)
        if permission not in self._permissions_for_project(project):
            raise HTTPException(status_code=403, detail=f"Missing project permission: {permission}")
        return project

    def effective_project_permissions(self, project_id: int) -> set[str]:
        """Return the one canonical permission set used by API authorization and clients."""
        return self._permissions_for_project(self._visible_project(project_id))

    def effective_permissions_for_visible_projects(self) -> dict[int, list[str]]:
        project_ids = self.visible_project_ids()
        if project_ids is None:
            project_ids = list(self.db.scalars(select(Project.id).order_by(Project.id)).all())
        return {project_id: sorted(self.effective_project_permissions(project_id)) for project_id in project_ids}

    def require_uat_signoff_role(self, project_id: int, signoff_role: str) -> Project:
        project = self.require_project_permission(project_id, "uat.signoff")
        if self.principal.is_legacy_system or self.is_platform_admin() or self._is_institution_admin(project):
            return project
        membership = self._project_membership(project_id)
        allowed_roles = UAT_SIGNOFF_ROLES.get(signoff_role, set())
        if membership is None or membership.project_role not in allowed_roles:
            raise HTTPException(status_code=403, detail=f"Project role cannot sign off as {signoff_role}")
        return project

    def load_project_resource_or_404(self, model: type[T], resource_id: int, permission: str = "project.view") -> T:
        resource = self.db.get(model, resource_id)
        if resource is None:
            raise HTTPException(status_code=404, detail=f"{model.__name__} not found")
        project_id = resource.id if isinstance(resource, Project) else getattr(resource, "project_id", None)
        if project_id is None:
            raise RuntimeError(f"{model.__name__} is not a project-scoped resource")
        self.require_project_permission(int(project_id), permission)
        return resource

    def visible_project_ids(self) -> list[int] | None:
        if self.is_platform_admin():
            return None
        if self.principal.user_id is None:
            return []
        managed_institutions = select(InstitutionMembership.institution_id).where(
            InstitutionMembership.user_id == self.principal.user_id,
            InstitutionMembership.status == "active",
            InstitutionMembership.role.in_(["institution_admin", "security_admin", "auditor"]),
        )
        return list(self.db.scalars(select(Project.id).where(
            (Project.id.in_(select(ProjectMembership.project_id).where(
                ProjectMembership.user_id == self.principal.user_id,
                ProjectMembership.status == "active",
            ))) | (Project.institution_id.in_(managed_institutions))
        )).all())

    def _visible_project(self, project_id: int) -> Project:
        project = self.db.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        if self.principal.is_legacy_system or self.is_platform_admin():
            return project
        if self._project_membership(project_id) or self._has_institution_role(project, {"institution_admin", "security_admin", "auditor"}):
            return project
        raise HTTPException(status_code=404, detail="Project not found")

    def _project_membership(self, project_id: int) -> ProjectMembership | None:
        if self.principal.user_id is None:
            return None
        return self.db.scalar(select(ProjectMembership).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == self.principal.user_id,
            ProjectMembership.status == "active",
        ))

    def _permissions_for_project(self, project: Project) -> set[str]:
        if self.principal.is_legacy_system or self.is_platform_admin() or self._is_institution_admin(project):
            return set(ALL_PROJECT_PERMISSIONS)
        permissions: set[str] = set()
        if self._has_institution_role(project, {"auditor"}):
            permissions.update(AUDITOR_PROJECT_PERMISSIONS)
        membership = self._project_membership(project.id)
        if membership is not None:
            permissions.update(PROJECT_ROLE_PERMISSIONS.get(membership.project_role, set()))
        return permissions

    def _is_institution_admin(self, project: Project) -> bool:
        if project.institution_id is None or self.principal.user_id is None:
            return self.principal.is_legacy_system
        return self.db.scalar(select(InstitutionMembership.id).where(
            InstitutionMembership.institution_id == project.institution_id,
            InstitutionMembership.user_id == self.principal.user_id,
            InstitutionMembership.status == "active",
            InstitutionMembership.role.in_(["institution_admin", "security_admin"]),
        ).limit(1)) is not None

    def _has_institution_role(self, project: Project, roles: set[str]) -> bool:
        if project.institution_id is None or self.principal.user_id is None:
            return False
        return self.db.scalar(select(InstitutionMembership.id).where(
            InstitutionMembership.institution_id == project.institution_id,
            InstitutionMembership.user_id == self.principal.user_id,
            InstitutionMembership.status == "active",
            InstitutionMembership.role.in_(roles),
        ).limit(1)) is not None


def require_institution_role(db: Session, principal: Principal, institution_id: int, *roles: str) -> Institution:
    return PermissionService(db, principal).require_institution_role(institution_id, roles)


def require_project_role(db: Session, principal: Principal, project_id: int, *roles: str) -> Project:
    return PermissionService(db, principal).require_project_role(project_id, roles)


def require_project_permission(db: Session, principal: Principal, project_id: int, permission: str) -> Project:
    return PermissionService(db, principal).require_project_permission(project_id, permission)


def load_project_resource_or_404(db: Session, principal: Principal, model: type[T], resource_id: int, permission: str = "project.view") -> T:
    return PermissionService(db, principal).load_project_resource_or_404(model, resource_id, permission)
