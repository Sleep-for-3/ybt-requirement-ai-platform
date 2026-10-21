"""语义检索真实链路冒烟：应用自身 embedding 服务 + Milvus 向量库。

目的：在 embedding 服务可用后，验证「文档向量化 → Milvus 写入 → 查询向量 →
相似度检索命中正确字段」这条真实组件链路（不是 Mock，不是定向构造的距离）。

用法（cwd=backend，需 EMBEDDING_BASE_URL 指向可用服务、MILVUS_URI 可连）：

    python scripts/vnext_semantic_smoke.py --output ../docs/audit/VNEXT_REAL_SEMANTIC_SMOKE-20261021.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import traceback
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

FIELD_DOCS = [
    ("field:customer_id", "客户统一标识，取客户主数据 CUSTOMER_ID，客户粒度唯一"),
    ("field:product_no", "产品编号，同一客户办理多个产品时重复，不能唯一标识客户"),
    ("field:loan_no", "借据号，标识单笔贷款业务，非客户标识"),
    ("field:stat_date", "统计日期，数据分区字段，按报送日取 T-1 快照"),
]

QUERIES = [
    ("客户统一标识取哪个字段", "field:customer_id"),
    ("借据对应的编号", "field:loan_no"),
    ("报送数据按哪天取数", "field:stat_date"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    report: dict = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "checks": {}}
    started = time.time()
    try:
        from app.core.settings import get_settings
        from app.services.embeddings.factory import get_embedding_service
        from app.services.vector.base import VectorRecord
        from app.services.vector.factory import get_vector_store

        settings = get_settings()
        embedding = get_embedding_service()
        report["config"] = {
            "embedding_provider": settings.embedding_provider,
            "embedding_model": settings.embedding_model,
            "embedding_base_url": settings.embedding_base_url,
            "embedding_dimension": settings.embedding_dimension,
            "vector_store": settings.vector_store_provider,
            "milvus_uri": settings.milvus_uri,
        }

        t0 = time.time()
        batch = embedding.embed_documents([text for _, text in FIELD_DOCS])
        doc_vectors = batch.vectors
        embed_ms = round((time.time() - t0) * 1000, 1)
        dim = len(doc_vectors[0])
        report["checks"]["embed_documents"] = {
            "status": "real",
            "dimension": dim,
            "count": len(doc_vectors),
            "latency_ms": embed_ms,
            "expected_dimension": int(settings.embedding_dimension),
            "dimension_ok": dim == int(settings.embedding_dimension),
        }

        collection = f"vnext_semantic_{int(time.time())}"
        store = get_vector_store(collection_name=collection, expected_dimension=dim)
        upsert_ms = 0.0
        t0 = time.time()
        store.upsert([
            VectorRecord(id=doc_id, embedding=vector, content=text, metadata={"field": doc_id})
            for (doc_id, text), vector in zip(FIELD_DOCS, doc_vectors, strict=True)
        ])
        upsert_ms = round((time.time() - t0) * 1000, 1)
        count = store.count()
        for _ in range(10):
            if count >= len(FIELD_DOCS):
                break
            time.sleep(0.5)
            count = store.count()
        report["checks"]["milvus_upsert"] = {
            "status": "real", "collection": collection, "rows": count, "latency_ms": upsert_ms,
        }

        retrieval = []
        for query, expected in QUERIES:
            t0 = time.time()
            vector = embedding.embed_query(query)
            hits = store.search(vector, top_k=3)
            latency = round((time.time() - t0) * 1000, 1)
            top_ids = [hit.id for hit in hits]
            retrieval.append({
                "query": query,
                "expected": expected,
                "top_ids": top_ids,
                "top_score": round(hits[0].score, 4) if hits else None,
                "hit_at_1": bool(top_ids[:1] == [expected]),
                "hit_at_3": expected in top_ids,
                "latency_ms": latency,
            })
        report["checks"]["retrieval"] = {
            "status": "real",
            "cases": retrieval,
            "top1_accuracy": round(sum(1 for r in retrieval if r["hit_at_1"]) / len(retrieval), 3),
            "top3_accuracy": round(sum(1 for r in retrieval if r["hit_at_3"]) / len(retrieval), 3),
        }

        # 随机向量对照：真实语义检索应显著好于随机噪声
        rng = random.Random(7)
        noise_hits = store.search([rng.random() for _ in range(dim)], top_k=1)
        report["checks"]["random_vector_control"] = {
            "top_id": noise_hits[0].id if noise_hits else None,
            "note": "随机向量也会返回最近邻，用于说明仅凭 Milvus 命中不能证明语义质量",
        }

        from pymilvus import MilvusClient

        MilvusClient(uri=settings.milvus_uri).drop_collection(collection)
        report["checks"]["cleanup"] = {"collection_dropped": collection}
        report["status"] = "real"
    except Exception as exc:  # pragma: no cover - 冒烟失败路径
        report["status"] = "error"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["trace"] = traceback.format_exc()[-1200:]

    report["total_ms"] = round((time.time() - started) * 1000, 1)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    return 0 if report.get("status") == "real" else 1


if __name__ == "__main__":
    raise SystemExit(main())
