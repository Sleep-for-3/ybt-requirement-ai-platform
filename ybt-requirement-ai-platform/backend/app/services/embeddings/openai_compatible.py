import os
import time

import httpx

from app.services.llm.base import LLMProviderError, LLMResponseError, ModelCallMetadata
from app.services.llm.openai_compatible import RETRYABLE_STATUS_CODES, _http_error, _usage
from app.services.llm.providers import ProviderRuntimeConfig, is_local_provider, normalize_provider_type


class OpenAICompatibleEmbeddingService:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key_env_name: str,
        *,
        provider: str = "openai_compatible",
        timeout_seconds: float = 60,
        retry_count: int = 2,
        batch_size: int = 64,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.provider = normalize_provider_type(provider)
        self.local_only = is_local_provider(self.provider)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_env_name = api_key_env_name
        self.timeout_seconds = min(max(float(timeout_seconds), 1), 180)
        self.retry_count = min(max(int(retry_count), 0), 2)
        self.batch_size = min(max(int(batch_size), 1), 256)
        self.transport = transport
        self.last_call = ModelCallMetadata(provider=self.provider, model=self.model)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        api_key = os.getenv(self.api_key_env_name, "")
        ProviderRuntimeConfig(
            provider=self.provider,
            base_url=self.base_url,
            model=self.model,
            api_key_env_name=self.api_key_env_name,
            api_key=api_key,
            local_only=self.local_only,
        ).validate()
        vectors: list[list[float]] = []
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cached_tokens": 0}
        usage_available = True
        started = time.perf_counter()
        retries = 0
        for offset in range(0, len(texts), self.batch_size):
            response, batch_retries = self._post(texts[offset : offset + self.batch_size], api_key)
            retries += batch_retries
            try:
                batch_vectors = [item["embedding"] for item in response.json()["data"]]
            except (ValueError, KeyError, TypeError) as exc:
                raise LLMResponseError("Provider response did not contain embeddings") from exc
            if not batch_vectors or not all(
                vector and all(isinstance(value, (int, float)) for value in vector)
                for vector in batch_vectors
            ):
                raise LLMResponseError("Provider returned an invalid embedding vector")
            vectors.extend(batch_vectors)
            usage = _usage(response)
            usage_available = usage_available and bool(usage.get("usage_available"))
            for key_name in total_usage:
                total_usage[key_name] += int(usage.get(key_name, 0))
        self.last_call = ModelCallMetadata(
            provider=self.provider,
            model=self.model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            token_usage={**total_usage, "usage_available": usage_available},
            retry_count=retries,
            http_status=200,
        )
        return vectors

    def _post(self, texts: list[str], key: str) -> tuple[httpx.Response, int]:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        attempts = 0
        while True:
            try:
                if self.transport is None:
                    response = httpx.post(
                        f"{self.base_url}/embeddings",
                        json={"model": self.model, "input": texts},
                        headers=headers,
                        timeout=self.timeout_seconds,
                        follow_redirects=False,
                    )
                else:
                    with httpx.Client(timeout=self.timeout_seconds, transport=self.transport, follow_redirects=False, trust_env=False) as client:
                        response = client.post(
                            f"{self.base_url}/embeddings",
                            json={"model": self.model, "input": texts},
                            headers=headers,
                        )
                if not hasattr(response, "status_code"):
                    response.raise_for_status()
                    return response, attempts
                if response.status_code < 400:
                    return response, attempts
                if response.status_code in RETRYABLE_STATUS_CODES and attempts < self.retry_count:
                    attempts += 1
                    continue
                raise _http_error(response.status_code)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempts < self.retry_count:
                    attempts += 1
                    continue
                raise LLMProviderError(
                    "Embedding provider network request failed after bounded retries",
                    error_type="network_error",
                ) from exc

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]


class LocalEmbeddingService(OpenAICompatibleEmbeddingService):
    def __init__(self, base_url: str, model: str, api_key_env_name: str, **kwargs) -> None:
        provider = kwargs.pop("provider", "local_vllm")
        super().__init__(base_url, model, api_key_env_name, provider=provider, **kwargs)
