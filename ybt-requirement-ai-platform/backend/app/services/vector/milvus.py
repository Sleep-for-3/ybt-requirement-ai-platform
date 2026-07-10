from typing import Any

from app.services.vector.base import VectorRecord, VectorSearchResult, VectorStore


class MilvusVectorStore(VectorStore):
    """Placeholder for future Milvus integration.

    Knowhere is Milvus' lower-level vector execution engine. Business systems should
    integrate through Milvus APIs rather than calling Knowhere directly.
    """

    def upsert(self, records: list[VectorRecord]) -> None:
        raise NotImplementedError("Milvus integration is reserved for a later phase.")

    def search(
        self,
        query_embedding: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        raise NotImplementedError("Milvus integration is reserved for a later phase.")
