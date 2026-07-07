from abc import ABC, abstractmethod


class LLMService(ABC):
    @abstractmethod
    async def chat_json(self, system_prompt: str, user_prompt: str) -> dict:
        """Return a JSON-compatible model response."""

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return embeddings for the given texts."""
