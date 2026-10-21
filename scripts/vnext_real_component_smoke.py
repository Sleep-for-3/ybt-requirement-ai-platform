"""VNext 真实组件 / 真实模型连通性冒烟。

用途：本机 WSL 已启动 PostgreSQL、Redis、Milvus、Ollama 之后，验证后端依赖的是
真实组件（不是 Mock）以及公司 API 提供的真实模型（LLM_PROVIDER=openai_compatible）。

不做破坏性操作：
- PostgreSQL 只读（`select 1` + 统计 public 表数量）；
- Redis 写一个带 TTL 的健康检查键，读回后删除；
- Milvus 建临时 collection（`vnext_smoke_<时间戳>`）→ 插入合成向量 → 检索 → 删除；
- LLM 只发少量请求（字段重排结构化 JSON、依据支持判定各一次），费用极小；
- 不打印任何密钥。

输出 JSON 到 stdout，可用 `--output` 落盘。单项失败记为 ``status=blocked/error``
并继续，不把失败包装成通过。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
import traceback
import uuid
from dataclasses import asdict
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.settings import get_settings  # noqa: E402
from app.services.llm.factory import get_llm_service  # noqa: E402

FIELD_RERANK_SYSTEM = (
    "你是银行监管数据字段匹配助手。只输出一个 JSON 对象，不要输出解释文字。"
)
FIELD_RERANK_USER = (
    "监管要求报送「客户统一标识」。候选来源字段：\n"
    "1. id=SRC1 表 CUSTOMER，字段 CUSTOMER_ID，说明：客户主键，全行唯一\n"
    "2. id=SRC2 表 PRODUCT，字段 PRODUCT_ID，说明：产品编号，同一客户多产品时重复\n"
    "3. id=SRC3 表 LOAN，字段 LOAN_NO，说明：借据号\n"
    "请输出 JSON：{\"ranking\":[{\"id\":\"SRC1\",\"score\":0.0,\"reason\":\"...\"}],"
    "\"chosen\":\"SRC1\"}"
)

CITATION_SYSTEM = "你是银行监管资料引用审核员。只输出 JSON 对象。"
CITATION_USER = (
    "主张：客户统一标识按产品编号报送。\n"
    "证据原文：客户统一标识取客户主键 CUSTOMER_ID，报送粒度为客户。\n"
    "请判断证据是否支持主张，输出 JSON："
    "{\"verdict\":\"supported|unsupported|partial\",\"reason\":\"...\"}"
)


def _timed(fn):
    start = time.perf_counter()
    try:
        value = fn()
        return value, round((time.perf_counter() - start) * 1000, 1), None
    except Exception as exc:  # noqa: BLE001 - report, do not hide
        return None, round((time.perf_counter() - start) * 1000, 1), exc


def check_postgres(settings) -> dict:
    def run():
        engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
        try:
            with engine.connect() as conn:
                conn.execute(text("select 1"))
                tables = conn.execute(text(
                    "select count(*) from information_schema.tables where table_schema='public'"
                )).scalar_one()
                return {"tables": int(tables)}
        finally:
            engine.dispose()

    value, ms, exc = _timed(run)
    if exc is not None:
        return {"status": "error", "latency_ms": ms, "error": repr(exc)[:400]}
    return {"status": "real", "latency_ms": ms, **value}


def check_redis(settings) -> dict:
    def run():
        import redis

        client = redis.Redis.from_url(settings.redis_url, socket_timeout=5)
        try:
            pong = client.ping()
            key = f"vnext:smoke:{uuid.uuid4().hex[:8]}"
            client.setex(key, 30, "ok")
            value = client.get(key)
            client.delete(key)
            return {"ping": bool(pong), "roundtrip": value == b"ok"}
        finally:
            client.close()

    value, ms, exc = _timed(run)
    if exc is not None:
        return {"status": "error", "latency_ms": ms, "error": repr(exc)[:400]}
    return {"status": "real", "latency_ms": ms, **value}


def check_milvus(settings) -> dict:
    def run():
        from pymilvus import MilvusClient

        from app.services.vector.base import VectorRecord
        from app.services.vector.factory import get_vector_store

        name = f"vnext_smoke_{int(time.time())}"
        dim = int(settings.embedding_dimension or 512)
        store = get_vector_store(collection_name=name, expected_dimension=dim)
        health = store.health_check()
        rng = random.Random(7)
        records = [
            VectorRecord(id=f"smoke-{index}", embedding=[rng.random() for _ in range(dim)],
                         content=label, metadata={"label": label})
            for index, label in enumerate(["客户", "产品", "借据"], start=1)
        ]
        store.upsert(records)
        results = store.search(records[0].embedding, 2)
        count = store.count()
        MilvusClient(uri=settings.milvus_uri).drop_collection(name)
        return {
            "dim": dim,
            "count": count,
            "hits": len(results),
            "top_id": results[0].id if results else None,
            "health": health,
        }

    value, ms, exc = _timed(run)
    if exc is not None:
        return {"status": "error", "latency_ms": ms, "error": repr(exc)[:400],
                "trace": traceback.format_exc()[-800:]}
    return {"status": "real", "latency_ms": ms, **value}


def check_embeddings(settings) -> dict:
    def run():
        url = settings.embedding_base_url.rstrip("/") + "/embeddings"
        with httpx.Client(timeout=60) as client:
            response = client.post(url, json={
                "model": settings.embedding_model,
                "input": "客户统一标识",
            })
            body = response.text[:300]
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}: {body}")
            payload = response.json()
            vector = payload["data"][0]["embedding"]
            return {"dim": len(vector), "model": payload.get("model")}

    value, ms, exc = _timed(run)
    if exc is not None:
        return {"status": "blocked", "latency_ms": ms, "error": repr(exc)[:400]}
    return {"status": "real", "latency_ms": ms, **value}


def check_llm(settings) -> dict:
    async def ask(system: str, user: str) -> dict:
        service = get_llm_service()
        started = time.perf_counter()
        payload = await service.chat_json(system, user)
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        return {"payload": payload, "latency_ms": elapsed,
                "metadata": asdict(service.last_call)}

    results: dict = {}
    for key, (system, user) in {
        "field_rerank": (FIELD_RERANK_SYSTEM, FIELD_RERANK_USER),
        "citation_support": (CITATION_SYSTEM, CITATION_USER),
    }.items():
        try:
            results[key] = {"status": "real", **asyncio.run(ask(system, user))}
        except Exception as exc:  # noqa: BLE001
            results[key] = {"status": "error", "error": repr(exc)[:500]}
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--skip-llm", action="store_true")
    args = parser.parse_args(argv)
    settings = get_settings()

    report: dict = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "config": {
            "llm_provider": settings.llm_provider,
            "llm_model": settings.llm_model,
            "llm_base_url": settings.llm_base_url,
            "database": settings.database_url.split("@")[-1] if "@" in settings.database_url else settings.database_url,
            "redis_url": settings.redis_url,
            "milvus_uri": settings.milvus_uri,
            "embedding_provider": settings.embedding_provider,
            "embedding_model": settings.embedding_model,
            "embedding_base_url": settings.embedding_base_url,
            "embedding_dimension": settings.embedding_dimension,
        },
        "checks": {},
    }
    report["checks"]["postgres"] = check_postgres(settings)
    report["checks"]["redis"] = check_redis(settings)
    report["checks"]["milvus"] = check_milvus(settings)
    report["checks"]["embeddings"] = check_embeddings(settings)
    if not args.skip_llm:
        report["checks"]["llm"] = check_llm(settings)

    text_report = json.dumps(report, ensure_ascii=False, indent=2)
    print(text_report)
    if args.output:
        args.output.write_text(text_report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
