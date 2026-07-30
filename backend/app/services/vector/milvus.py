import json
import math
from typing import Any

from app.core.settings import get_settings
from app.services.vector.base import VectorRecord, VectorSearchResult, VectorStore


class MilvusVectorStore(VectorStore):
    """A collection-scoped Milvus adapter used by one immutable index version."""

    def __init__(
        self,
        client=None,
        collection_name: str = "ybt_knowledge_units",
        expected_dimension: int | None = None,
        metric_type: str | None = None,
        index_type: str | None = None,
    ):
        settings = get_settings()
        if client is None:
            try:
                from pymilvus import MilvusClient
            except ImportError as exc:
                raise RuntimeError("Milvus provider requires optional pymilvus dependency") from exc
            client = MilvusClient(
                uri=settings.milvus_uri,
                token=settings.milvus_token,
                timeout=settings.milvus_connection_timeout_seconds,
            )
        self.client = client
        self.collection_name = collection_name
        self.expected_dimension = expected_dimension
        self.metric_type = (metric_type or settings.milvus_metric_type).upper()
        self.index_type = (index_type or settings.milvus_index_type).upper()

    def health_check(self) -> dict[str, Any]:
        try:
            collections = self.client.list_collections()
            return {
                "healthy": True,
                "collection": self.collection_name,
                "collection_exists": self.collection_name in collections,
            }
        except Exception as exc:
            return {
                "healthy": False,
                "collection": self.collection_name,
                "error_type": type(exc).__name__,
            }

    def ensure_collection(self, dimension: int) -> None:
        self._validate_dimension(dimension)
        if self.client.has_collection(self.collection_name):
            self._validate_existing_collection_dimension(dimension)
            return
        index_params = None
        if hasattr(self.client, "prepare_index_params"):
            index_params = self.client.prepare_index_params()
            index_params.add_index(
                field_name="vector",
                index_type=self.index_type,
                metric_type=self.metric_type,
                params={},
            )
        self.client.create_collection(
            collection_name=self.collection_name,
            dimension=dimension,
            metric_type=self.metric_type,
            auto_id=False,
            primary_field_name="id",
            id_type="string",
            max_length=128,
            vector_field_name="vector",
            enable_dynamic_field=True,
            index_params=index_params,
        )

    def upsert_embeddings(self, records: list[VectorRecord]) -> None:
        self.upsert(records)

    def upsert(self, records: list[VectorRecord]) -> None:
        if not records:
            return
        dimension = len(records[0].embedding)
        self._validate_dimension(dimension)
        for record in records:
            self._validate_vector(record.embedding, dimension)
        self.ensure_collection(dimension)
        self.client.upsert(
            collection_name=self.collection_name,
            data=[_milvus_row(record) for record in records],
        )

    def search(
        self,
        query_embedding: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        self._validate_dimension(len(query_embedding))
        self._validate_vector(query_embedding, len(query_embedding))
        expression = _filter_expression(filters or {})
        rows = self.client.search(
            self.collection_name,
            [query_embedding],
            limit=top_k,
            filter=expression or "",
            output_fields=["*"],
        )[0]
        results = []
        for row in rows:
            entity = row.get("entity", row)
            results.append(
                VectorSearchResult(
                    id=str(row["id"]),
                    score=float(row["distance"]),
                    content="",
                    metadata={
                        key: value
                        for key, value in entity.items()
                        if key not in {"id", "vector", "content"}
                    },
                )
            )
        return results

    def delete(self, ids=None, filters=None):
        if ids:
            self.client.delete(collection_name=self.collection_name, ids=ids)
        elif filters:
            self.client.delete(
                collection_name=self.collection_name,
                filter=_filter_expression(filters),
            )

    def count(self, filters: dict[str, Any] | None = None) -> int:
        if not self.client.has_collection(self.collection_name):
            return 0
        if hasattr(self.client, "query"):
            rows = self.client.query(
                collection_name=self.collection_name,
                filter=_filter_expression(filters or {}),
                output_fields=["count(*)"],
            )
            if rows:
                return int(rows[0].get("count(*)", rows[0].get("count", 0)))
        stats = self.client.get_collection_stats(collection_name=self.collection_name)
        return int(stats.get("row_count", 0))

    def validate_index(self, *, expected_count: int, expected_dimension: int) -> dict[str, Any]:
        if hasattr(self.client, "flush"):
            self.client.flush(collection_name=self.collection_name)
        dimension_valid = self.expected_dimension in {None, expected_dimension}
        actual_count = self.count()
        return {
            "valid": dimension_valid and actual_count == expected_count,
            "expected_count": expected_count,
            "actual_count": actual_count,
            "expected_dimension": expected_dimension,
            "dimension_valid": dimension_valid,
            "collection": self.collection_name,
        }

    def _validate_dimension(self, dimension: int) -> None:
        if dimension <= 0:
            raise ValueError("Embedding dimension must be positive")
        if self.expected_dimension is not None and dimension != self.expected_dimension:
            raise ValueError(
                f"Embedding dimension {dimension} does not match expected dimension "
                f"{self.expected_dimension}"
            )

    @staticmethod
    def _validate_vector(vector: list[float], dimension: int) -> None:
        if len(vector) != dimension or not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            for value in vector
        ):
            raise ValueError("Embedding vector has an invalid dimension or value")

    def _validate_existing_collection_dimension(self, expected: int) -> None:
        if not hasattr(self.client, "describe_collection"):
            return
        description = self.client.describe_collection(
            collection_name=self.collection_name
        )
        for field in description.get("fields", []):
            if field.get("name") != "vector":
                continue
            params = field.get("params") or {}
            actual = params.get("dim") or field.get("dimension")
            if actual is not None and int(actual) != expected:
                raise ValueError(
                    f"Milvus collection dimension {actual} does not match expected dimension {expected}"
                )


def _filter_expression(filters):
    parts = []
    for key, value in filters.items():
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            parts.append(f"{key} in {json.dumps(value, ensure_ascii=False)}")
        elif isinstance(value, str):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            parts.append(f'{key} == "{escaped}"')
        elif isinstance(value, bool):
            parts.append(f"{key} == {str(value).lower()}")
        else:
            parts.append(f"{key} == {value!r}")
    return " and ".join(parts)


def _milvus_row(record):
    return {"id": record.id, "vector": record.embedding, **record.metadata}
