import os
from app.core.settings import get_settings
from app.services.llm.base import LLMService
from app.services.llm.mock import MockLLMService
from app.services.llm.openai_compatible import OpenAICompatibleLLMService


def get_llm_service(
    provider: str | None = None,
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key_env_name: str | None = None,
) -> LLMService:
    settings = get_settings()
    selected_provider = (provider or settings.llm_provider).lower()
    if selected_provider == "mock":
        return MockLLMService()
    if selected_provider in {"openai", "openai_compatible", "vllm", "local_vllm", "ollama", "local_ollama_compatible", "openai-compatible"}:
        return OpenAICompatibleLLMService(
            base_url=base_url or settings.llm_base_url,
            api_key=os.getenv(api_key_env_name or settings.llm_api_key_env_name,settings.llm_api_key),
            model=model or settings.llm_model,
            embedding_model=settings.embedding_model,
        )
    raise ValueError(f"Unsupported LLM_PROVIDER: {selected_provider}")
