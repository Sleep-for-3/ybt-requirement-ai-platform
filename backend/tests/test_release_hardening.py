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
