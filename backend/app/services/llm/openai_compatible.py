import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.services.llm.base import (
    LLMProviderError,
    LLMResponseError,
    LLMService,
    ModelCallMetadata,
    StructuredResponse,
)
from app.services.llm.providers import ProviderRuntimeConfig, normalize_provider_type


RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504, 524}
# Relays answer 403/429 with a body that names the real cause: the upstream is
# out of quota, overloaded, or rate limiting us.  Those are availability
# problems, so a second provider in the fallback chain can still answer.
PROVIDER_BUSY_MARKERS = (
    "insufficient_quota",
    "quota",
    "rate limit",
    "rate_limit",
    "too many requests",
    "overloaded",
    "capacity",
)
CHAT_COMPLETIONS_PATH = "/chat/completions"
# A relay that lists a model but answers ``400 model_not_found`` (or a plain
# 404) is having a routing hiccup, not rejecting our request body.  Those
# markers are the only 400-class failures worth retrying on another model.
MODEL_UNAVAILABLE_MARKERS = (
    "model_not_found",
    "unknown provider for model",
    "does not exist",
    "invalid model",
    "no such model",
    "model is not available",
    "model not found",
)
# OpenAI-compatible gateways enforce the documented rule that the word "json"
# must appear in the messages when ``response_format=json_object`` is sent.
# Prompts that never spell it out are rejected with HTTP 400 before the model
# runs, which is how a correct prompt could still fail on a real provider.
JSON_MODE_INSTRUCTION = (
    "Return exactly one json object that matches the requested schema; "
    "no markdown fences and no commentary."
)


class OpenAICompatibleLLMService(LLMService):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        embedding_model: str | None = None,
        *,
        provider: str = "openai_compatible",
        api_key_env_name: str | None = None,
        json_mode: bool = True,
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
        timeout_seconds: float = 60,
        retry_count: int = 2,
        fallback_models: list[str] | None = None,
        fallback_base_url: str | None = None,
        fallback_api_key: str | None = None,
        fallback_api_key_env_name: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.provider = normalize_provider_type(provider)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_key_env_name = api_key_env_name
        self.model = model
        self.embedding_model = embedding_model or model
        self.json_mode = json_mode
        self.temperature = min(max(float(temperature), 0), 2)
        self.max_output_tokens = min(max(int(max_output_tokens), 1), 8192)
        self.timeout_seconds = min(max(float(timeout_seconds), 1), 180)
        self.retry_count = min(max(int(retry_count), 0), 2)
        self.fallback_models = _dedupe_models(fallback_models or [], primary=self.model)
        self.fallback_base_url = (fallback_base_url or "").rstrip("/")
        self.fallback_api_key = fallback_api_key
        self.fallback_api_key_env_name = fallback_api_key_env_name
        self.transport = transport
        self.sleep_func = sleep_func
        self.last_call = ModelCallMetadata(provider=self.provider, model=self.model)

    def _validate(self) -> None:
        for target in self._targets():
            ProviderRuntimeConfig(
                provider=self.provider,
                base_url=target["base_url"],
                model=target["model"],
                api_key_env_name=target["api_key_env_name"],
                api_key=target["api_key"],
                local_only=self.provider.startswith("local_"),
            ).validate()

    def _targets(self) -> list[dict[str, Any]]:
        """Primary endpoint first, then every configured fallback model."""

        targets: list[dict[str, Any]] = [
            {
                "base_url": self.base_url,
                "api_key": self.api_key,
                "api_key_env_name": self.api_key_env_name,
                "model": self.model,
            }
        ]
        for model in self.fallback_models:
            targets.append(
                {
                    "base_url": self.fallback_base_url or self.base_url,
                    "api_key": self.fallback_api_key if self.fallback_api_key else self.api_key,
                    "api_key_env_name": self.fallback_api_key_env_name or self.api_key_env_name,
                    "model": model,
                }
            )
        return targets

    async def chat_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        return await self._chat_and_parse(system_prompt, user_prompt)

    async def chat_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[StructuredResponse],
    ) -> StructuredResponse:
        invalid_response = ""
        try:
            payload = await self._chat_and_parse(system_prompt, user_prompt)
            invalid_response = json.dumps(payload, ensure_ascii=False)
            return response_schema.model_validate(payload)
        except (LLMResponseError, ValidationError) as first_error:
            first_metadata = _copy_metadata(self.last_call)
            if isinstance(first_error, LLMResponseError) and first_error.raw_response:
                invalid_response = first_error.raw_response
            repair_prompt = (
                "Return one JSON object that conforms exactly to this JSON Schema. "
                "Do not add commentary or markdown.\n"
                f"Schema: {json.dumps(response_schema.model_json_schema(), ensure_ascii=False)}\n"
                f"Invalid response: {invalid_response[:10000] or 'invalid JSON output'}"
            )
            try:
                repaired = await self._chat_and_parse(
                    "You repair JSON formatting. Return only the corrected JSON object.",
                    repair_prompt,
                )
                validated = response_schema.model_validate(repaired)
                self.last_call = _merge_metadata(first_metadata, self.last_call)
                return validated
            except (LLMResponseError, ValidationError) as exc:
                self.last_call = _merge_metadata(first_metadata, self.last_call)
                raise LLMResponseError("Model did not return valid JSON matching the required schema") from exc

    async def _chat_and_parse(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        self._validate()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        if self.json_mode and "json" not in f"{system_prompt}\n{user_prompt}".lower():
            messages[0]["content"] = f"{system_prompt}\n{JSON_MODE_INSTRUCTION}".strip()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_output_tokens,
        }
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        response = await self._post("/chat/completions", payload)
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("Provider response did not contain a chat completion") from exc
        if not isinstance(content, str):
            raise LLMResponseError("Provider chat completion content was not text")
        content = _strip_json_fence(content)
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMResponseError("Provider response was not valid JSON", raw_response=content) from exc
        if not isinstance(parsed, dict):
            raise LLMResponseError("Provider response JSON must be an object")
        return parsed

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self._validate()
        response = await self._post(
            "/embeddings",
            {"model": self.embedding_model, "input": texts},
        )
        try:
            vectors = [item["embedding"] for item in response.json()["data"]]
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMResponseError("Provider response did not contain embeddings") from exc
        if not all(vector and all(isinstance(value, (int, float)) for value in vector) for vector in vectors):
            raise LLMResponseError("Provider returned an invalid embedding vector")
        return vectors

    async def _post(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        """Send one request, walking the fallback chain only for model outages.

        ``HTTP 400 model_not_found`` from a relay that still lists the model is
        a routing hiccup rather than a bad request, and it used to abort the
        whole business flow.  The identical payload is therefore replayed
        against the next configured fallback model before giving up.
        """

        fallback_capable = path == CHAT_COMPLETIONS_PATH
        targets = self._targets() if fallback_capable else self._targets()[:1]
        unavailable: list[str] = []
        for index, target in enumerate(targets):
            request_payload = {**payload, "model": target["model"]} if fallback_capable else payload
            try:
                # With no fallback configured a transient ``model_not_found`` is
                # retried against the same model; with a chain configured the
                # next model answers instead of burning time on the outage.
                return await self._post_once(
                    target,
                    path,
                    request_payload,
                    retry_model_outage=len(targets) == 1,
                )
            except LLMProviderError as exc:
                model = str(target["model"])
                if not _is_provider_unavailable(exc):
                    if unavailable:
                        raise _exhausted_chain_error([*unavailable, model], exc) from exc
                    raise
                unavailable.append(model)
                if index + 1 >= len(targets):
                    if len(targets) == 1:
                        raise
                    raise _exhausted_chain_error(unavailable, exc) from exc
        raise AssertionError("fallback loop must return or raise")  # pragma: no cover

    async def _post_once(
        self,
        target: dict[str, Any],
        path: str,
        payload: dict[str, Any],
        *,
        retry_model_outage: bool = False,
    ) -> httpx.Response:
        api_key = str(target["api_key"] or "")
        base_url = str(target["base_url"]).rstrip("/")
        model = str(target["model"])
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        started = time.perf_counter()
        attempts = 0
        while True:
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds,
                    transport=self.transport,
                    follow_redirects=False,
                    trust_env=False,
                ) as client:
                    response = await client.post(
                        f"{base_url}{path}",
                        json=payload,
                        headers=headers,
                    )
                self.last_call.http_status = response.status_code
                if response.status_code >= 400:
                    error = _http_error(response.status_code, response)
                    retryable = response.status_code in RETRYABLE_STATUS_CODES or (
                        retry_model_outage and _is_transient_model_outage(error)
                    )
                    if retryable and attempts < self.retry_count:
                        attempts += 1
                        await self.sleep_func(0.1 * (2 ** (attempts - 1)))
                        continue
                    raise error
                self.last_call = ModelCallMetadata(
                    provider=self.provider,
                    model=model,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    token_usage=_usage(response),
                    retry_count=attempts,
                    http_status=response.status_code,
                )
                return response
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempts < self.retry_count:
                    attempts += 1
                    await self.sleep_func(0.1 * (2 ** (attempts - 1)))
                    continue
                self.last_call = ModelCallMetadata(
                    provider=self.provider,
                    model=model,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    retry_count=attempts,
                )
                # A timeout is reported separately from a transport failure so
                # interactive callers can degrade to "generation is slow"
                # instead of a generic dependency error.
                if isinstance(exc, httpx.TimeoutException):
                    raise LLMProviderError(
                        f"Model provider call exceeded {self.timeout_seconds:g}s",
                        error_type="timeout",
                        detail=f"{type(exc).__name__}: {exc}",
                    ) from exc
                raise LLMProviderError(
                    "Model provider network request failed after bounded retries",
                    error_type="network_error",
                    detail=f"{type(exc).__name__}: {exc}",
                ) from exc
            finally:
                self.last_call.retry_count = attempts
                self.last_call.latency_ms = int((time.perf_counter() - started) * 1000)


def _dedupe_models(models: list[str], *, primary: str) -> list[str]:
    """Keep the declared fallback order, drop blanks and the primary model."""

    seen = {primary.strip()}
    ordered: list[str] = []
    for raw in models:
        candidate = str(raw).strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        ordered.append(candidate)
    return ordered


def _is_model_unavailable(error: LLMProviderError) -> bool:
    """True when the provider says the *model* is missing, not the request."""

    if error.error_type == "not_found":
        return True
    return _is_transient_model_outage(error)


def _is_provider_unavailable(error: LLMProviderError) -> bool:
    """True when another configured target has a realistic chance to answer."""

    if _is_model_unavailable(error):
        return True
    if error.http_status in RETRYABLE_STATUS_CODES:
        return True
    if error.http_status in {403, 429}:
        detail = (error.detail or "").lower()
        return any(marker in detail for marker in PROVIDER_BUSY_MARKERS)
    return False


def _is_transient_model_outage(error: LLMProviderError) -> bool:
    """True for ``400 model_not_found`` answers, which are usually routing blips."""

    if error.http_status != 400:
        return False
    detail = (error.detail or "").lower()
    return any(marker in detail for marker in MODEL_UNAVAILABLE_MARKERS)


def _exhausted_chain_error(models: list[str], error: LLMProviderError) -> LLMProviderError:
    """Report every model that was tried before the call finally failed."""

    detail = f"fallback chain exhausted: {', '.join(models)}"
    if error.detail:
        detail = f"{detail}; last error: {error.detail}"
    return LLMProviderError(
        str(error),
        error_type=error.error_type,
        http_status=error.http_status,
        detail=detail,
    )


def _strip_json_fence(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```json\n") and stripped.endswith("\n```"):
        return stripped[len("```json\n") : -len("\n```")].strip()
    if stripped.startswith("```\n") and stripped.endswith("\n```"):
        return stripped[len("```\n") : -len("\n```")].strip()
    return stripped


def _usage(response: httpx.Response) -> dict[str, Any]:
    try:
        usage = response.json().get("usage")
    except ValueError:
        usage = None
    if not isinstance(usage, dict):
        return {"usage_available": False}
    details = usage.get("prompt_tokens_details") or {}
    return {
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "cached_tokens": details.get("cached_tokens", 0),
        "usage_available": True,
    }


def _copy_metadata(metadata: ModelCallMetadata) -> ModelCallMetadata:
    return ModelCallMetadata(
        provider=metadata.provider,
        model=metadata.model,
        latency_ms=metadata.latency_ms,
        token_usage=dict(metadata.token_usage),
        retry_count=metadata.retry_count,
        http_status=metadata.http_status,
    )


def _merge_metadata(first: ModelCallMetadata, second: ModelCallMetadata) -> ModelCallMetadata:
    first_usage = first.token_usage
    second_usage = second.token_usage
    usage_available = bool(first_usage.get("usage_available")) and bool(second_usage.get("usage_available"))
    usage: dict[str, Any] = {"usage_available": usage_available}
    if usage_available:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens"):
            usage[key] = int(first_usage.get(key, 0)) + int(second_usage.get(key, 0))
    return ModelCallMetadata(
        provider=second.provider,
        model=second.model,
        latency_ms=first.latency_ms + second.latency_ms,
        token_usage=usage,
        retry_count=first.retry_count + second.retry_count,
        http_status=second.http_status,
    )


def _http_error(status_code: int, response: httpx.Response | None = None) -> LLMProviderError:
    if status_code in {401, 403}:
        message, error_type = "Model provider authentication failed", "authentication_error"
    elif status_code == 404:
        message, error_type = "Model endpoint or model was not found; check Base URL and model name", "not_found"
    elif status_code == 429:
        message, error_type = "Model provider quota or rate limit was exceeded", "rate_limit"
    else:
        message, error_type = "Model provider request failed", "provider_error"
    return LLMProviderError(
        message,
        error_type=error_type,
        http_status=status_code,
        detail=_error_body(response),
    )


def _error_body(response: httpx.Response | None) -> str | None:
    """Return the provider's own error payload so failures stay diagnosable.

    Without this the caller only ever saw ``provider_error``; distinguishing a
    malformed request (400) from a quota problem (429) or a model-side outage
    (5xx) required guessing.  The body is trimmed and redacted later.
    """

    if response is None:
        return None
    try:
        text = response.text
    except Exception:  # pragma: no cover - defensive: httpx already buffered
        return None
    if not text:
        return None
    return f"HTTP {response.status_code}: {text}"
