import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel

from app.services.llm.base import LLMConfigurationError, LLMResponseError
from app.services.llm.base import (
    MAX_ERROR_DETAIL_CHARS,
    LLMProviderError,
    ModelCallMetadata,
    sanitize_provider_error_detail,
)
from app.core.settings import Settings, get_settings
from app.services.llm.factory import get_interactive_llm_service, get_llm_service
from app.services.llm.openai_compatible import OpenAICompatibleLLMService
from app.services.llm import providers
from app.services.llm.providers import normalize_provider_type
from app.services.embeddings.openai_compatible import OpenAICompatibleEmbeddingService
from app.services.embeddings.observability import (
    embed_with_observability,
    ensure_embedding_external_allowed,
)
from app.models import AuditLog, ModelCallLog
from app.services.llm.prompt_runtime import (
    PromptRuntime,
    execute_runtime_chat,
    get_runtime_llm_service,
    prepare_model_input,
)
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


def test_api_key_resolution_strips_shell_and_env_file_whitespace(monkeypatch) -> None:
    """A trailing newline used to become an illegal Authorization header.

    ``export KEY=$(cat key.txt)`` and CRLF ``.env`` files both leave whitespace
    on the value; the provider client then failed with an opaque HTTP 500
    instead of reporting a usable configuration error.
    """

    monkeypatch.setenv("TEST_ONLY_TRIMMED_KEY", "  test-key-value\r\n")
    assert providers.resolve_api_key("TEST_ONLY_TRIMMED_KEY") == "test-key-value"

    monkeypatch.setenv("TEST_ONLY_QUOTED_KEY", '"test-key-value"')
    assert providers.resolve_api_key("TEST_ONLY_QUOTED_KEY") == "test-key-value"

    monkeypatch.setenv("TEST_ONLY_BLANK_KEY", "   ")
    assert providers.resolve_api_key("TEST_ONLY_BLANK_KEY") == ""


def test_named_profile_api_key_loads_from_backend_dotenv_regardless_of_cwd(monkeypatch, tmp_path: Path) -> None:
    """The secret lookup must share Settings' stable backend/.env location."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PROFILE_DOTENV_KEY", raising=False)
    env_file = tmp_path / "backend" / ".env"
    env_file.parent.mkdir()
    env_file.write_text("PROFILE_DOTENV_KEY=dotenv-test-value\n", encoding="utf-8")
    monkeypatch.setattr(providers, "_BACKEND_ENV_FILE", env_file, raising=False)

    service = get_llm_service(
        provider="openai_compatible",
        base_url="https://provider.example.com/v1",
        api_key_env_name="PROFILE_DOTENV_KEY",
        model="example-model",
    )

    assert service.api_key == "dotenv-test-value"


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
            raise LLMProviderError(
                "Model provider request failed",
                error_type="provider_error",
                http_status=503,
                detail="HTTP 503: upstream unavailable for 13800138000",
            )

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
    monkeypatch.setattr(
        "app.services.llm.prompt_runtime.get_runtime_llm_service",
        lambda _, **__: FailingService(),
    )
    sensitive_prompt = "customer-data literal-secret-value"

    with pytest.raises(LLMProviderError):
        await execute_runtime_chat(db_session, 1, runtime, sensitive_prompt, ConnectionResult)

    log = db_session.query(ModelCallLog).one()
    assert log.status == "failed"
    assert log.error_type == "provider_error"
    assert log.provider == "openai_compatible"
    assert log.http_status == 503
    assert log.error_detail is not None and log.error_detail.startswith("HTTP 503: upstream unavailable")
    assert "13800138000" not in log.error_detail
    serialized = f"{log.input_summary} {log.output_summary}"
    assert sensitive_prompt not in serialized
    assert "literal-secret-value" not in serialized


@pytest.mark.asyncio
async def test_provider_http_failure_keeps_status_and_redacted_body() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "unsupported parameter: max_completion_tokens",
                    "contact": "13800138000",
                }
            },
        )

    service = OpenAICompatibleLLMService(
        base_url="https://provider.example.com/v1",
        api_key="test-only",
        model="example-model",
        provider="openai_compatible",
        retry_count=2,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LLMProviderError) as captured:
        await service.chat_json("system", "user")

    error = captured.value
    assert error.error_type == "provider_error"
    assert error.http_status == 400
    assert error.detail is not None and error.detail.startswith("HTTP 400: ")
    assert "unsupported parameter" in error.detail
    assert "13800138000" not in error.detail
    assert service.last_call.http_status == 400


def test_provider_error_detail_is_single_line_redacted_and_bounded() -> None:
    assert sanitize_provider_error_detail(None) is None
    assert sanitize_provider_error_detail("  \n\t ") is None

    raw = "first\nsecond\tpassword=hunter2 13800138000 " + "z" * (MAX_ERROR_DETAIL_CHARS + 200)
    detail = sanitize_provider_error_detail(raw)

    assert detail is not None
    assert "\n" not in detail and "\t" not in detail
    assert len(detail) == MAX_ERROR_DETAIL_CHARS
    assert "hunter2" not in detail
    assert "13800138000" not in detail


@pytest.mark.asyncio
async def test_model_outage_falls_back_to_the_next_configured_model() -> None:
    models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        models.append(model)
        if model == "primary-model":
            return httpx.Response(
                400,
                json={"error": {"message": "unknown provider for model primary-model", "code": "model_not_found"}},
            )
        return _response('{"status":"ok","message":"fallback answered"}')

    service = OpenAICompatibleLLMService(
        base_url="https://provider.example.com/v1",
        api_key="test-only",
        model="primary-model",
        provider="openai_compatible",
        retry_count=2,
        fallback_models=["primary-model", "fallback-model"],
        transport=httpx.MockTransport(handler),
    )

    result = await service.chat_structured("system", "user", ConnectionResult)

    assert result.message == "fallback answered"
    assert models == ["primary-model", "fallback-model"]
    assert service.last_call.model == "fallback-model"
    assert service.last_call.http_status == 200


@pytest.mark.asyncio
async def test_bad_request_without_model_marker_never_tries_the_fallback() -> None:
    models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        models.append(json.loads(request.content)["model"])
        return httpx.Response(400, json={"error": {"message": "unsupported parameter: max_completion_tokens"}})

    service = OpenAICompatibleLLMService(
        base_url="https://provider.example.com/v1",
        api_key="test-only",
        model="primary-model",
        provider="openai_compatible",
        retry_count=2,
        fallback_models=["fallback-model"],
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LLMProviderError) as captured:
        await service.chat_json("system", "user")

    assert models == ["primary-model"]
    assert captured.value.http_status == 400
    assert "unsupported parameter" in (captured.value.detail or "")


@pytest.mark.asyncio
async def test_single_model_configuration_retries_a_transient_model_outage() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                400,
                json={"error": {"message": "unknown provider for model primary-model", "code": "model_not_found"}},
            )
        return _response('{"status":"ok","message":"retry answered"}')

    async def no_sleep(_: float) -> None:
        return None

    service = OpenAICompatibleLLMService(
        base_url="https://provider.example.com/v1",
        api_key="test-only",
        model="primary-model",
        provider="openai_compatible",
        retry_count=2,
        transport=httpx.MockTransport(handler),
        sleep_func=no_sleep,
    )

    result = await service.chat_structured("system", "user", ConnectionResult)

    assert result.message == "retry answered"
    assert attempts == 2
    assert service.last_call.http_status == 200


@pytest.mark.asyncio
async def test_exhausted_model_chain_reports_every_attempted_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        return httpx.Response(
            400,
            json={"error": {"message": f"unknown provider for model {model}", "code": "model_not_found"}},
        )

    service = OpenAICompatibleLLMService(
        base_url="https://provider.example.com/v1",
        api_key="test-only",
        model="primary-model",
        provider="openai_compatible",
        retry_count=2,
        fallback_models=["fallback-model"],
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LLMProviderError) as captured:
        await service.chat_json("system", "user")

    detail = captured.value.detail or ""
    assert captured.value.http_status == 400
    assert "fallback chain exhausted: primary-model, fallback-model" in detail
    assert "model_not_found" in detail


@pytest.mark.asyncio
async def test_provider_quota_exhaustion_moves_to_the_fallback_provider() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "primary.example.com" in str(request.url):
            return httpx.Response(
                403,
                json={"error": {"message": "status 403", "code": "insufficient_quota"}},
            )
        return _response('{"status":"ok","message":"secondary provider answered"}')

    service = OpenAICompatibleLLMService(
        base_url="https://primary.example.com/v1",
        api_key="primary-key",
        model="primary-model",
        provider="openai_compatible",
        retry_count=0,
        fallback_models=["deepseek-chat"],
        fallback_base_url="https://secondary.example.net/v1",
        fallback_api_key="secondary-key",
        transport=httpx.MockTransport(handler),
    )

    result = await service.chat_structured("system", "user", ConnectionResult)

    assert result.message == "secondary provider answered"
    assert service.last_call.model == "deepseek-chat"


@pytest.mark.asyncio
async def test_gateway_timeout_status_is_retried_on_the_same_model() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(524, text="A timeout occurred")
        return _response('{"status":"ok","message":"retry answered"}')

    async def no_sleep(_: float) -> None:
        return None

    service = OpenAICompatibleLLMService(
        base_url="https://provider.example.com/v1",
        api_key="test-only",
        model="primary-model",
        provider="openai_compatible",
        retry_count=2,
        transport=httpx.MockTransport(handler),
        sleep_func=no_sleep,
    )

    result = await service.chat_structured("system", "user", ConnectionResult)

    assert result.message == "retry answered"
    assert attempts == 2


@pytest.mark.asyncio
async def test_fallback_can_target_a_separate_endpoint_and_key() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("authorization", "")))
        if "primary.example.com" in str(request.url):
            return httpx.Response(404, json={"error": {"message": "model not found"}})
        return _response('{"status":"ok","message":"domestic model answered"}')

    service = OpenAICompatibleLLMService(
        base_url="https://primary.example.com/v1",
        api_key="primary-key",
        provider="openai_compatible",
        model="primary-model",
        fallback_models=["deepseek-chat"],
        fallback_base_url="https://fallback.example.net/v1",
        fallback_api_key="domestic-key",
        fallback_api_key_env_name="DEEPSEEK_API_KEY",
        transport=httpx.MockTransport(handler),
    )

    result = await service.chat_structured("system", "user", ConnectionResult)

    assert result.message == "domestic model answered"
    assert [url for url, _ in seen] == [
        "https://primary.example.com/v1/chat/completions",
        "https://fallback.example.net/v1/chat/completions",
    ]
    assert [header for _, header in seen] == ["Bearer primary-key", "Bearer domestic-key"]
    assert service.last_call.model == "deepseek-chat"


def test_factory_wires_the_fallback_chain_from_settings(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://provider.example.com/v1")
    monkeypatch.setenv("LLM_MODEL", "primary-model")
    monkeypatch.setenv("LLM_API_KEY_ENV_NAME", "FALLBACK_PRIMARY_KEY")
    monkeypatch.setenv("FALLBACK_PRIMARY_KEY", "primary-key")
    monkeypatch.setenv("LLM_FALLBACK_MODELS", "fallback-one, ,fallback-two;primary-model")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://fallback.example.net/v1")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY_ENV_NAME", "FALLBACK_SECONDARY_KEY")
    monkeypatch.setenv("FALLBACK_SECONDARY_KEY", "domestic-key")
    get_settings.cache_clear()
    try:
        service = get_llm_service()
    finally:
        get_settings.cache_clear()

    assert service.fallback_models == ["fallback-one", "fallback-two"]
    assert service.fallback_base_url == "https://fallback.example.net/v1"
    assert service.fallback_api_key == "domestic-key"
    assert service.fallback_api_key_env_name == "FALLBACK_SECONDARY_KEY"


@pytest.mark.asyncio
async def test_json_mode_instruction_is_added_only_when_the_prompt_omits_it() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _response('{"status":"ok","message":"connection ok"}')

    service = OpenAICompatibleLLMService(
        base_url="https://provider.example.com/v1",
        api_key="test-only",
        model="example-model",
        provider="openai_compatible",
        transport=httpx.MockTransport(handler),
    )

    await service.chat_json("business assistant", "explain this field")
    assert bodies[0]["response_format"] == {"type": "json_object"}
    assert "Return exactly one json object" in bodies[0]["messages"][0]["content"]

    await service.chat_json("Return JSON only", "explain this field")
    assert bodies[1]["messages"][0]["content"] == "Return JSON only"

    plain = OpenAICompatibleLLMService(
        base_url="https://provider.example.com/v1",
        api_key="test-only",
        model="example-model",
        provider="openai_compatible",
        json_mode=False,
        transport=httpx.MockTransport(handler),
    )
    await plain.chat_json("business assistant", "explain this field")
    assert bodies[2]["messages"][0]["content"] == "business assistant"
    assert "response_format" not in bodies[2]


def test_factory_uses_the_configured_provider_timeout(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://provider.example.com/v1")
    monkeypatch.setenv("LLM_MODEL", "primary-model")
    monkeypatch.setenv("LLM_API_KEY_ENV_NAME", "TIMEOUT_TEST_KEY")
    monkeypatch.setenv("TIMEOUT_TEST_KEY", "test-only")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "180")
    get_settings.cache_clear()
    try:
        service = get_llm_service()
    finally:
        get_settings.cache_clear()

    assert service.timeout_seconds == 180


def test_interactive_calls_use_their_own_budget_and_single_retry(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://provider.example.com/v1")
    monkeypatch.setenv("LLM_MODEL", "primary-model")
    monkeypatch.setenv("LLM_API_KEY_ENV_NAME", "INTERACTIVE_TIMEOUT_KEY")
    monkeypatch.setenv("INTERACTIVE_TIMEOUT_KEY", "test-only")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "180")
    monkeypatch.setenv("LLM_INTERACTIVE_TIMEOUT_SECONDS", "25")
    get_settings.cache_clear()
    try:
        background = get_llm_service()
        interactive = get_interactive_llm_service()
    finally:
        get_settings.cache_clear()

    # Generation jobs keep the long budget; a request-thread call answers
    # inside its own shorter window with a single retry.
    assert background.timeout_seconds == 180
    assert background.retry_count == 2
    assert interactive.timeout_seconds == 25
    assert interactive.retry_count == 1


def test_grounded_qa_uses_the_interactive_budget_without_doubling_it(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://provider.example.com/v1")
    monkeypatch.setenv("LLM_MODEL", "primary-model")
    monkeypatch.setenv("LLM_API_KEY_ENV_NAME", "INTERACTIVE_TIMEOUT_KEY")
    monkeypatch.setenv("INTERACTIVE_TIMEOUT_KEY", "test-only")
    monkeypatch.setenv("LLM_INTERACTIVE_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "180")
    get_settings.cache_clear()
    runtime = PromptRuntime(
        prompt_key="regulatory_field_explanation",
        version=1,
        system_prompt="system",
        user_template="",
        model_profile_id=None,
        provider_type="openai_compatible",
        base_url=None,
        model_name=None,
        api_key_env_name=None,
        local_only=False,
        config={},
    )
    try:
        interactive = get_runtime_llm_service(runtime, interactive=True)
        background = get_runtime_llm_service(runtime)
    finally:
        get_settings.cache_clear()

    # Degrading callers must not silently double their worst-case wait.
    assert interactive.timeout_seconds == 30
    assert interactive.retry_count == 0
    assert background.timeout_seconds == 180
    assert background.retry_count == 2


def test_interactive_timeout_rejects_out_of_range_values() -> None:
    settings = Settings(_env_file=None, llm_interactive_timeout_seconds=0)
    codes = {
        item["code"]
        for item in settings.validate_configuration()
        if item["severity"] == "error"
    }

    assert "llm_interactive_timeout_invalid" in codes


@pytest.mark.asyncio
async def test_provider_timeout_is_reported_as_a_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    service = OpenAICompatibleLLMService(
        base_url="https://provider.example.com/v1",
        api_key="test-only",
        model="slow-model",
        provider="openai_compatible",
        timeout_seconds=7,
        retry_count=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LLMProviderError) as excinfo:
        await service.chat_structured("system", "user", ConnectionResult)

    # The interactive degradation keys off this error type, so a timeout must
    # be distinguishable from a transport failure.
    assert excinfo.value.error_type == "timeout"
    assert "7s" in str(excinfo.value)


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
    # The production stack reads the private, git-ignored root ``.env``; the
    # checked-in ``.env.production.example`` is documentation only and must
    # never be wired into a service.
    assert ".env.production.example" not in compose
    assert compose.count("./.env") >= 2


def test_docker_contexts_exclude_host_build_artifacts() -> None:
    root = Path(__file__).parents[2]
    frontend = root / "frontend"
    dockerignore = (frontend / ".dockerignore").read_text(encoding="utf-8").splitlines()
    dockerfile = (frontend / "Dockerfile").read_text(encoding="utf-8")
    backend_dockerignore = (root / "backend" / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert "node_modules/" in dockerignore
    assert ".next/" in dockerignore
    assert ".env.*" in dockerignore
    assert "RUN npm ci" in dockerfile
    assert ".venv/" in backend_dockerignore
    assert "dev_storage*/" in backend_dockerignore
    assert "/backend/dev_storage*/" in (root / ".gitignore").read_text(encoding="utf-8").splitlines()


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
