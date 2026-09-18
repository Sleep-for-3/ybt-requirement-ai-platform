from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models import AuditLog, Institution, InstitutionMembership, Project, ProjectMembership, TargetTable, User
from app.services.auth.dependencies import Principal, get_current_principal


def _user(db, username: str) -> User:
    user = User(username=username, display_name=username, email=f"{username}@example.invalid", status="active")
    db.add(user)
    db.flush()
    return user


def test_project_suspend_and_restore_preserve_history_and_enforce_permissions() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db_session = sessionmaker(bind=engine)()
    institution = Institution(
        institution_code="LIFECYCLE_BANK",
        institution_name="生命周期隔离银行",
        institution_type="bank",
        status="active",
    )
    platform = Institution(
        institution_code="LIFECYCLE_PLATFORM",
        institution_name="生命周期隔离平台",
        institution_type="platform_operator",
        status="active",
    )
    db_session.add_all([institution, platform])
    db_session.flush()
    admin = _user(db_session, "lifecycle_admin")
    member = _user(db_session, "lifecycle_member")
    db_session.add_all([
        InstitutionMembership(
            institution_id=platform.id,
            user_id=admin.id,
            role="institution_admin",
            status="active",
            created_by=admin.id,
        ),
        InstitutionMembership(
            institution_id=institution.id,
            user_id=member.id,
            role="member",
            status="active",
            created_by=admin.id,
        ),
    ])
    db_session.commit()

    current = {"principal": Principal(admin.id, admin.username, admin.display_name)}
    app.dependency_overrides[get_current_principal] = lambda: current["principal"]
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            created = client.post("/api/projects", json={
                "name": "可停用隔离项目",
                "institution_id": institution.id,
                "bank_name": institution.institution_name,
                "description": "验证软生命周期",
                "client_request_id": "lifecycle-create-request-0001",
            })
            assert created.status_code == 200, created.text
            project_id = created.json()["id"]
            assert created.json()["project_status"] == "active"

            repeated_create = client.post("/api/projects", json={
                "name": "不应重复创建的副本",
                "institution_id": institution.id,
                "bank_name": institution.institution_name,
                "description": "同一创建请求必须返回原项目",
                "client_request_id": "lifecycle-create-request-0001",
            })
            assert repeated_create.status_code == 200, repeated_create.text
            assert repeated_create.json()["id"] == project_id
            assert db_session.scalar(select(func.count()).select_from(Project).where(
                Project.creation_request_id == "lifecycle-create-request-0001",
            )) == 1

            target = TargetTable(
                project_id=project_id,
                table_code="REPORT",
                table_name="监管报送表",
                description="停用后必须保留",
            )
            db_session.add(target)
            db_session.add(ProjectMembership(
                project_id=project_id,
                user_id=member.id,
                project_role="viewer",
                status="active",
                created_by=admin.id,
            ))
            db_session.commit()

            suspended = client.patch(f"/api/projects/{project_id}/status", json={"project_status": "suspended"})
            assert suspended.status_code == 200, suspended.text
            assert suspended.json()["project_status"] == "suspended"
            assert db_session.get(Project, project_id).project_status == "suspended"
            assert db_session.get(TargetTable, target.id).table_name == "监管报送表"
            assert db_session.scalar(select(func.count()).select_from(AuditLog).where(
                AuditLog.project_id == project_id,
                AuditLog.action == "suspend_project",
            )) == 1

            repeated = client.patch(f"/api/projects/{project_id}/status", json={"project_status": "suspended"})
            assert repeated.status_code == 200
            assert db_session.scalar(select(func.count()).select_from(AuditLog).where(
                AuditLog.project_id == project_id,
                AuditLog.action == "suspend_project",
            )) == 1

            current["principal"] = Principal(member.id, member.username, member.display_name)
            assert client.get("/api/projects").json() == []
            assert client.get(f"/api/projects/{project_id}").status_code == 409
            denied = client.patch(f"/api/projects/{project_id}/status", json={"project_status": "active"})
            assert denied.status_code == 403

            current["principal"] = Principal(admin.id, admin.username, admin.display_name)
            restored = client.patch(f"/api/projects/{project_id}/status", json={"project_status": "active"})
            assert restored.status_code == 200, restored.text
            assert restored.json()["project_status"] == "active"

            current["principal"] = Principal(member.id, member.username, member.display_name)
            assert [item["id"] for item in client.get("/api/projects").json()] == [project_id]
            assert client.get(f"/api/projects/{project_id}").status_code == 200
    finally:
        app.dependency_overrides.clear()
        db_session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
