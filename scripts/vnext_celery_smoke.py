"""真实 Celery 队列冒烟：API(TASK_QUEUE_PROVIDER=celery) → Redis broker → celery worker → 完成。

证据：job 状态流转（queued/running/succeeded）、celery_task_id、索引重建后 chunk_count、
混合检索命中；不使用 inline 队列，也不 Mock。需要同时运行 uvicorn(8011) 与 celery worker。
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8011"
OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "audit" / "VNEXT_REAL_CELERY_QUEUE-20261021.json"
TERMINAL = {"completed", "succeeded", "failed", "cancelled", "dead_letter", "timed_out"}


def call(path, payload=None, token=None, method="POST", timeout=120):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode() or "null")


def main() -> int:
    report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    try:
        token = call("/api/auth/login", {"username": "vnext-smoke", "password": "VnextSmoke#2026"})["access_token"]

        t0 = time.time()
        submitted = call("/api/projects/1/semantic-index/reindex", {"force": True}, token, timeout=120)
        job_id = submitted.get("job_id")
        report["submission"] = {
            "http_response": submitted,
            "submit_latency_ms": round((time.time() - t0) * 1000, 1),
        }

        states, deadline = [], time.time() + 240
        job = None
        while time.time() < deadline and job_id:
            job = call(f"/api/jobs/{job_id}", token=token, method="GET")
            states.append({"status": job.get("status"), "at": job.get("updated_at")})
            if job.get("status") in TERMINAL:
                break
            time.sleep(1.5)
        report["job"] = {
            "job_id": job_id,
            "final_status": (job or {}).get("status"),
            "celery_task_id": (job or {}).get("celery_task_id"),
            "job_type": (job or {}).get("job_type"),
            "queued_at": (job or {}).get("queued_at"),
            "started_at": (job or {}).get("started_at"),
            "finished_at": (job or {}).get("finished_at"),
            "state_trail": states[:20],
            "result_summary": (job or {}).get("result_summary_json") or (job or {}).get("result_summary"),
            "error_message": (job or {}).get("error_message"),
        }

        status = call("/api/projects/1/semantic-index/status", token=token, method="GET")
        report["index_status"] = {
            "mode": status.get("mode"),
            "document_count": status.get("document_count"),
            "chunk_count": status.get("chunk_count"),
            "active_index_id": (status.get("active_index") or {}).get("id"),
            "milvus_health": status.get("milvus_health"),
        }

        hits = call(
            "/api/projects/1/knowledge/hybrid-search",
            {"query": "客户统一标识能不能用产品编号代替", "top_k": 3, "retrieval_mode": "hybrid"},
            token,
        )
        items = hits.get("items") or []
        report["retrieval"] = {
            "item_count": len(items),
            "top": [
                {"final_score": item.get("final_score"), "content": (item.get("content") or "")[:80]}
                for item in items[:3]
            ],
        }
        report["status"] = "real" if report["job"]["final_status"] == "completed" else "incomplete"
    except urllib.error.HTTPError as exc:
        report["status"] = "error"
        report["error"] = f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:600]}"
    except Exception as exc:  # pragma: no cover
        report["status"] = "error"
        report["error"] = f"{type(exc).__name__}: {exc}"

    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8")
    return 0 if report.get("status") == "real" else 1


if __name__ == "__main__":
    sys.exit(main())
