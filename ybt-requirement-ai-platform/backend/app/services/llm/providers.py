import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from app.services.llm.base import LLMConfigurationError


PROVIDER_ALIASES = {
    "openai-compatible": "openai_compatible",
    "vllm": "local_vllm",
    "ollama": "local_ollama_compatible",
    "local": "local_vllm",
}
SUPPORTED_PROVIDERS = {
    "mock",
    "openai",
    "openai_compatible",
    "local_vllm",
    "local_ollama_compatible",
}
LOCAL_PROVIDERS = {"local_vllm", "local_ollama_compatible"}
CLOUD_PROVIDERS = {"openai", "openai_compatible"}
ENV_NAME_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def normalize_provider_type(provider: str) -> str:
    normalized = provider.strip().lower()
    normalized = PROVIDER_ALIASES.get(normalized, normalized)
    if normalized not in SUPPORTED_PROVIDERS:
        raise LLMConfigurationError(f"Unsupported model provider: {provider}")
    return normalized


def is_local_provider(provider: str) -> bool:
    return normalize_provider_type(provider) in LOCAL_PROVIDERS


def provider_requires_api_key(provider: str) -> bool:
    return normalize_provider_type(provider) in CLOUD_PROVIDERS


def validate_env_name(value: str | None) -> str | None:
    if value and not ENV_NAME_PATTERN.fullmatch(value):
        raise ValueError("API key environment variable name is invalid")
    return value


def sanitize_base_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme, f"{host}{port}", parsed.path.rstrip("/"), "", ""))


def validate_provider_url(value: str | None, *, local_only: bool) -> str | None:
    if not value:
        return value
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Base URL must use http or https")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Base URL must not contain credentials, query parameters, or fragments")
    if local_only:
        return value.rstrip("/")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise ValueError("External providers cannot use local hostnames")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
        or address.is_multicast
    ):
        raise ValueError("External provider address is not allowed")
    return value.rstrip("/")


@dataclass(frozen=True)
class ProviderRuntimeConfig:
    provider: str
    base_url: str
    model: str
    api_key_env_name: str | None
    api_key: str
    local_only: bool

    def validate(self) -> None:
        normalized = normalize_provider_type(self.provider)
        if normalized == "mock":
            return
        if not self.base_url.strip():
            raise LLMConfigurationError("Model Base URL is not configured")
        if not self.model.strip():
            raise LLMConfigurationError("Model name is not configured")
        if provider_requires_api_key(normalized) and not self.api_key.strip():
            name = self.api_key_env_name or "configured environment variable"
            raise LLMConfigurationError(f"Model API key environment variable {name} is not configured")
