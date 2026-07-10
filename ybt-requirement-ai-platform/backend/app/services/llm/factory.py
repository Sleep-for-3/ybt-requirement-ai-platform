from app.core.settings import get_settings
from app.services.llm.base import LLMService
from app.services.llm.mock import MockLLMService
from app.services.llm.openai_compatible import OpenAICompatibleLLMService


def get_llm_service(provider: str | None = None) -> LLMService:
    settings = get_settings()
    selected_provider = (provider or settings.llm_provider).lower()
    if selected_provider == "mock":
        return MockLLMService()
    if selected_provider in {"openai", "vllm", "ollama", "openai-compatible"}:
        return OpenAICompatibleLLMService(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            embedding_model=settings.embedding_model,
        )
    raise ValueError(f"Unsupported LLM_PROVIDER: {selected_provider}")
