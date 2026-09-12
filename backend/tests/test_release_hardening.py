from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.core.database import Base, get_db
from app.core.settings import get_settings
from app.main import app
from app.services.storage import get_storage_service
from app.services.task_queue import get_task_queue


@contextmanager
def _production_client(monkeypatch, tmp_path) -> Iterator[TestClient]:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_MODE", "required")
    monkeypatch.setenv("APP_SECRET_KEY", "release-hardening-app-secret")
    monkeypatch.setenv("JWT_SECRET_KEY", "release-hardening-jwt-secret-with-more-than-32-chars")
    # Production validation must see the real deployment contract. The API's
    # database dependency remains an isolated in-memory SQLite session below.
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://release-test:unused@postgres/release_test")
    monkeypatch.setenv("STORAGE_PROVIDER", "local")
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("TASK_QUEUE_PROVIDER", "celery")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://redis:6379/0")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
    monkeypatch.setenv("VECTOR_STORE_PROVIDER", "mock")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("CORS_ORIGINS", "http://127.0.0.1:3000")
    get_settings.cache_clear()
    get_storage_service.cache_clear()
    get_task_queue.cache_clear()

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)

    def override() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
        get_settings.cache_clear()
        get_storage_service.cache_clear()
        get_task_queue.cache_clear()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_production_requires_auth_and_preserves_login_and_project_isolation(monkeypatch, tmp_path) -> None:
    with _production_client(monkeypatch, tmp_path) as client:
        unauthenticated = client.get("/api/projects")
        assert unauthenticated.status_code == 401
        assert "legacy-system" not in unauthenticated.text
        assert unauthenticated.json()["error_code"] == "authentication_required"

        admin_password = "Test-only-admin-password-2026"
        bootstrap = client.post("/api/admin/bootstrap", json={
            "institution_code": "RC_BANK",
            "institution_name": "RC 测试机构",
            "institution_type": "bank",
            "username": "rc_admin",
            "display_name": "RC 管理员",
            "email": "rc-admin@example.invalid",
            "password": admin_password,
        })
        assert bootstrap.status_code == 201, bootstrap.text
        institution_id = bootstrap.json()["institution_id"]

        admin_login = client.post("/api/auth/login", json={"username": "rc_admin", "password": admin_password})
        assert admin_login.status_code == 200, admin_login.text
        admin_headers = _bearer(admin_login.json()["access_token"])

        project_a = client.post("/api/projects", headers=admin_headers, json={
            "name": "RC 项目 A", "institution_id": institution_id,
        })
        project_b = client.post("/api/projects", headers=admin_headers, json={
            "name": "RC 项目 B", "institution_id": institution_id,
        })
        assert project_a.status_code == 200 and project_b.status_code == 200

        analyst_password = "Test-only-analyst-password-2026"
        analyst = client.post("/api/admin/users", headers=admin_headers, json={
            "username": "rc_analyst",
            "display_name": "RC 分析员",
            "email": "rc-analyst@example.invalid",
            "password": analyst_password,
            "institution_id": institution_id,
            "institution_role": "member",
        })
        assert analyst.status_code == 201, analyst.text
        membership = client.post(
            f"/api/projects/{project_a.json()['id']}/members",
            headers=admin_headers,
            json={"user_id": analyst.json()["id"], "project_role": "business_analyst"},
        )
        assert membership.status_code == 201, membership.text

        analyst_login = client.post("/api/auth/login", json={"username": "rc_analyst", "password": analyst_password})
        assert analyst_login.status_code == 200, analyst_login.text
        analyst_headers = _bearer(analyst_login.json()["access_token"])

        visible = client.get("/api/projects", headers=analyst_headers)
        assert visible.status_code == 200
        assert [item["id"] for item in visible.json()] == [project_a.json()["id"]]
        assert client.get(f"/api/projects/{project_a.json()['id']}", headers=analyst_headers).status_code == 200
        assert client.get(f"/api/projects/{project_b.json()['id']}", headers=analyst_headers).status_code == 404


def test_production_metrics_requires_authenticated_platform_admin(monkeypatch, tmp_path) -> None:
    with _production_client(monkeypatch, tmp_path) as client:
        assert client.get("/api/metrics").status_code == 401


def test_duplicate_admin_resources_report_conflict_instead_of_server_error(monkeypatch, tmp_path) -> None:
    """重复创建机构/用户必须返回 409，而不是数据库唯一约束冒出来的 500。

    端到端验收脚本靠这个状态码判断“复用既有资源”还是“新建资源”；返回 500 会让
    生产环境上的重复演练在第一步就中断，也掩盖了真正的冲突原因。
    """

    with _production_client(monkeypatch, tmp_path) as client:
        admin_password = "Test-only-admin-password-2026"
        bootstrap = client.post("/api/admin/bootstrap", json={
            "institution_code": "RC_DUP_PLATFORM",
            "institution_name": "RC 冲突平台运营方",
            "institution_type": "platform_operator",
            "username": "rc_dup_admin",
            "display_name": "RC 冲突管理员",
            "email": "rc-dup-admin@example.invalid",
            "password": admin_password,
        })
        assert bootstrap.status_code == 201, bootstrap.text
        admin_headers = _bearer(client.post(
            "/api/auth/login", json={"username": "rc_dup_admin", "password": admin_password},
        ).json()["access_token"])

        duplicate_institution = client.post("/api/admin/institutions", headers=admin_headers, json={
            "institution_code": "rc_dup_platform",
            "institution_name": "重复机构",
            "institution_type": "bank",
        })
        assert duplicate_institution.status_code == 409, duplicate_institution.text

        second_institution = client.post("/api/admin/institutions", headers=admin_headers, json={
            "institution_code": "RC_DUP_BANK2",
            "institution_name": "RC 第二机构",
            "institution_type": "bank",
        })
        assert second_institution.status_code == 201, second_institution.text
        second_id = second_institution.json()["id"]

        first_user = client.post("/api/admin/users", headers=admin_headers, json={
            "username": "rc_dup_user",
            "display_name": "RC 重复用户",
            "email": "rc-dup-user@example.invalid",
            "password": "Test-only-user-password-2026",
            "institution_id": second_id,
            "institution_role": "member",
        })
        assert first_user.status_code == 201, first_user.text

        duplicate_username = client.post("/api/admin/users", headers=admin_headers, json={
            "username": "RC_DUP_USER",
            "display_name": "RC 重复用户名",
            "email": "rc-dup-user-2@example.invalid",
            "password": "Test-only-user-password-2026",
            "institution_id": second_id,
            "institution_role": "member",
        })
        assert duplicate_username.status_code == 409, duplicate_username.text

        duplicate_email = client.post("/api/admin/users", headers=admin_headers, json={
            "username": "rc_dup_user_2",
            "display_name": "RC 重复邮箱",
            "email": "RC-DUP-USER@example.invalid",
            "password": "Test-only-user-password-2026",
            "institution_id": second_id,
            "institution_role": "member",
        })
        assert duplicate_email.status_code == 409, duplicate_email.text
