import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel

from app.services.llm.base import LLMConfigurationError, LLMResponseError
from app.services.llm.base import LLMProviderError, ModelCallMetadata
from app.services.llm.factory import get_llm_service
from app.services.llm.openai_compatible import OpenAICompatibleLLMService
from app.services.llm.providers import normalize_provider_type
from app.services.embeddings.openai_compatible import OpenAICompatibleEmbeddingService
from app.services.embeddings.observability import (
    embed_with_observability,
    ensure_embedding_external_allowed,
)
from app.models import AuditLog, ModelCallLog
from app.services.llm.prompt_runtime import PromptRuntime, execute_runtime_chat, prepare_model_input
from app.services.llm.structured_outputs import ScenarioBusinessOutput


class ConnectionResult(BaseModel):
    status: str
    message: str


def _response(content: str, *, status_code: int = 200, usage: dict | None = None) -> httpx.Response:
    payload = {
        "choices": [{"message": {"content": content}}],
        "usage": usage or {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
    }
    return httpx.Response(status_code, json=payload)


def test_provider_aliases_are_normalized_once() -> None:
    assert normalize_provider_type("openai-compatible") == "openai_compatible"
    assert normalize_provider_type("vllm") == "local_vllm"
    assert normalize_provider_type("ollama") == "local_ollama_compatible"


@pytest.mark.asyncio
async def test_real_provider_without_key_fails_without_mock_fallback(monkeypatch) -> None:
    monkeypatch.delenv("MISSING_LLM_KEY", raising=False)
    service = get_llm_service(
        provider="openai_compatible",
        base_url="https://provider.example.com/v1",
        api_key_env_name="MISSING_LLM_KEY",
        model="example-model",
    )

    with pytest.raises(LLMConfigurationError, match="MISSING_LLM_KEY"):
        await service.chat_json("system", "user")


@pytest.mark.asyncio
async def test_local_vllm_allows_an_empty_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return _response('{"status":"ok","message":"连接成功"}')

    service = OpenAICompatibleLLMService(
        base_url="http://vllm:8000/v1",
        api_key="",
        model="local-model",
        provider="local_vllm",
        transport=httpx.MockTransport(handler),
    )

    result = await service.chat_structured("system", "user", ConnectionResult)

    assert result.status == "ok"
    assert service.last_call.token_usage["total_tokens"] == 10


@pytest.mark.asyncio
async def test_json_mode_and_markdown_json_block_are_supported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        return _response('```json\n{"status":"ok","message":"连接成功"}\n```')

    service = OpenAICompatibleLLMService(
        base_url="https://provider.example.com/v1",
        api_key="test-only",
        model="example-model",
        provider="openai_compatible",
        transport=httpx.MockTransport(handler),
    )

    result = await service.chat_structured("system", "user", ConnectionResult)

    assert result.message == "连接成功"


@pytest.mark.asyncio
async def test_invalid_json_is_repaired_once_without_repeating_business_prompt() -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return _response("not-json")
        repair_text = body["messages"][1]["content"]
        assert "sensitive-business-payload" not in repair_text
        return _response('{"status":"ok","message":"连接成功"}')

    service = OpenAICompatibleLLMService(
        base_url="https://provider.example.com/v1",
        api_key="test-only",
        model="example-model",
        provider="openai_compatible",
        transport=httpx.MockTransport(handler),
    )

    result = await service.chat_structured(
        "system",
        "sensitive-business-payload",
        ConnectionResult,
    )

    assert result.status == "ok"
    assert len(requests) == 2
    assert service.last_call.token_usage["total_tokens"] == 20


def test_structured_draft_rejects_unrelated_object() -> None:
    with pytest.raises(Exception, match="missing business content"):
        ScenarioBusinessOutput.model_validate({"foo": "bar"})


@pytest.mark.asyncio
async def test_second_invalid_json_returns_controlled_error() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return _response("still-not-json")

    service = OpenAICompatibleLLMService(
        base_url="https://provider.example.com/v1",
        api_key="test-only",
        model="example-model",
        provider="openai_compatible",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LLMResponseError, match="valid JSON"):
        await service.chat_structured("system", "business", ConnectionResult)

    assert attempts == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 404])
async def test_non_retryable_http_errors_are_not_retried(status_code: int) -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status_code, json={"error": {"message": "unsafe upstream text"}})

    service = OpenAICompatibleLLMService(
        base_url="https://provider.example.com/v1",
        api_key="test-only",
        model="example-model",
        provider="openai_compatible",
        retry_count=2,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(Exception):
        await service.chat_json("system", "user")

    assert attempts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [429, 500])
async def test_transient_http_errors_use_bounded_retries(status_code: int) -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(status_code, json={"error": {"message": "temporary"}})
        return _response('{"status":"ok","message":"连接成功"}')

    async def no_sleep(_: float) -> None:
        return None

    service = OpenAICompatibleLLMService(
        base_url="https://provider.example.com/v1",
        api_key="test-only",
        model="example-model",
        provider="openai_compatible",
        retry_count=2,
        transport=httpx.MockTransport(handler),
        sleep_func=no_sleep,
    )

    result = await service.chat_structured("system", "user", ConnectionResult)

    assert result.status == "ok"
    assert attempts == 3
    assert service.last_call.retry_count == 2


def test_embedding_provider_requires_key_without_mock_fallback(monkeypatch) -> None:
    monkeypatch.delenv("MISSING_EMBEDDING_KEY", raising=False)
    service = OpenAICompatibleEmbeddingService(
        "https://provider.example.com/v1",
        "embedding-model",
        "MISSING_EMBEDDING_KEY",
        provider="openai_compatible",
    )

    with pytest.raises(LLMConfigurationError, match="MISSING_EMBEDDING_KEY"):
        service.embed_texts(["connection test"])


def test_embedding_provider_returns_numeric_vectors_and_usage(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_TEST_KEY", "test-only")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["input"] == ["connection test"]
        return httpx.Response(
            200,
            json={
                "data": [{"embedding": [0.1, 0.2, 0.3]}],
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
            },
        )

    service = OpenAICompatibleEmbeddingService(
        "https://provider.example.com/v1",
        "embedding-model",
        "EMBEDDING_TEST_KEY",
        provider="openai_compatible",
        transport=httpx.MockTransport(handler),
    )

    assert service.embed_query("connection test") == [0.1, 0.2, 0.3]
    assert service.last_call.token_usage["total_tokens"] == 2


@pytest.mark.asyncio
async def test_timeout_retries_are_bounded() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ReadTimeout("temporary timeout", request=request)
        return _response('{"status":"ok","message":"连接成功"}')

    async def no_sleep(_: float) -> None:
        return None

    service = OpenAICompatibleLLMService(
        base_url="https://provider.example.com/v1",
        api_key="test-only",
        model="example-model",
        provider="openai_compatible",
        retry_count=2,
        transport=httpx.MockTransport(handler),
        sleep_func=no_sleep,
    )

    assert (await service.chat_structured("system", "user", ConnectionResult)).status == "ok"
    assert attempts == 3


@pytest.mark.asyncio
async def test_failed_model_call_is_logged_without_prompt_or_key(db_session, monkeypatch) -> None:
    class FailingService:
        last_call = ModelCallMetadata(provider="openai_compatible", model="example-model", latency_ms=11, retry_count=2)

        async def chat_structured(self, *_):
            raise LLMProviderError("Model provider request failed", error_type="provider_error", http_status=503)

    runtime = PromptRuntime(
        prompt_key="scenario_business_mapping",
        version=1,
        system_prompt="system",
        user_template="",
        model_profile_id=None,
        provider_type="openai_compatible",
        base_url="https://provider.example.com/v1",
        model_name="example-model",
        api_key_env_name="OPENAI_API_KEY",
        local_only=False,
        config={},
    )
    monkeypatch.setattr("app.services.llm.prompt_runtime.get_runtime_llm_service", lambda _: FailingService())
    sensitive_prompt = "customer-data literal-secret-value"

    with pytest.raises(LLMProviderError):
        await execute_runtime_chat(db_session, 1, runtime, sensitive_prompt, ConnectionResult)

    log = db_session.query(ModelCallLog).one()
    assert log.status == "failed"
    assert log.error_type == "provider_error"
    assert log.provider == "openai_compatible"
    serialized = f"{log.input_summary} {log.output_summary}"
    assert sensitive_prompt not in serialized
    assert "literal-secret-value" not in serialized


def test_restricted_external_send_is_denied_and_audited(db_session) -> None:
    runtime = PromptRuntime(
        prompt_key="regulatory_field_explanation",
        version=1,
        system_prompt="system",
        user_template="",
        model_profile_id=7,
        provider_type="openai_compatible",
        base_url="https://provider.example.com/v1",
        model_name="example-model",
        api_key_env_name="OPENAI_API_KEY",
        local_only=False,
        config={},
    )

    with pytest.raises(ValueError, match="restricted"):
        prepare_model_input(runtime, "restricted-content", ["restricted"], db=db_session, project_id=1)

    audit = db_session.query(AuditLog).one()
    assert audit.action == "external_model_data_denied"
    assert audit.result == "denied"


def test_restricted_external_embedding_is_denied_and_audited(db_session) -> None:
    class ExternalEmbedding:
        local_only = False
        last_call = ModelCallMetadata(provider="openai_compatible", model="embedding-model")

    with pytest.raises(ValueError, match="restricted"):
        ensure_embedding_external_allowed(
            db_session,
            1,
            ExternalEmbedding(),
            ["restricted"],
            persist_denial=True,
        )

    audit = db_session.query(AuditLog).one()
    assert audit.action == "external_embedding_data_denied"
    assert audit.result == "denied"


def test_failed_embedding_call_is_logged_without_input(db_session) -> None:
    class FailingEmbedding:
        local_only = False
        last_call = ModelCallMetadata(
            provider="openai_compatible",
            model="embedding-model",
            latency_ms=9,
        )

        def embed_texts(self, _texts):
            raise LLMProviderError("Embedding provider failed", error_type="provider_error")

    sensitive_text = "customer-data secret=literal-secret-value"
    with pytest.raises(LLMProviderError):
        embed_with_observability(
            db_session,
            1,
            FailingEmbedding(),
            [sensitive_text],
            ["internal"],
        )

    log = db_session.query(ModelCallLog).one()
    assert log.status == "failed"
    assert log.prompt_key == "embedding"
    assert sensitive_text not in f"{log.input_summary} {log.output_summary}"
    assert "literal-secret-value" not in f"{log.input_summary} {log.output_summary}"


def test_compose_uses_private_env_not_public_template() -> None:
    compose = (Path(__file__).parents[2] / "docker-compose.yml").read_text(encoding="utf-8")
    assert "./backend/.env.example" not in compose
    assert compose.count("./backend/.env") >= 2


def test_local_setup_check_never_prints_secret_value() -> None:
    root = Path(__file__).parents[2]
    environment = {**os.environ, "OPENAI_API_KEY": "literal-secret-must-not-appear"}
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "check_local_setup.py")],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "literal-secret-must-not-appear" not in result.stdout
    assert "literal-secret-must-not-appear" not in result.stderr
