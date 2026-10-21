"""检查混合检索真实返回结构（只看真实 Milvus + Embedding 链路是否按语义排序）。"""

import json
import urllib.request

BASE = "http://127.0.0.1:8011"


def call(path, payload=None, token=None, method="POST"):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read().decode() or "null")


def main() -> None:
    token = call("/api/auth/login", {"username": "vnext-smoke", "password": "VnextSmoke#2026"})["access_token"]
    for query in ["客户统一标识取哪个字段", "报送数据按哪天取数", "产品编号能不能代替客户号"]:
        body = call(
            "/api/projects/1/knowledge/hybrid-search",
            {"query": query, "top_k": 5, "retrieval_mode": "hybrid"},
            token,
        )
        print("=" * 30, query)
        print("KEYS:", list(body)[:12])
        items = body.get("items") or []
        for item in items:
            print(
                json.dumps(
                    {
                        k: item.get(k)
                        for k in ("final_score", "rerank_score", "score", "vector_score", "keyword_score",
                                  "rrf_score", "knowledge_unit_id", "title", "content", "match_reasons",
                                  "authority_rank", "lifecycle_status")
                        if k in item
                    },
                    ensure_ascii=False,
                )[:400]
            )


if __name__ == "__main__":
    main()
