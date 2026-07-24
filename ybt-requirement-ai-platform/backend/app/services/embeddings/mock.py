import hashlib
from app.services.llm.base import ModelCallMetadata
class MockEmbeddingService:
    dimensions=64;local_only=True
    def __init__(self):self.last_call=ModelCallMetadata(provider="mock",model="mock-embedding",token_usage={"usage_available":False})
    def embed_texts(self,texts):return [self._embed(text) for text in texts]
    def embed_query(self,text):return self._embed(text)
    def _embed(self,text):
        digest=hashlib.sha256(text.encode()).digest();return [digest[index%32]/255-.5 for index in range(self.dimensions)]
