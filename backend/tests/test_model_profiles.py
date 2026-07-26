import pytest
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.ai_runtime import ConnectionTestOutput, ModelProfileCreate, sanitize_base_url
from app.services.llm.base import LLMConfigurationError
from app.services.llm.providers import ProviderRuntimeConfig
from app.core.database import Base, get_db
from app.core.settings import get_settings
from app.main import app
from app.services.auth.dependencies import Principal, get_current_principal


def test_model_profile_rejects_api_key_fields() -> None:
    with pytest.raises(ValidationError):
        ModelProfileCreate(
            profile_name="unsafe",
            provider_type="openai",
            base_url="https://provider.example.com/v1",
            model_name="example-model",
            api_key_env_name="OPENAI_API_KEY",
            config_json={"api_key": "must-not-persist"},
        )


def test_model_profile_validates_environment_variable_name() -> None:
    with pytest.raises(ValidationError):
        ModelProfileCreate(
            profile_name="invalid-env",
            provider_type="openai",
            base_url="https://provider.example.com/v1",
            model_name="example-model",
            api_key_env_name="not-valid",
        )


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://169.254.169.254/latest/meta-data",
        "http://127.0.0.1:8000/v1",
        "https://user:password@provider.example.com/v1",
    ],
)
def test_external_profile_rejects_ssrf_and_credential_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        ModelProfileCreate(
            profile_name="unsafe-url",
            provider_type="openai_compatible",
            base_url=url,
            model_name="example-model",
            api_key_env_name="OPENAI_API_KEY",
            local_only=False,
        )


def test_local_profile_allows_local_service_url() -> None:
    profile = ModelProfileCreate(
        profile_name="local",
        provider_type="local_vllm",
        base_url="http://vllm:8000/v1",
        model_name="local-model",
        local_only=True,
    )

    assert profile.provider_type == "local_vllm"


def test_runtime_rejects_cloud_hostname_resolving_to_private_address(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.llm.providers.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("10.0.0.7", 443))],
    )
    runtime = ProviderRuntimeConfig(
        provider="openai_compatible",
        base_url="https://runtime.vendor.example.net/v1",
        model="example-model",
        api_key_env_name="OPENAI_API_KEY",
        api_key="test-only",
        local_only=False,
    )

    with pytest.raises(LLMConfigurationError, match="non-public"):
        runtime.validate()


def test_connection_test_schema_only_accepts_ok_status() -> None:
    with pytest.raises(ValidationError):
        ConnectionTestOutput.model_validate({"status": "mock", "message": "not connected"})


def test_status_url_sanitizer_removes_query_and_userinfo() -> None:
    assert (
        sanitize_base_url("https://user:secret@provider.example.com/v1?token=secret#fragment")
        == "https://provider.example.com/v1"
    )


def test_profile_api_crud_activation_and_secret_safe_status(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "optional")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("PROFILE_TEST_KEY", raising=False)
    with _client() as client:
        created = client.post(
            "/api/model-profiles",
            json={
                "profile_name": "external-test",
                "provider_type": "openai-compatible",
                "base_url": "https://provider.example.com/v1",
                "model_name": "example-model",
                "api_key_env_name": "PROFILE_TEST_KEY",
                "local_only": False,
                "config_json": {"json_mode": True, "retry_count": 1},
            },
        )
        assert created.status_code == 201, created.text
        profile = created.json()
        assert profile["provider_type"] == "openai_compatible"
        assert profile["api_key_present"] is False
        assert "test-only" not in created.text

        missing_key = client.post(f"/api/model-profiles/{profile['id']}/activate")
        assert missing_key.status_code == 422
        monkeypatch.setenv("PROFILE_TEST_KEY", "test-only")
        activated = client.post(f"/api/model-profiles/{profile['id']}/activate")
        assert activated.status_code == 200
        assert activated.json()["enabled"] is True

        status = client.get("/api/ai-runtime/status")
        assert status.status_code == 200
        assert status.json()["llm"]["is_mock"] is False
        assert status.json()["llm"]["api_key_present"] is True
        assert "test-only" not in status.text

        disabled = client.post(f"/api/model-profiles/{profile['id']}/disable")
        assert disabled.status_code == 200
        assert disabled.json()["enabled"] is False


def test_profile_api_rejects_secret_payload() -> None:
    with _client() as client:
        response = client.post(
            "/api/model-profiles",
            json={
                "profile_name": "unsafe",
                "provider_type": "openai",
                "base_url": "https://provider.example.com/v1",
                "model_name": "example-model",
                "api_key": "literal-secret-value",
            },
        )
        assert response.status_code == 422
        assert "literal-secret-value" not in response.text


def test_failed_enabled_profile_creation_does_not_leave_orphan(monkeypatch) -> None:
    monkeypatch.delenv("MISSING_PROFILE_KEY", raising=False)
    with _client() as client:
        response = client.post(
            "/api/model-profiles",
            json={
                "profile_name": "must-not-persist",
                "provider_type": "openai_compatible",
                "base_url": "https://provider.example.com/v1",
                "model_name": "example-model",
                "api_key_env_name": "MISSING_PROFILE_KEY",
                "enabled": True,
            },
        )
        assert response.status_code == 422
        assert all(item["profile_name"] != "must-not-persist" for item in client.get("/api/model-profiles").json())


def test_non_admin_cannot_modify_model_profiles() -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(999, "viewer", "Viewer")
    try:
        with _client() as client:
            response = client.post(
                "/api/model-profiles",
                json={"profile_name": "denied", "provider_type": "mock"},
            )
            assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


def test_non_admin_only_sees_basic_active_profile_fields() -> None:
    with _client() as client:
        created = client.post(
            "/api/model-profiles",
            json={
                "profile_name": "visible-basic",
                "provider_type": "mock",
                "enabled": True,
                "config_json": {"temperature": 0.1},
            },
        )
        assert created.status_code == 201
        app.dependency_overrides[get_current_principal] = lambda: Principal(999, "viewer", "Viewer")
        try:
            response = client.get("/api/model-profiles")
            assert response.status_code == 200
            profile = response.json()[0]
            assert set(profile) == {
                "id",
                "profile_name",
                "provider_type",
                "model_name",
                "is_mock",
                "is_local",
                "enabled",
            }
        finally:
            app.dependency_overrides.pop(get_current_principal, None)


@contextmanager
def _client() -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
        get_settings.cache_clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
