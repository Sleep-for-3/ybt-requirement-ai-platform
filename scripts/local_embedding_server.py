"""本地 OpenAI 兼容 embedding 服务（验收/开发用，不进入生产路径）。

背景：内网暂时没有可用的 embedding 推理服务（alpine ollama 缺 llama-server，
ollama 官方镜像与 HF 直连受网络限制）。本服务用 fastembed + onnxruntime
在 CPU 上加载 `bge-small-zh-v1.5`（512 维），暴露与项目
`EMBEDDING_BASE_URL`/`EMBEDDING_MODEL` 约定的 `/v1/embeddings` 接口，
用于真实组件与真实检索链路的验收。

用法（模型权重已缓存到 %USERPROFILE%\\.cache\\huggingface 时无需联网）：

    python scripts/local_embedding_server.py --port 11434

首次下载权重需设置：
    HF_ENDPOINT=https://hf-mirror.com
    HF_HUB_DISABLE_XET=1

接口：
    GET  /health            -> {"status": "ok", "model": ..., "dimension": ...}
    GET  /v1/models         -> OpenAI 兼容列表
    POST /v1/embeddings     -> {"model", "input": str | [str], "encoding_format": "float"}

注意：这是**验收替身**，生产必须由内网模型服务或离线权重提供；不得把本服务
当作生产 embedding 方案写进正式部署。
"""

from __future__ import annotations

import argparse
import math
import os
import time
from typing import Any

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from fastapi import FastAPI, HTTPException  # noqa: E402
from pydantic import BaseModel  # noqa: E402

MODEL_NAME = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
EXPECTED_DIMENSION = int(os.environ.get("EMBEDDING_DIMENSION", "512"))

app = FastAPI(title="local embedding server", version="0.1")
_state: dict[str, Any] = {"model": None, "dimension": 0, "loaded_at": None}


def _get_model():
    if _state["model"] is None:
        from fastembed import TextEmbedding

        started = time.time()
        _state["model"] = TextEmbedding(MODEL_NAME)
        probe = list(_state["model"].embed(["维度探测"]))[0]
        _state["dimension"] = len(probe)
        _state["loaded_at"] = round(time.time() - started, 1)
        if EXPECTED_DIMENSION and _state["dimension"] != EXPECTED_DIMENSION:
            raise RuntimeError(
                f"embedding dimension mismatch: model={_state['dimension']} expected={EXPECTED_DIMENSION}"
            )
    return _state["model"]


class EmbeddingRequest(BaseModel):
    model: str | None = None
    input: str | list[str]
    encoding_format: str | None = None


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [value / norm for value in vector]


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        _get_model()
    except Exception as exc:  # pragma: no cover - 启动期错误直接暴露
        raise HTTPException(status_code=503, detail=f"model not ready: {exc}") from exc
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "dimension": _state["dimension"],
        "load_seconds": _state["loaded_at"],
    }


@app.get("/v1/models")
def models() -> dict[str, Any]:
    return {"object": "list", "data": [{"id": MODEL_NAME, "object": "model"}]}


@app.post("/v1/embeddings")
def embeddings(request: EmbeddingRequest) -> dict[str, Any]:
    texts = [request.input] if isinstance(request.input, str) else list(request.input)
    if not texts:
        raise HTTPException(status_code=422, detail="input must not be empty")
    started = time.time()
    model = _get_model()
    vectors = [[float(value) for value in vector] for vector in model.embed(texts)]
    data = []
    for index, vector in enumerate(vectors):
        values = vector if request.encoding_format == "base64" else _normalize(vector)
        data.append({"object": "embedding", "index": index, "embedding": values})
    return {
        "object": "list",
        "data": data,
        "model": request.model or MODEL_NAME,
        "usage": {"prompt_tokens": sum(len(text) for text in texts), "total_tokens": sum(len(text) for text in texts)},
        "elapsed_ms": round((time.time() - started) * 1000, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11434)
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
