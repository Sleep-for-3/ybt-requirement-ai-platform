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


RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


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
        self.transport = transport
        self.sleep_func = sleep_func
        self.last_call = ModelCallMetadata(provider=self.provider, model=self.model)

    def _validate(self) -> None:
        ProviderRuntimeConfig(
            provider=self.provider,
            base_url=self.base_url,
            model=self.model,
            api_key_env_name=self.api_key_env_name,
            api_key=self.api_key,
            local_only=self.provider.startswith("local_"),
        ).validate()

    async def chat_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        return await self._chat_and_parse(system_prompt, user_prompt)

    async def chat_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[StructuredResponse],
    ) -> StructuredResponse:
        try:
            payload = await self._chat_and_parse(system_prompt, user_prompt)
            return response_schema.model_validate(payload)
        except (LLMResponseError, ValidationError) as first_error:
            repair_prompt = (
                "Return one JSON object that conforms exactly to this JSON Schema. "
                "Do not add commentary or markdown.\n"
                f"Schema: {json.dumps(response_schema.model_json_schema(), ensure_ascii=False)}\n"
                f"Invalid response: {getattr(first_error, 'input', '') or 'invalid JSON output'}"
            )
            try:
                repaired = await self._chat_and_parse(
                    "You repair JSON formatting. Return only the corrected JSON object.",
                    repair_prompt,
                )
                return response_schema.model_validate(repaired)
            except (LLMResponseError, ValidationError) as exc:
                raise LLMResponseError("Model did not return valid JSON matching the required schema") from exc

    async def _chat_and_parse(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        self._validate()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
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
            raise LLMResponseError("Provider response was not valid JSON") from exc
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
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
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
                        f"{self.base_url}{path}",
                        json=payload,
                        headers=headers,
                    )
                self.last_call.http_status = response.status_code
                if response.status_code >= 400:
                    if response.status_code in RETRYABLE_STATUS_CODES and attempts < self.retry_count:
                        attempts += 1
                        await self.sleep_func(0.1 * (2 ** (attempts - 1)))
                        continue
                    raise _http_error(response.status_code)
                self.last_call = ModelCallMetadata(
                    provider=self.provider,
                    model=self.model,
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
                    model=self.model,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    retry_count=attempts,
                )
                raise LLMProviderError(
                    "Model provider network request failed after bounded retries",
                    error_type="network_error",
                ) from exc
            finally:
                self.last_call.retry_count = attempts
                self.last_call.latency_ms = int((time.perf_counter() - started) * 1000)


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


def _http_error(status_code: int) -> LLMProviderError:
    if status_code in {401, 403}:
        message, error_type = "Model provider authentication failed", "authentication_error"
    elif status_code == 404:
        message, error_type = "Model endpoint or model was not found; check Base URL and model name", "not_found"
    elif status_code == 429:
        message, error_type = "Model provider quota or rate limit was exceeded", "rate_limit"
    else:
        message, error_type = "Model provider request failed", "provider_error"
    return LLMProviderError(message, error_type=error_type, http_status=status_code)
