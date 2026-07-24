from typing import Protocol

from app.services.llm.base import ModelCallMetadata


class EmbeddingService(Protocol):
    local_only: bool
    last_call: ModelCallMetadata

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...
