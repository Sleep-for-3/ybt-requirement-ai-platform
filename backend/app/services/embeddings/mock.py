import hashlib
import time

from app.services.embeddings.base import EmbeddingBatchResult
from app.services.llm.base import ModelCallMetadata


class MockEmbeddingService:
    dimensions = 64
    local_only = True

    def __init__(self):
        self.last_call = ModelCallMetadata(
            provider="mock",
            model="mock-embedding",
            token_usage={"usage_available": False},
        )

    def embed_documents(self, texts: list[str]) -> EmbeddingBatchResult:
        started = time.perf_counter()
        vectors = [self._embed(text) for text in texts]
        self.last_call = ModelCallMetadata(
            provider="mock",
            model="mock-embedding",
            latency_ms=int((time.perf_counter() - started) * 1000),
            token_usage={"usage_available": False},
        )
        return EmbeddingBatchResult(
            vectors=vectors,
            provider="mock",
            model="mock-embedding",
            dimension=self.dimensions if vectors else 0,
            latency_ms=self.last_call.latency_ms,
            token_usage=self.last_call.token_usage,
            batch_count=1 if vectors else 0,
        )

    def embed_texts(self, texts):
        return self.embed_documents(texts).vectors

    def embed_query(self, text):
        return self.embed_documents([text]).vectors[0]

    def _embed(self, text):
        digest = hashlib.sha256(text.encode()).digest()
        return [digest[index % 32] / 255 - 0.5 for index in range(self.dimensions)]
