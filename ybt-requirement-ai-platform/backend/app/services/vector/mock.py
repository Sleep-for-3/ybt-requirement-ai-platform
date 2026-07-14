import math
from typing import Any

from app.services.vector.base import VectorRecord, VectorSearchResult, VectorStore


class MockVectorStore(VectorStore):
    def __init__(self) -> None:
        self._records: dict[str, VectorRecord] = {}

    def upsert(self, records: list[VectorRecord]) -> None:
        for record in records:
            self._records[record.id] = VectorRecord(record.id,record.embedding,"",dict(record.metadata))

    def search(
        self,
        query_embedding: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        filters = filters or {}
        scored: list[VectorSearchResult] = []
        for record in self._records.values():
            if not _matches_filters(record.metadata, filters):
                continue
            scored.append(
                VectorSearchResult(
                    id=record.id,
                    score=_cosine_similarity(query_embedding, record.embedding),
                    content="",
                    metadata=record.metadata,
                )
            )
        return sorted(scored, key=lambda item: item.score, reverse=True)[:top_k]

    def delete(self,ids=None,filters=None):
        ids=set(ids or []);filters=filters or {}
        self._records={key:value for key,value in self._records.items() if key not in ids and not(filters and _matches_filters(value.metadata,filters))}


def _matches_filters(metadata: dict[str, Any], filters: dict[str, Any]) -> bool:
    for key, expected in filters.items():
        if expected in (None, "", []):
            continue
        actual = metadata.get(key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    length = min(len(left), len(right))
    dot = sum(left[index] * right[index] for index in range(length))
    norm_left = math.sqrt(sum(left[index] ** 2 for index in range(length)))
    norm_right = math.sqrt(sum(right[index] ** 2 for index in range(length)))
    if norm_left == 0 or norm_right == 0:
        return 0.0
    return dot / (norm_left * norm_right)
