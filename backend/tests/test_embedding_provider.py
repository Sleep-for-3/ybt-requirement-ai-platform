import math

import httpx
import pytest

from app.services.embeddings.openai_compatible import OpenAICompatibleEmbeddingService
from app.services.llm.base import LLMProviderError, LLMResponseError


def _service(handler, *, batch_size=2, retry_count=2):
    return OpenAICompatibleEmbeddingService(
        "http://embedding.local/v1",
        "bge-test",
        "UNUSED_EMBEDDING_KEY",
        provider="local_vllm",
        batch_size=batch_size,
        retry_count=retry_count,
        transport=httpx.MockTransport(handler),
    )


def test_embedding_batches_preserve_input_order_and_report_runtime_metadata():
    requests: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        requests.append(payload["input"])
        data = [
            {"index": index, "embedding": [float(len(text)), float(index + 1)]}
            for index, text in enumerate(payload["input"])
        ]
        return httpx.Response(
            200,
            json={"data": list(reversed(data)), "usage": {"prompt_tokens": len(data), "total_tokens": len(data)}},
        )

    result = _service(handler).embed_documents(["甲", "乙乙", "丙丙丙"])

    assert requests == [["甲", "乙乙"], ["丙丙丙"]]
    assert result.vectors == [[1.0, 1.0], [2.0, 2.0], [3.0, 1.0]]
    assert result.provider == "local_vllm"
    assert result.model == "bge-test"
    assert result.dimension == 2
    assert result.batch_count == 2
    assert result.token_usage["total_tokens"] == 3
    assert result.latency_ms >= 0


@pytest.mark.parametrize(
    "data",
    [
        [{"index": 0, "embedding": [1.0, 2.0]}],
        [
            {"index": 0, "embedding": [1.0, 2.0]},
            {"index": 1, "embedding": [1.0]},
        ],
        [
            {"index": 0, "embedding": [1.0, math.nan]},
            {"index": 1, "embedding": [1.0, 2.0]},
        ],
    ],
)
def test_embedding_rejects_count_dimension_and_non_finite_errors(data):
    response_body = __import__("json").dumps({"data": data}, allow_nan=True).encode()
    service = _service(
        lambda request: httpx.Response(
            200,
            content=response_body,
            headers={"content-type": "application/json"},
        )
    )

    with pytest.raises(LLMResponseError):
        service.embed_documents(["第一段", "第二段"])


def test_embedding_retries_only_bounded_transient_failures():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})

    result = _service(handler).embed_documents(["文本"])
    assert result.vectors == [[1.0, 0.0]]
    assert result.retry_count == 2
    assert attempts == 3

    bad_request_attempts = 0

    def bad_request(request: httpx.Request) -> httpx.Response:
        nonlocal bad_request_attempts
        bad_request_attempts += 1
        return httpx.Response(400, json={"error": "invalid"})

    with pytest.raises(LLMProviderError):
        _service(bad_request).embed_documents(["文本"])
    assert bad_request_attempts == 1


@pytest.mark.parametrize("status_code", [401, 403, 404])
def test_embedding_auth_and_not_found_errors_are_never_retried(status_code):
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status_code, json={"error": "denied"})

    with pytest.raises(LLMProviderError):
        _service(handler).embed_documents(["文本"])
    assert attempts == 1


def test_embedding_timeout_retries_are_bounded():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    with pytest.raises(LLMProviderError, match="bounded retries"):
        _service(handler, retry_count=1).embed_documents(["文本"])
    assert attempts == 2
