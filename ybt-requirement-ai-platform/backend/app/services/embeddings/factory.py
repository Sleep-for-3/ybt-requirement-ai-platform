from functools import lru_cache

from app.core.settings import get_settings
from app.services.llm.providers import is_local_provider, normalize_provider_type

from .mock import MockEmbeddingService
from .openai_compatible import LocalEmbeddingService, OpenAICompatibleEmbeddingService


@lru_cache
def get_embedding_service():
    settings = get_settings()
    provider = normalize_provider_type(settings.embedding_provider)
    if provider == "mock":
        return MockEmbeddingService()
    service_type = LocalEmbeddingService if is_local_provider(provider) else OpenAICompatibleEmbeddingService
    return service_type(
        settings.embedding_base_url,
        settings.embedding_model,
        settings.embedding_api_key_env_name,
        provider=provider,
    )
