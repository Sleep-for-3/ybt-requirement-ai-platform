import os
from typing import Any

from app.core.settings import get_settings
from app.services.llm.base import LLMService
from app.services.llm.mock import MockLLMService
from app.services.llm.openai_compatible import OpenAICompatibleLLMService
from app.services.llm.providers import normalize_provider_type


def get_llm_service(
    provider: str | None = None,
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key_env_name: str | None = None,
    config: dict[str, Any] | None = None,
) -> LLMService:
    settings = get_settings()
    selected_provider = normalize_provider_type(provider or settings.llm_provider)
    if selected_provider == "mock":
        return MockLLMService()
    env_name = api_key_env_name or settings.llm_api_key_env_name
    options = config or {}
    return OpenAICompatibleLLMService(
        base_url=base_url or settings.llm_base_url,
        api_key=os.getenv(env_name, settings.llm_api_key),
        api_key_env_name=env_name,
        model=model or settings.llm_model,
        provider=selected_provider,
        json_mode=bool(options.get("json_mode", True)),
        max_output_tokens=int(options.get("max_output_tokens", 2048)),
        temperature=float(options.get("temperature", 0.2)),
        timeout_seconds=float(options.get("timeout_seconds", 60)),
        retry_count=int(options.get("retry_count", 2)),
    )
