from functools import lru_cache

from app.core.settings import get_settings
from app.services.vector.base import VectorStore
from app.services.vector.milvus import MilvusVectorStore
from app.services.vector.mock import MockVectorStore


@lru_cache
def get_vector_store() -> VectorStore:
    provider = get_settings().vector_store_provider.lower()
    if provider == "mock":
        return MockVectorStore()
    if provider == "milvus":
        return MilvusVectorStore()
    raise ValueError(f"Unsupported VECTOR_STORE_PROVIDER: {provider}")
