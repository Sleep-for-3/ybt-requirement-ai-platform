import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.settings import get_settings
from app.models import Institution, InstitutionMembership, Project, ProjectMembership, User
from app.services.auth.dependencies import Principal, require_real_user
from app.services.auth.permission_service import INSTITUTION_ROLES, PROJECT_ROLE_PERMISSIONS, PermissionService


def _user(db, username: str) -> User:
    user = User(username=username, display_name=username, email=f"{username}@example.invalid", status="active")
    db.add(user)
    db.flush()
    return user


def _institution(db, code: str, kind: str = "bank") -> Institution:
    institution = Institution(institution_code=code, institution_name=code, institution_type=kind, status="active")
    db.add(institution)
    db.flush()
    return institution


@pytest.mark.parametrize(
    ("role", "institution_type", "expected"),
    [
        ("institution_admin", "platform_operator", {"can_view_admin": True, "can_view_permission_matrix": True, "can_view_institution_cockpit": True, "can_view_all_projects": True}),
        ("institution_admin", "bank", {"can_view_admin": True, "can_manage_users": True, "can_view_permission_matrix": False, "can_view_institution_cockpit": True}),
        ("security_admin", "bank", {"can_view_admin": True, "can_manage_users": True, "can_view_permission_matrix": False, "can_view_institution_cockpit": True}),
        ("auditor", "bank", {"can_view_admin": False, "can_manage_users": False, "can_view_permission_matrix": False, "can_view_institution_cockpit": True}),
        ("member", "bank", {"can_view_admin": False, "can_manage_users": False, "can_view_permission_matrix": False, "can_view_institution_cockpit": False}),
    ],
)
def test_server_computed_capabilities_for_institution_roles(db_session, role, institution_type, expected) -> None:
    institution = _institution(db_session, f"INST_{role}_{institution_type}", institution_type)
    user = _user(db_session, f"user_{role}_{institution_type}")
    db_session.add(InstitutionMembership(institution_id=institution.id, user_id=user.id, role=role, status="active", created_by=user.id))
    db_session.commit()

    actual = PermissionService(db_session, Principal(user.id, user.username, user.display_name)).capabilities()
    assert actual | expected == actual
    assert {key: actual[key] for key in expected} == expected


@pytest.mark.parametrize("project_role", sorted(PROJECT_ROLE_PERMISSIONS))
def test_project_roles_do_not_imply_admin_or_institution_cockpit(db_session, project_role) -> None:
    institution = _institution(db_session, f"BANK_{project_role}")
    user = _user(db_session, f"project_{project_role}")
    project = Project(name=project_role, institution_id=institution.id, bank_name=institution.institution_name)
    db_session.add(project)
    db_session.flush()
    db_session.add_all([
        InstitutionMembership(institution_id=institution.id, user_id=user.id, role="member", status="active", created_by=user.id),
        ProjectMembership(project_id=project.id, user_id=user.id, project_role=project_role, status="active", created_by=user.id),
    ])
    db_session.commit()
    capabilities = PermissionService(db_session, Principal(user.id, user.username, user.display_name)).capabilities()
    assert capabilities["can_view_admin"] is False
    assert capabilities["can_view_institution_cockpit"] is False


def test_disabled_institution_does_not_grant_cockpit_capability_or_project_visibility(db_session) -> None:
    institution = _institution(db_session, "DISABLED_BANK")
    institution.status = "inactive"
    user = _user(db_session, "disabled_auditor")
    project = Project(name="停用机构项目", institution_id=institution.id)
    db_session.add(project)
    db_session.flush()
    db_session.add(InstitutionMembership(institution_id=institution.id, user_id=user.id, role="auditor", status="active", created_by=user.id))
    db_session.commit()
    service = PermissionService(db_session, Principal(user.id, user.username, user.display_name))
    assert service.capabilities()["can_view_institution_cockpit"] is False
    assert project.id not in service.visible_project_ids()


def test_product_language_covers_every_backend_role_and_permission() -> None:
    path = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "permission-language.json"
    language = json.loads(path.read_text(encoding="utf-8"))
    assert set(language["institutionRoles"]) == INSTITUTION_ROLES
    assert set(language["projectRoles"]) == set(PROJECT_ROLE_PERMISSIONS)
    backend_permissions = set().union(*PROJECT_ROLE_PERMISSIONS.values())
    assert set(language["permissions"]) == backend_permissions


@pytest.fixture()
def integrity_client(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "required")
    monkeypatch.setenv("JWT_SECRET_KEY", "tests-generate-this-non-production-secret")
    get_settings.cache_clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    session = factory()

    def override_db():
        yield session

    from app.main import app
    app.dependency_overrides[get_db] = override_db
    try:
        yield app, session
    finally:
        app.dependency_overrides.clear()
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
        get_settings.cache_clear()


def _platform_principal(session) -> Principal:
    institution = _institution(session, "PLATFORM", "platform_operator")
    user = _user(session, "platform_admin")
    session.add(InstitutionMembership(institution_id=institution.id, user_id=user.id, role="institution_admin", status="active", created_by=user.id))
    session.commit()
    return Principal(user.id, user.username, user.display_name)


def test_cockpit_returns_partial_when_one_project_analytics_fails(integrity_client, monkeypatch) -> None:
    app, session = integrity_client
    principal = _platform_principal(session)
    session.add_all([Project(name="正常项目", bank_name="示例银行"), Project(name="异常项目", bank_name="示例银行")])
    session.commit()

    def overview(_db, project_id):
        if project_id == 2:
            raise RuntimeError("synthetic project analytics failure")
        return {"metrics": {"readiness_score": {"value": 0.75, "numerator": 3, "denominator": 4}}, "risk_distribution": [], "as_of": "2026-08-28T00:00:00+00:00"}

    monkeypatch.setattr("app.api.cockpit.build_project_overview", overview)
    app.dependency_overrides[require_real_user] = lambda: principal
    with TestClient(app) as client:
        response = client.get("/api/cockpit", headers={"X-Request-ID": "partial-cockpit-test"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data_status"] == "partial"
    assert payload["unavailable_project_count"] == 1
    assert {row["data_status"] for row in payload["projects"]} == {"ready", "unavailable"}
    unavailable = next(row for row in payload["projects"] if row["data_status"] == "unavailable")
    assert unavailable["trace_id"] == "partial-cockpit-test"
    assert "synthetic" not in json.dumps(payload)


def test_cockpit_all_project_failures_return_system_error(integrity_client, monkeypatch) -> None:
    app, session = integrity_client
    principal = _platform_principal(session)
    session.add(Project(name="异常项目", bank_name="示例银行"))
    session.commit()
    monkeypatch.setattr("app.api.cockpit.build_project_overview", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    app.dependency_overrides[require_real_user] = lambda: principal
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/cockpit", headers={"X-Request-ID": "failed-cockpit-test"})
    assert response.status_code == 500
    assert response.json()["error_code"] == "cockpit_data_unavailable"
    assert response.json()["detail"]["message"] == "驾驶舱数据计算失败"
    assert response.json()["trace_id"] == "failed-cockpit-test"


def test_member_is_forbidden_from_institution_cockpit(integrity_client) -> None:
    app, session = integrity_client
    institution = _institution(session, "MEMBER_BANK")
    user = _user(session, "ordinary_member")
    session.add(InstitutionMembership(institution_id=institution.id, user_id=user.id, role="member", status="active", created_by=user.id))
    session.commit()
    app.dependency_overrides[require_real_user] = lambda: Principal(user.id, user.username, user.display_name)
    with TestClient(app) as client:
        response = client.get("/api/cockpit")
    assert response.status_code == 403
    assert response.json()["error_code"] == "permission_denied"


def test_auth_me_exposes_server_computed_capabilities(integrity_client) -> None:
    app, session = integrity_client
    principal = _platform_principal(session)
    app.dependency_overrides[require_real_user] = lambda: principal
    with TestClient(app) as client:
        response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["capabilities"]["can_view_admin"] is True
    assert response.json()["capabilities"]["can_view_all_projects"] is True


def test_database_failure_is_not_downgraded_to_partial(integrity_client, monkeypatch) -> None:
    app, session = integrity_client
    principal = _platform_principal(session)
    session.add(Project(name="Schema 异常项目", bank_name="示例银行"))
    session.commit()
    monkeypatch.setattr("app.api.cockpit.build_project_overview", lambda *_: (_ for _ in ()).throw(SQLAlchemyError("schema mismatch")))
    app.dependency_overrides[require_real_user] = lambda: principal
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/cockpit", headers={"X-Request-ID": "schema-cockpit-test"})
    assert response.status_code == 500
    assert response.json()["error_code"] == "internal_error"
    assert response.json()["trace_id"] == "schema-cockpit-test"
