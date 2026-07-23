from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.observability import build_log_event
from app.core.settings import Settings, get_settings
from app.main import app
from app.services.storage import get_storage_service


def test_production_configuration_validation_is_structured_and_secret_safe() -> None:
    settings = Settings(
        environment="production",
        auth_mode="optional",
        app_secret_key="default",
        jwt_secret_key="short",
        cors_origins="*",
        debug=True,
        storage_provider="s3",
        s3_bucket_name="",
        task_queue_provider="celery",
        redis_url="",
        llm_provider="openai",
        llm_api_key="super-secret-value",
    )

    issues = settings.validate_configuration()

    assert any(item["severity"] == "error" and item["code"] == "auth_mode_not_required" for item in issues)
    assert any(item["code"] == "s3_configuration_missing" for item in issues)
    serialized = str(issues)
    assert "super-secret-value" not in serialized
    assert {item["severity"] for item in issues} <= {"error", "warning", "info"}


def test_health_endpoints_are_bounded_sanitized_and_revision_aware(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "health-storage"))
    monkeypatch.setenv("HEALTH_DETAILS_PUBLIC", "true")
    get_settings.cache_clear()
    get_storage_service.cache_clear()
    try:
        with _client() as client:
            assert (tmp_path / "health-storage").is_dir()
            live = client.get("/health/live", headers={"X-Request-ID": "test-health-request"})
            assert live.status_code == 200
            assert live.json() == {"status": "healthy", "application": "YBT Requirement AI Platform"}
            assert live.headers["X-Request-ID"] == "test-health-request"

            ready = client.get("/health/ready")
            assert ready.status_code == 503
            assert ready.json()["checks"]["alembic_revision"] == "unhealthy"
            assert "database_url" not in ready.text.lower()

            details = client.get("/health/details")
            assert details.status_code == 200
            checks = details.json()["checks"]
            assert set(checks) == {"application", "database", "alembic_revision", "storage", "redis", "task_queue", "vector_store", "llm_provider", "embedding_provider", "disk_space"}
            assert checks["storage"]["status"] == "healthy"
            assert checks["redis"]["status"] == "disabled"
            assert "redis://" not in details.text
            assert "token" not in details.text.lower()
    finally:
        get_settings.cache_clear()
        get_storage_service.cache_clear()


def test_structured_log_event_has_required_fields_and_redacts_sensitive_input() -> None:
    event = build_log_event(
        "security_test",
        request_id="request-123",
        authorization="Bearer forbidden",
        cookie="session=forbidden",
        raw_sql="select secret_column from restricted_table",
        project_id=12,
    )

    assert set(("timestamp", "level", "logger", "request_id", "user_id", "institution_id", "project_id", "route", "method", "status_code", "duration_ms", "job_id", "event_type")) <= set(event)
    serialized = str(event).lower()
    assert "bearer forbidden" not in serialized
    assert "session=forbidden" not in serialized
    assert "secret_column" not in serialized


@contextmanager
def _client() -> Iterator[TestClient]:
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
