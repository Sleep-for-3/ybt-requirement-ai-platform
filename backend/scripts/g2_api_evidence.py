"""G2 真机证据：hybrid-search 接口在展开开/关下的 top5 对照（只读，不写业务数据）。"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8011/api"
OUT = Path("scripts/out/retrieval")
OUT.mkdir(parents=True, exist_ok=True)

QUERIES = [
    ("processing", "E010005 科目类型 的加工逻辑是什么"),
    ("scenario", "一表通监管报送（20261024 跑批）场景下产品ID的业务口径是什么"),
    ("lineage", "产品ID这个字段来自哪个系统、哪张表的哪个字段"),
]


def login() -> str:
    response = requests.post(
        f"{BASE}/auth/login",
        json={"username": "ybt-lead", "password": "Ybt#20261024lead"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def main() -> int:
    token = login()
    headers = {"Authorization": f"Bearer {token}"}
    result = {"base": BASE, "queries": [], "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    for label, query in QUERIES:
        response = requests.post(
            f"{BASE}/projects/9/knowledge/hybrid-search",
            headers=headers,
            json={"query": query, "top_k": 5, "retrieval_mode": "hybrid"},
            timeout=120,
        )
        payload = response.json()
        items = payload.get("items") or payload.get("results") or []
        top = []
        for item in items[:5]:
            top.append(
                {
                    "unit_id": item.get("knowledge_unit_id") or item.get("chunk_id"),
                    "title": item.get("title"),
                    "document_id": item.get("document_id"),
                    "field_code": item.get("target_field_code"),
                    "knowledge_type": item.get("knowledge_type"),
                    "final_score": item.get("final_score"),
                }
            )
        log = payload.get("retrieval_log") or {}
        filters = log.get("filters_json") or {}
        result["queries"].append(
            {
                "label": label,
                "query": query,
                "status": response.status_code,
                "top5": top,
                "log": {
                    "query_type": log.get("query_type"),
                    "latency_ms": log.get("latency_ms"),
                    "query_variant_count": filters.get("query_variant_count"),
                    "intent": filters.get("intent"),
                    "scenario_hint": filters.get("scenario_hint"),
                    "fusion_strategy": filters.get("fusion_strategy"),
                    "rrf_k": filters.get("rrf_k"),
                    "authority_mode": filters.get("authority_mode"),
                },
            }
        )
        print(label, response.status_code, [row["unit_id"] for row in top])
    path = OUT / "g2_api_evidence.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
