"""真实组件知识闭环冒烟：登录 → 上传合成监管材料 → 语义索引重建 → 混合检索。

验证的是真实 PostgreSQL + 真实 Milvus + 真实 Embedding 服务 + 真实 DeepSeek 之外的检索链路，
不使用 Mock。仅在本地隔离冒烟库执行（项目 1 / VNEXT 真实组件冒烟 20261021）。
"""

import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = "http://127.0.0.1:8011"
PROJECT_ID = 1
USERNAME = "vnext-smoke"
PASSWORD = "VnextSmoke#2026"
FILE = Path(__file__).resolve().parents[1] / "dev_storage_local" / "vnext_smoke_docs" / "ybt_customer_id_policy.md"
OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "audit" / "VNEXT_REAL_KNOWLEDGE_SMOKE-20261021.json"


def call(path, payload=None, token=None, method="POST", timeout=900, data=None, content_type="application/json"):
    body = data if data is not None else (json.dumps(payload).encode() if payload is not None else None)
    headers = {}
    if body is not None:
        headers["Content-Type"] = content_type
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.status, json.loads(response.read().decode() or "null")


def login() -> str:
    _, body = call("/api/auth/login", {"username": USERNAME, "password": PASSWORD})
    return body["access_token"]


def upload(token: str) -> dict:
    content = FILE.read_bytes()
    boundary = "----b" + uuid.uuid4().hex
    parts = []
    for name, value in [
        ("knowledge_type", "regulatory_policy"),
        ("knowledge_scope", "project"),
        ("confidentiality_level", "internal"),
        ("source_category", "regulatory_formal"),
    ]:
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode())
    parts.append(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{FILE.name}"\r\n'
            "Content-Type: text/markdown\r\n\r\n"
        ).encode()
        + content
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    status, body = call(
        f"/api/projects/{PROJECT_ID}/knowledge/documents/upload",
        token=token,
        data=b"".join(parts),
        content_type=f"multipart/form-data; boundary={boundary}",
        timeout=1200,
    )
    return {"http_status": status, "document": body}


def main() -> int:
    report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "project_id": PROJECT_ID}
    steps = report["steps"] = {}
    try:
        t0 = time.time()
        token = login()
        steps["login"] = {"status": "ok", "latency_ms": round((time.time() - t0) * 1000, 1)}

        uploaded = upload(token)
        doc = uploaded["document"]
        doc_id = doc.get("id")
        steps["upload"] = {
            "http_status": uploaded["http_status"],
            "document_id": doc_id,
            "document_status": doc.get("document_status"),
            "version": doc.get("current_version_no"),
        }
        if not doc_id:
            report["status"] = "error"
            report["error"] = "upload did not create a document (job not completed?)"
            return _finish(report)

        version_id = ((doc.get("parse_summary_json") or {}).get("candidate_version_id"))
        steps["upload_parse"] = {
            "parse_status": doc.get("parse_status"),
            "document_status": doc.get("document_status"),
            "candidate_version_id": version_id,
        }

        # 治理流程：送审 → 审核 → 生效（真实 Milvus 模式要求生效版本才会进入语料）
        for step, path in [
            ("submit_review", f"/api/knowledge/document-versions/{version_id}/submit-review?project_id={PROJECT_ID}"),
            ("review", f"/api/knowledge/document-versions/{version_id}/review?project_id={PROJECT_ID}"),
            ("activate", f"/api/knowledge/document-versions/{version_id}/activate?project_id={PROJECT_ID}"),
        ]:
            try:
                _, body = call(path, {}, token, timeout=300)
                steps[step] = {"lifecycle_status": body.get("lifecycle_status") if isinstance(body, dict) else body}
            except urllib.error.HTTPError as exc:
                steps[step] = {"error": f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}"}
                if step in {"activate"}:
                    raise

        t0 = time.time()
        status, reindex = call(f"/api/projects/{PROJECT_ID}/semantic-index/reindex", {"force": True}, token, timeout=1800)
        steps["reindex"] = {"http_status": status, "response": reindex, "latency_ms": round((time.time() - t0) * 1000, 1)}

        t0 = time.time()
        _, index_status = call(f"/api/projects/{PROJECT_ID}/semantic-index/status", method="GET", token=token)
        steps["index_status"] = {
            "mode": index_status.get("mode"),
            "formal_ready": index_status.get("formal_ready"),
            "vector_store": index_status.get("vector_store"),
            "vector_dimension": index_status.get("vector_dimension"),
            "document_count": index_status.get("document_count"),
            "chunk_count": index_status.get("chunk_count"),
            "active_index_id": (index_status.get("active_index") or {}).get("id"),
            "active_index_current": index_status.get("active_index_current"),
            "milvus_health": index_status.get("milvus_health"),
            "latency_ms": round((time.time() - t0) * 1000, 1),
        }

        queries = ["客户统一标识取哪个字段", "报送数据按哪天取数"]
        hits = []
        for query in queries:
            t0 = time.time()
            status, body = call(
                f"/api/projects/{PROJECT_ID}/knowledge/hybrid-search",
                {"query": query, "top_k": 5, "retrieval_mode": "hybrid"},
                token,
                timeout=600,
            )
            items = body.get("items") or body.get("results") or []
            hits.append({
                "query": query,
                "http_status": status,
                "item_count": len(items),
                "top_titles": [item.get("document_title") or item.get("title") for item in items[:3]],
                "top_scores": [round(item.get("score", 0), 4) for item in items[:3]],
                "latency_ms": round((time.time() - t0) * 1000, 1),
            })
        steps["retrieval"] = {"cases": hits, "hit_at_5": sum(1 for h in hits if h["item_count"] > 0) / len(hits)}
        report["status"] = "real" if steps["index_status"]["chunk_count"] else "partial"
    except urllib.error.HTTPError as exc:
        report["status"] = "error"
        report["error"] = f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:800]}"
    except Exception as exc:  # pragma: no cover - 冒烟失败路径
        report["status"] = "error"
        report["error"] = f"{type(exc).__name__}: {exc}"
    return _finish(report)


def _finish(report: dict) -> int:
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8")
    return 0 if report.get("status") == "real" else 1


if __name__ == "__main__":
    sys.exit(main())
