import json

import httpx

from app.services.llm.base import LLMService
from app.services.llm.mock import MockLLMService


class OpenAICompatibleLLMService(LLMService):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        embedding_model: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.embedding_model = embedding_model
        self._fallback = MockLLMService()

    async def chat_json(self, system_prompt: str, user_prompt: str) -> dict:
        if not self.api_key:
            return await self._fallback.chat_json(system_prompt, user_prompt)

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            return await self._fallback.embed_texts(texts)

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.base_url}/embeddings",
                json={"model": self.embedding_model, "input": texts},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
        data = response.json()["data"]
        return [item["embedding"] for item in data]
