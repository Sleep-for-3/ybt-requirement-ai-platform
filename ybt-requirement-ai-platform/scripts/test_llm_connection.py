#!/usr/bin/env python3
"""Run one minimal, explicit LLM connection test without reading project data."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
ENV_FILE = BACKEND / ".env"
sys.path.insert(0, str(BACKEND))


def load_private_environment() -> None:
    if not ENV_FILE.is_file():
        raise RuntimeError("backend/.env is missing; create it from the public template and review it")
    for raw_line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


async def run(include_embedding: bool) -> int:
    load_private_environment()
    from pydantic import BaseModel

    from app.core.settings import get_settings
    from app.services.embeddings import get_embedding_service
    from app.services.llm.factory import get_llm_service

    class ConnectionOutput(BaseModel):
        status: str
        message: str

    get_settings.cache_clear()
    settings = get_settings()
    print(f"Provider: {settings.llm_provider}")
    print(f"Model: {settings.llm_model or 'not configured'}")
    print(f"Base URL host: {urlsplit(settings.llm_base_url).hostname or 'not configured'}")
    service = get_llm_service()
    result = await service.chat_structured(
        "Return only a JSON object for a connection test.",
        'Return {"status":"ok","message":"连接成功"}. No project or user data is provided.',
        ConnectionOutput,
    )
    metadata = service.last_call
    print(f"HTTP status: {metadata.http_status if metadata.http_status is not None else 'not applicable'}")
    print(f"Latency: {metadata.latency_ms} ms")
    print(f"Token usage: {metadata.token_usage}")
    print(f"Valid JSON: {result.status == 'ok'}")
    if include_embedding:
        embedding = get_embedding_service()
        vector = embedding.embed_query("connection test")
        if not vector:
            raise RuntimeError("Embedding provider returned an empty vector")
        print(f"Embedding provider: {embedding.last_call.provider}")
        print(f"Embedding model: {embedding.last_call.model}")
        print(f"Embedding dimension: {len(vector)}")
        print(f"Embedding latency: {embedding.last_call.latency_ms} ms")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--embedding", action="store_true", help="also test the configured embedding provider")
    args = parser.parse_args()
    try:
        return asyncio.run(run(args.embedding))
    except Exception as exc:
        print(f"Connection test failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
