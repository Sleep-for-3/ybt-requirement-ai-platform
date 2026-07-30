import ipaddress
import os
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from dotenv import dotenv_values

from app.services.llm.base import LLMConfigurationError


PROVIDER_ALIASES = {
    "openai-compatible": "openai_compatible",
    "vllm": "local_vllm",
    "ollama": "local_ollama_compatible",
    "local": "local_vllm",
    "local_openai_compatible": "local_vllm",
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
SECRET_VALUE_PATTERNS = (
    re.compile(r"^sk-[A-Za-z0-9_-]{16,}$"),
    re.compile(r"^(?:ghp|github_pat|xox[baprs])[_-][A-Za-z0-9_-]{16,}$"),
    re.compile(r"^AIza[A-Za-z0-9_-]{20,}$"),
)
METADATA_HOSTNAMES = {
    "metadata",
    "metadata.aws.internal",
    "metadata.azure.internal",
    "metadata.google.internal",
}
TRANSPARENT_PROXY_FAKE_IP_NETWORKS = (ipaddress.ip_network("198.18.0.0/15"),)


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


def validate_model_identifier(value: str | None) -> str | None:
    if value and any(pattern.fullmatch(value.strip()) for pattern in SECRET_VALUE_PATTERNS):
        raise ValueError("模型名称疑似填入了 API Key；请填写模型 ID，并把密钥放入 backend/.env")
    return value


def resolve_api_key(env_name: str | None, fallback: str = "") -> str:
    if not env_name:
        return fallback
    validate_env_name(env_name)
    process_value = os.getenv(env_name)
    if process_value is not None:
        return process_value
    try:
        dotenv_value = dotenv_values(".env", encoding="utf-8").get(env_name)
    except OSError:
        dotenv_value = None
    return str(dotenv_value) if dotenv_value is not None else fallback


def sanitize_base_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme, f"{host}{port}", parsed.path.rstrip("/"), "", ""))


def _is_forbidden_external_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
        or address.is_multicast
    )


def _is_transparent_proxy_fake_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return any(address in network for network in TRANSPARENT_PROXY_FAKE_IP_NETWORKS)


def validate_provider_url(
    value: str | None,
    *,
    local_only: bool,
    resolve_dns: bool = False,
) -> str | None:
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
    if (
        host in METADATA_HOSTNAMES
        or host == "localhost"
        or host.endswith(".localhost")
        or host.endswith(".local")
        or host.startswith("metadata.")
    ):
        raise ValueError("External providers cannot use local hostnames")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and _is_forbidden_external_address(str(address)):
        raise ValueError("External provider address is not allowed")
    is_reserved_test_host = host.endswith((".example", ".example.com", ".invalid", ".test"))
    if resolve_dns and address is None and not is_reserved_test_host:
        try:
            resolved = socket.getaddrinfo(
                host,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror:
            resolved = []
        if any(
            _is_forbidden_external_address(item[4][0])
            and not _is_transparent_proxy_fake_address(item[4][0])
            for item in resolved
        ):
            raise ValueError("External provider hostname resolves to a non-public address")
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
        try:
            validate_env_name(self.api_key_env_name)
            validate_model_identifier(self.model)
            validate_provider_url(
                self.base_url,
                local_only=self.local_only,
                resolve_dns=True,
            )
        except ValueError as exc:
            raise LLMConfigurationError(str(exc)) from exc
