import pytest

from app.services.vector import VectorRecord
from app.services.vector.milvus import MilvusVectorStore


class FakeMilvusClient:
    def __init__(self):
        self.collections = {}
        self.upserted = {}

    def has_collection(self, name):
        return name in self.collections

    def create_collection(self, **kwargs):
        self.collections[kwargs["collection_name"]] = kwargs

    def upsert(self, collection_name, data):
        self.upserted.update({item["id"]: item for item in data})
        return {"upsert_count": len(data)}

    def get_collection_stats(self, collection_name):
        return {"row_count": len(self.upserted)}

    def search(self, collection_name, data, **kwargs):
        item = next(iter(self.upserted.values()))
        return [[{"id": item["id"], "distance": 0.9, "entity": item}]]

    def delete(self, collection_name, **kwargs):
        return None

    def list_collections(self):
        return list(self.collections)


def test_milvus_store_uses_versioned_collection_and_validates_count_and_dimension():
    client = FakeMilvusClient()
    store = MilvusVectorStore(client=client, collection_name="semantic_v1", expected_dimension=3)
    record = VectorRecord(
        id="stable-id",
        embedding=[1.0, 0.0, 0.0],
        content="",
        metadata={"knowledge_unit_id": 9, "document_version_id": 3},
    )

    store.ensure_collection(3)
    store.upsert_embeddings([record])
    store.upsert_embeddings([record])

    assert client.collections["semantic_v1"]["dimension"] == 3
    assert store.count() == 1
    assert store.validate_index(expected_count=1, expected_dimension=3)["valid"] is True
    assert store.health_check()["healthy"] is True
    assert store.search([1.0, 0.0, 0.0], 1)[0].metadata["knowledge_unit_id"] == 9


def test_milvus_store_rejects_wrong_vector_dimension():
    store = MilvusVectorStore(client=FakeMilvusClient(), collection_name="semantic_v1", expected_dimension=3)
    with pytest.raises(ValueError, match="dimension"):
        store.upsert_embeddings([VectorRecord(id="bad", embedding=[1.0, 2.0], content="")])


def test_milvus_health_failure_is_explicit_and_search_dimension_must_match():
    class UnavailableClient(FakeMilvusClient):
        def list_collections(self):
            raise ConnectionError("synthetic unavailable")

    unhealthy = MilvusVectorStore(
        client=UnavailableClient(),
        collection_name="semantic_v1",
        expected_dimension=3,
    ).health_check()
    assert unhealthy["healthy"] is False
    assert unhealthy["error_type"] == "ConnectionError"

    store = MilvusVectorStore(
        client=FakeMilvusClient(),
        collection_name="semantic_v1",
        expected_dimension=3,
    )
    with pytest.raises(ValueError, match="dimension"):
        store.search([1.0, 0.0], 3)
