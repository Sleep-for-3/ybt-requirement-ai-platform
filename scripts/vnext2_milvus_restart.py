"""VNext2 P2-A：Milvus 重启后已有集合与索引是否仍可查询。

用途：先 ``create`` 建一个带随机向量的临时集合（不依赖 embedding 服务，只验证持久化与
索引可用性），重启 Milvus 容器后 ``verify`` 再查同一批向量并 ``drop`` 清理。

用法（cwd=ai-platform，需 MILVUS_URI 可连）::

    backend\\.venv\\Scripts\\python.exe scripts\\vnext2_milvus_restart.py create
    docker restart ybt-dev-milvus-1
    backend\\.venv\\Scripts\\python.exe scripts\\vnext2_milvus_restart.py verify

证据级别：REAL_COMPONENT（真实 Milvus 2.5.4），向量为随机值，不代表语义质量。
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from pymilvus import DataType, MilvusClient  # noqa: E402

from app.core.settings import get_settings  # noqa: E402

COLLECTION = "vnext2_restart_probe"
DIM = 512
ROWS = 16


def _vectors() -> list[list[float]]:
    rng = random.Random(20261023)
    return [[rng.uniform(-1, 1) for _ in range(DIM)] for _ in range(ROWS)]


def create(client: MilvusClient) -> dict:
    if client.has_collection(COLLECTION):
        client.drop_collection(COLLECTION)
    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field("id", DataType.INT64, is_primary=True)
    schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=DIM)
    schema.add_field("label", DataType.VARCHAR, max_length=64)
    index_params = client.prepare_index_params()
    index_params.add_index(field_name="embedding", index_type="HNSW", metric_type="COSINE", params={"M": 8, "efConstruction": 64})
    client.create_collection(COLLECTION, schema=schema, index_params=index_params)
    vectors = _vectors()
    rows = [{"id": i, "embedding": vector, "label": f"row-{i}"} for i, vector in enumerate(vectors)]
    client.insert(COLLECTION, rows)
    client.flush(COLLECTION)
    hits = client.search(COLLECTION, data=[vectors[3]], limit=3, output_fields=["label"])
    return {
        "phase": "create",
        "collection": COLLECTION,
        "dimension": DIM,
        "rows": len(rows),
        "first_query": [[hit["entity"]["label"] for hit in result] for result in hits],
        "flush_done": True,
    }


def verify(client: MilvusClient) -> dict:
    started = time.perf_counter()
    stats = client.get_collection_stats(COLLECTION)
    vectors = _vectors()
    hits = client.search(COLLECTION, data=[vectors[3]], limit=3, output_fields=["label"])
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    top = [[hit["entity"]["label"] for hit in result] for result in hits]
    ok = bool(top) and top[0][0] == "row-3"
    report = {
        "phase": "verify",
        "collection": COLLECTION,
        "row_count": stats.get("row_count"),
        "latency_ms": latency_ms,
        "top_labels": top,
        "index_survived_restart": ok,
    }
    if ok:
        client.drop_collection(COLLECTION)
        report["cleanup"] = "collection_dropped"
    return report


def main() -> int:
    phase = sys.argv[1] if len(sys.argv) > 1 else "verify"
    settings = get_settings()
    client = MilvusClient(uri=settings.milvus_uri)
    try:
        report = create(client) if phase == "create" else verify(client)
    finally:
        client.close()
    report["milvus_uri"] = settings.milvus_uri
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if phase == "verify" and not report.get("index_survived_restart"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
