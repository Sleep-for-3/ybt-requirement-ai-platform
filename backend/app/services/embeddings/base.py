from dataclasses import dataclass, field
from typing import Any, Protocol

from app.services.llm.base import ModelCallMetadata


@dataclass(frozen=True)
class EmbeddingBatchResult:
    vectors: list[list[float]]
    provider: str
    model: str
    dimension: int
    latency_ms: int
    token_usage: dict[str, Any] = field(default_factory=dict)
    batch_count: int = 0
    retry_count: int = 0


class EmbeddingService(Protocol):
    local_only: bool
    last_call: ModelCallMetadata

    def embed_documents(self, texts: list[str]) -> EmbeddingBatchResult: ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...
