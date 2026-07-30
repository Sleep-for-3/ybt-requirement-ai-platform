from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class VectorRecord:
    id: str
    embedding: list[float]
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VectorSearchResult:
    id: str
    score: float
    content: str
    metadata: dict[str, Any]


class VectorStore(ABC):
    def health_check(self) -> dict[str, Any]:
        return {"healthy": True}

    def ensure_collection(self, dimension: int) -> None:
        """Create or validate the configured collection."""

    def upsert_embeddings(self, records: list[VectorRecord]) -> None:
        self.upsert(records)

    def count(self, filters: dict[str, Any] | None = None) -> int:
        raise NotImplementedError

    def validate_index(self, *, expected_count: int, expected_dimension: int) -> dict[str, Any]:
        actual_count = self.count()
        return {
            "valid": actual_count == expected_count,
            "expected_count": expected_count,
            "actual_count": actual_count,
            "expected_dimension": expected_dimension,
        }

    def delete_document_version(self, document_version_id: int) -> None:
        self.delete(filters={"document_version_id": document_version_id})

    @abstractmethod
    def upsert(self, records: list[VectorRecord]) -> None:
        """Insert or update vector records."""

    @abstractmethod
    def search(
        self,
        query_embedding: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        """Search records by vector similarity."""

    @abstractmethod
    def delete(self, ids: list[str] | None = None, filters: dict[str, Any] | None = None) -> None:
        """Delete records by id or metadata filters."""
