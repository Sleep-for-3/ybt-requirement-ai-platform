from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

from app.services.security.content_redactor import redact_content


StructuredResponse = TypeVar("StructuredResponse", bound=BaseModel)

# Provider error payloads are persisted for operators, so they are collapsed to
# a single line, redacted and bounded before they ever reach the database.
MAX_ERROR_DETAIL_CHARS = 500


def sanitize_provider_error_detail(value: object | None) -> str | None:
    """Return a storable, redacted, length-bounded provider error payload."""

    if value is None:
        return None
    collapsed = " ".join(str(value).split())
    if not collapsed:
        return None
    return redact_content(collapsed)[:MAX_ERROR_DETAIL_CHARS]


@dataclass
class ModelCallMetadata:
    provider: str
    model: str
    latency_ms: int = 0
    token_usage: dict[str, Any] = field(default_factory=lambda: {"usage_available": False})
    retry_count: int = 0
    http_status: int | None = None


class LLMRuntimeError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_type: str,
        http_status: int | None = None,
        detail: object | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.http_status = http_status
        self.detail = sanitize_provider_error_detail(detail)


class LLMConfigurationError(LLMRuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message, error_type="configuration_error")


class LLMProviderError(LLMRuntimeError):
    pass


class LLMResponseError(LLMRuntimeError):
    def __init__(self, message: str, *, raw_response: str | None = None) -> None:
        super().__init__(message, error_type="invalid_model_response", detail=raw_response)
        self.raw_response = raw_response


class LLMService(ABC):
    last_call: ModelCallMetadata

    @abstractmethod
    async def chat_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Return a validated JSON-compatible model response."""

    async def chat_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[StructuredResponse],
    ) -> StructuredResponse:
        return response_schema.model_validate(await self.chat_json(system_prompt, user_prompt))

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Compatibility method; new embedding work uses the independent embedding gateway."""
