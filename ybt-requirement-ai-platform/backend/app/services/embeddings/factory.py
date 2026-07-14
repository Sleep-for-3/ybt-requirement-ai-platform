from functools import lru_cache
from app.core.settings import get_settings
from .mock import MockEmbeddingService
from .openai_compatible import LocalEmbeddingService,OpenAICompatibleEmbeddingService
@lru_cache
def get_embedding_service():
    s=get_settings();provider=s.embedding_provider.lower()
    if provider=="mock":return MockEmbeddingService()
    cls=LocalEmbeddingService if provider in {"local","local_vllm","local_ollama_compatible"} else OpenAICompatibleEmbeddingService
    return cls(s.embedding_base_url,s.embedding_model,s.embedding_api_key_env_name)
