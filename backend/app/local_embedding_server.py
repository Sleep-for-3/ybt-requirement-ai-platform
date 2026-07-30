import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


MODEL_NAME = "BAAI/bge-small-zh-v1.5"
VECTOR_DIMENSION = 512

app = FastAPI(title="YBT Local Embedding Service", docs_url=None, redoc_url=None)


class EmbeddingRequest(BaseModel):
    model: str
    input: str | list[str]
    input_type: Literal["document", "query"] = "document"


class EmbeddingItem(BaseModel):
    object: str = "embedding"
    index: int
    embedding: list[float]


class EmbeddingUsage(BaseModel):
    prompt_tokens: int = 0
    total_tokens: int = 0


class EmbeddingResponse(BaseModel):
    object: str = "list"
    model: str
    data: list[EmbeddingItem]
    usage: EmbeddingUsage = Field(default_factory=EmbeddingUsage)


@lru_cache(maxsize=1)
def get_embedding_model():
    from fastembed import TextEmbedding

    cache_dir = Path(os.getenv("FASTEMBED_CACHE_PATH", ".local-fastembed-cache")).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    threads = max(1, min(int(os.getenv("FASTEMBED_THREADS", "2")), 8))
    return TextEmbedding(
        model_name=MODEL_NAME,
        cache_dir=str(cache_dir),
        threads=threads,
        providers=["CPUExecutionProvider"],
    )


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "healthy", "model": MODEL_NAME, "dimension": VECTOR_DIMENSION}


@app.post("/v1/embeddings", response_model=EmbeddingResponse)
def embeddings(
    payload: EmbeddingRequest,
    input_type_header: Literal["document", "query"] | None = Header(
        default=None,
        alias="X-YBT-Embedding-Input-Type",
    ),
) -> EmbeddingResponse:
    if payload.model != MODEL_NAME:
        raise HTTPException(status_code=400, detail="Unsupported embedding model")
    texts = [payload.input] if isinstance(payload.input, str) else payload.input
    if not texts or len(texts) > 256:
        raise HTTPException(status_code=400, detail="Embedding input count must be between 1 and 256")
    if any(not isinstance(text, str) or not text.strip() for text in texts):
        raise HTTPException(status_code=400, detail="Embedding input must contain non-empty strings")
    model = get_embedding_model()
    input_type = input_type_header or payload.input_type
    encoder = model.query_embed if input_type == "query" else model.embed
    vectors = [list(map(float, vector)) for vector in encoder(texts)]
    if len(vectors) != len(texts):
        raise HTTPException(status_code=502, detail="Embedding model returned an unexpected vector count")
    if any(not vector or not all(math.isfinite(value) for value in vector) for vector in vectors):
        raise HTTPException(status_code=502, detail="Embedding model returned invalid vector values")
    return EmbeddingResponse(
        model=MODEL_NAME,
        data=[
            EmbeddingItem(index=index, embedding=vector)
            for index, vector in enumerate(vectors)
        ],
    )
