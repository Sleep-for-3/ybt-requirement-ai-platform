from typing import Any

from app.core.settings import get_settings
from app.services.llm.base import LLMService
from app.services.llm.mock import MockLLMService
from app.services.llm.openai_compatible import OpenAICompatibleLLMService
from app.services.llm.providers import (
    normalize_provider_type,
    resolve_api_key,
    sanitize_base_url,
    validate_env_name,
)


def _fallback_model_names(settings: Any, options: dict[str, Any]) -> list[str]:
    """Read the fallback chain from the profile options, then from the environment."""

    raw = options.get("fallback_models")
    if raw is None:
        raw = settings.llm_fallback_models
    if isinstance(raw, (list, tuple, set)):
        candidates = [str(item) for item in raw]
    else:
        candidates = str(raw or "").replace(";", ",").split(",")
    return [item.strip() for item in candidates if item.strip()]


def get_llm_service(
    provider: str | None = None,
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key_env_name: str | None = None,
    config: dict[str, Any] | None = None,
    timeout_seconds: float | None = None,
    retry_count: int | None = None,
) -> LLMService:
    settings = get_settings()
    selected_provider = normalize_provider_type(provider or settings.llm_provider)
    if selected_provider == "mock":
        return MockLLMService()
    env_name = api_key_env_name or settings.llm_api_key_env_name
    options = config or {}
    # Interactive callers pass an explicit budget so a single slow provider
    # cannot consume the whole request; background generation keeps the longer
    # ``LLM_TIMEOUT_SECONDS`` budget.
    resolved_timeout = float(
        timeout_seconds
        if timeout_seconds is not None
        else options.get("timeout_seconds", settings.llm_timeout_seconds)
    )
    resolved_retries = int(
        retry_count if retry_count is not None else options.get("retry_count", 2)
    )
    fallback_models = _fallback_model_names(settings, options)
    fallback_env_name = validate_env_name(
        str(options.get("fallback_api_key_env_name") or settings.llm_fallback_api_key_env_name or "") or None
    )
    fallback_base_url = sanitize_base_url(
        str(options.get("fallback_base_url") or settings.llm_fallback_base_url or "")
    )
    return OpenAICompatibleLLMService(
        base_url=base_url or settings.llm_base_url,
        api_key=resolve_api_key(env_name, settings.llm_api_key),
        api_key_env_name=env_name,
        model=model or settings.llm_model,
        provider=selected_provider,
        json_mode=bool(options.get("json_mode", True)),
        max_output_tokens=int(options.get("max_output_tokens", 2048)),
        temperature=float(options.get("temperature", 0.2)),
        timeout_seconds=resolved_timeout,
        retry_count=resolved_retries,
        fallback_models=fallback_models,
        fallback_base_url=fallback_base_url,
        fallback_api_key=resolve_api_key(fallback_env_name) if fallback_env_name else None,
        fallback_api_key_env_name=fallback_env_name,
    )


def get_interactive_llm_service(
    provider: str | None = None,
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key_env_name: str | None = None,
    config: dict[str, Any] | None = None,
    retry_count: int = 1,
) -> LLMService:
    """Build the service used by synchronous, user-facing endpoints.

    The budget is ``LLM_INTERACTIVE_TIMEOUT_SECONDS``.  ``retry_count`` stays
    explicit because a silent retry doubles the worst-case wait and can outlive
    the browser or proxy timeout -- the exact failure the iteration plan asked
    to remove.  Callers that cannot degrade (the operator's connection test)
    keep one retry for a fairer verdict; callers that degrade (knowledge Q&A)
    pass ``retry_count=0``.
    """

    settings = get_settings()
    return get_llm_service(
        provider,
        base_url=base_url,
        model=model,
        api_key_env_name=api_key_env_name,
        config=config,
        timeout_seconds=float(settings.llm_interactive_timeout_seconds),
        retry_count=retry_count,
    )
