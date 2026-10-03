"""B02 / BA05: a deactivated institution must not grant project access by any route.

The original defect: the project list and capability query joined the institution and checked
its status, but the two direct-institution-role helpers only looked at membership rows, so a
user could still reach a known project id (read, write, related resources) after the
institution was deactivated. These tests pin the unified guard on every entry point.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.models import (
    Institution,
    InstitutionMembership,
    Project,
    ProjectMembership,
    TargetField,
    TargetTable,
    User,
)
from app.services.auth.dependencies import Principal
from app.services.auth.permission_service import PermissionService


def _institution(db, code: str, *, status: str = "active", kind: str = "bank") -> Institution:
    institution = Institution(institution_code=code, institution_name=code,
                              institution_type=kind, status=status)
    db.add(institution)
    db.flush()
    return institution


def _user(db, username: str) -> User:
    user = User(username=username, display_name=username,
                email=f"{username}@example.invalid", status="active")
    db.add(user)
    db.flush()
    return user


def _project(db, institution: Institution, name: str) -> Project:
    project = Project(name=name, institution_id=institution.id)
    db.add(project)
    db.flush()
    return project


def _service(db, user: User) -> PermissionService:
    return PermissionService(db, Principal(user.id, user.username, user.display_name))


def _institution_admin_project(db, *, institution_status: str):
    institution = _institution(db, "GUARD_BANK", status=institution_status)
    user = _user(db, "guard_admin")
    project = _project(db, institution, "熔断项目")
    db.add(InstitutionMembership(institution_id=institution.id, user_id=user.id,
                                 role="institution_admin", status="active", created_by=user.id))
    db.commit()
    return institution, user, project


def test_active_institution_admin_keeps_full_project_access(db_session) -> None:
    _institution, user, project = _institution_admin_project(db_session, institution_status="active")
    service = _service(db_session, user)
    assert project.id in (service.visible_project_ids() or [])
    assert service.require_project_permission(project.id, "project.manage").id == project.id


@pytest.mark.parametrize("permission", ["project.view", "project.manage", "technical.edit"])
def test_deactivated_institution_blocks_direct_project_permission(db_session, permission) -> None:
    _institution, user, project = _institution_admin_project(db_session, institution_status="inactive")
    service = _service(db_session, user)
    # the list already hid it; the direct-id route must agree
    assert project.id not in service.visible_project_ids()
    with pytest.raises(HTTPException) as excinfo:
        service.require_project_permission(project.id, permission)
    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "Project not found"


def test_deactivated_institution_grants_no_effective_permissions(db_session) -> None:
    institution, user, project = _institution_admin_project(db_session, institution_status="inactive")
    service = _service(db_session, user)
    with pytest.raises(HTTPException):
        service.effective_project_permissions(project.id)
    assert service._is_institution_admin(project) is False
    assert service._has_institution_role(project, {"auditor"}) is False


def test_deactivated_institution_blocks_related_resource_access(db_session) -> None:
    institution, user, project = _institution_admin_project(db_session, institution_status="inactive")
    table = TargetTable(project_id=project.id, table_code="GUARD_T", table_name="熔断表")
    db_session.add(table)
    db_session.flush()
    field = TargetField(project_id=project.id, target_table_id=table.id,
                        field_code="GUARD_F", field_name="熔断字段")
    db_session.add(field)
    db_session.commit()

    service = _service(db_session, user)
    with pytest.raises(HTTPException) as excinfo:
        service.load_project_resource_or_404(TargetField, field.id, "project.view")
    assert excinfo.value.status_code == 404


def test_deactivated_institution_blocks_auditor_role_as_well(db_session) -> None:
    institution = _institution(db_session, "GUARD_AUDIT", status="inactive")
    user = _user(db_session, "guard_auditor")
    project = _project(db_session, institution, "熔断审计项目")
    db_session.add(InstitutionMembership(institution_id=institution.id, user_id=user.id,
                                         role="auditor", status="active", created_by=user.id))
    db_session.commit()
    service = _service(db_session, user)
    with pytest.raises(HTTPException) as excinfo:
        service.require_project_permission(project.id, "project.view")
    assert excinfo.value.status_code == 404


def test_member_of_deactivated_institution_is_blocked_too(db_session) -> None:
    institution = _institution(db_session, "GUARD_MEMBER", status="inactive")
    user = _user(db_session, "guard_member")
    project = _project(db_session, institution, "熔断成员项目")
    db_session.add(InstitutionMembership(institution_id=institution.id, user_id=user.id,
                                         role="member", status="active", created_by=user.id))
    db_session.add(ProjectMembership(project_id=project.id, user_id=user.id,
                                     project_role="project_manager", status="active",
                                     created_by=user.id))
    db_session.commit()
    service = _service(db_session, user)
    assert project.id not in service.visible_project_ids()
    with pytest.raises(HTTPException) as excinfo:
        service.require_project_permission(project.id, "project.view")
    assert excinfo.value.status_code == 404


def test_platform_admin_remains_the_explicit_recovery_path(db_session) -> None:
    # The platform-admin role comes from an ACTIVE platform-operator institution ...
    platform = _institution(db_session, "GUARD_PLATFORM", kind="platform_operator")
    bank = _institution(db_session, "GUARD_RECOVERY_BANK", status="inactive")
    user = _user(db_session, "guard_platform_admin")
    project = _project(db_session, bank, "停用机构待恢复项目")
    db_session.add(InstitutionMembership(institution_id=platform.id, user_id=user.id,
                                         role="institution_admin", status="active", created_by=user.id))
    db_session.commit()
    service = _service(db_session, user)
    assert service.is_platform_admin() is True
    # ... and is the documented recovery exception for a deactivated institution's project.
    assert service.require_project_permission(project.id, "project.manage").id == project.id


def test_deactivated_platform_operator_institution_grants_no_platform_admin(db_session) -> None:
    platform = _institution(db_session, "GUARD_PLATFORM_OFF", status="inactive", kind="platform_operator")
    user = _user(db_session, "guard_platform_off")
    project = _project(db_session, platform, "停用平台项目")
    db_session.add(InstitutionMembership(institution_id=platform.id, user_id=user.id,
                                         role="institution_admin", status="active", created_by=user.id))
    db_session.commit()
    service = _service(db_session, user)
    assert service.is_platform_admin() is False
    with pytest.raises(HTTPException) as excinfo:
        service.require_project_permission(project.id, "project.manage")
    assert excinfo.value.status_code == 404


def test_cross_institution_access_is_rejected(db_session) -> None:
    active = _institution(db_session, "GUARD_A")
    inactive = _institution(db_session, "GUARD_B", status="inactive")
    outsider = _user(db_session, "guard_outsider")
    project_a = _project(db_session, active, "A 项目")
    project_b = _project(db_session, inactive, "B 项目")
    db_session.add(InstitutionMembership(institution_id=active.id, user_id=outsider.id,
                                         role="member", status="active", created_by=outsider.id))
    db_session.commit()
    service = _service(db_session, outsider)
    for project in (project_a, project_b):
        with pytest.raises(HTTPException) as excinfo:
            service.require_project_permission(project.id, "project.view")
        assert excinfo.value.status_code == 404
