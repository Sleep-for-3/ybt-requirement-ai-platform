import math
import time

import httpx

from app.services.llm.base import LLMProviderError, LLMResponseError, ModelCallMetadata
from app.services.llm.openai_compatible import RETRYABLE_STATUS_CODES, _http_error, _usage
from app.services.llm.providers import (
    ProviderRuntimeConfig,
    is_local_provider,
    normalize_provider_type,
    resolve_api_key,
)
from app.services.embeddings.base import EmbeddingBatchResult


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

    def embed_documents(self, texts: list[str]) -> EmbeddingBatchResult:
        return self._embed(texts, input_type="document")

    def _embed(self, texts: list[str], *, input_type: str) -> EmbeddingBatchResult:
        if not texts:
            return EmbeddingBatchResult(
                vectors=[],
                provider=self.provider,
                model=self.model,
                dimension=0,
                latency_ms=0,
            )
        api_key = resolve_api_key(self.api_key_env_name)
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
        batch_count = 0
        for offset in range(0, len(texts), self.batch_size):
            batch_texts = texts[offset : offset + self.batch_size]
            response, batch_retries = self._post(batch_texts, api_key, input_type=input_type)
            retries += batch_retries
            batch_count += 1
            try:
                data = response.json()["data"]
                ordered = sorted(data, key=lambda item: int(item.get("index", 0)))
                batch_vectors = [item["embedding"] for item in ordered]
            except (ValueError, KeyError, TypeError) as exc:
                raise LLMResponseError("Provider response did not contain embeddings") from exc
            _validate_vectors(batch_vectors, expected_count=len(batch_texts))
            if vectors and len(batch_vectors[0]) != len(vectors[0]):
                raise LLMResponseError("Provider changed embedding dimension between batches")
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
        return EmbeddingBatchResult(
            vectors=vectors,
            provider=self.provider,
            model=self.model,
            dimension=len(vectors[0]),
            latency_ms=self.last_call.latency_ms,
            token_usage=self.last_call.token_usage,
            batch_count=batch_count,
            retry_count=retries,
        )

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts).vectors

    def _post(
        self,
        texts: list[str],
        key: str,
        *,
        input_type: str,
    ) -> tuple[httpx.Response, int]:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        payload = {"model": self.model, "input": texts}
        if self.local_only:
            # Keep the JSON body compatible with standard local vLLM/Ollama
            # endpoints. The bundled lightweight server reads this optional
            # query/document hint, while other servers safely ignore it.
            headers["X-YBT-Embedding-Input-Type"] = input_type
        attempts = 0
        while True:
            try:
                if self.transport is None:
                    response = httpx.post(
                        f"{self.base_url}/embeddings",
                        json=payload,
                        headers=headers,
                        timeout=self.timeout_seconds,
                        follow_redirects=False,
                    )
                else:
                    with httpx.Client(timeout=self.timeout_seconds, transport=self.transport, follow_redirects=False, trust_env=False) as client:
                        response = client.post(
                            f"{self.base_url}/embeddings",
                            json=payload,
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
        return self._embed([text], input_type="query").vectors[0]


class LocalEmbeddingService(OpenAICompatibleEmbeddingService):
    def __init__(self, base_url: str, model: str, api_key_env_name: str, **kwargs) -> None:
        provider = kwargs.pop("provider", "local_vllm")
        super().__init__(base_url, model, api_key_env_name, provider=provider, **kwargs)


def _validate_vectors(vectors: list[list[float]], *, expected_count: int) -> None:
    if len(vectors) != expected_count or not vectors:
        raise LLMResponseError("Provider returned a different number of embeddings than inputs")
    dimension = len(vectors[0])
    if dimension <= 0:
        raise LLMResponseError("Provider returned an empty embedding vector")
    for vector in vectors:
        if len(vector) != dimension:
            raise LLMResponseError("Provider returned inconsistent embedding dimensions")
        if not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            for value in vector
        ):
            raise LLMResponseError("Provider returned a non-numeric or non-finite embedding value")
