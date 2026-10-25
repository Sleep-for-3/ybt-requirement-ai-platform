"""Real-component semantic index run against the local embedding server and Milvus.

Steps (all against a live backend on 127.0.0.1:8011):
1. upload a knowledge workbook with one long clause row (forces fragmentation),
2. wait for the ingestion job, then activate the version,
3. submit a fragment-strategy reindex and wait for it,
4. verify the index version, the vector record bookkeeping and the fragment
   metadata that a hit resolves back to.
"""

from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import requests
from openpyxl import Workbook

BASE = "http://127.0.0.1:8011"
USERNAME = "ybt-lead"
PASSWORD = "Ybt#20261024lead"
PROJECT_ID = 9
LONG_TEXT = (
    "贷款余额的统计口径按借据分户账逐笔汇总，包含本金余额与已计提未结清的应收利息，"
    "剔除已核销、已转让以及经审批确认的以物抵债抵销部分；集团客户内部的委托贷款与"
    "联合贷款按实际出资比例计入本机构份额，不得重复报送全额；"
) * 12


def login() -> dict[str, str]:
    response = requests.post(f"{BASE}/api/auth/login", json={"username": USERNAME, "password": PASSWORD}, timeout=30)
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def workbook() -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "贷款口径"
    sheet.append(["字段代码", "字段名称", "口径说明"])
    sheet.append(["LOAN_BAL", "贷款余额", LONG_TEXT])
    sheet.append(["LOAN_STATUS", "贷款状态", "按五级分类口径报送：正常、关注、次级、可疑、损失。"])
    sheet.append(["DUEBILL_NO", "借据号", "借据唯一编号，24 位，左补零。"])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def wait_job(headers: dict[str, str], job_id: int, timeout: int = 900) -> dict:
    deadline = time.time() + timeout
    job: dict = {}
    while time.time() < deadline:
        response = requests.get(f"{BASE}/api/jobs/{job_id}", headers=headers, timeout=60)
        if response.ok:
            job = response.json()
            if job.get("status") in {"completed", "failed", "cancelled"}:
                return job
        time.sleep(8)
    return job


def main() -> int:
    headers = login()

    files = {"file": ("real-fragment-check.xlsx", workbook(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    form = {"knowledge_type": "regulatory_policy", "knowledge_scope": "project", "confidentiality_level": "internal"}
    upload = requests.post(f"{BASE}/api/projects/{PROJECT_ID}/knowledge/documents/upload", headers=headers, files=files, data=form, timeout=120)
    print("upload:", upload.status_code)
    upload.raise_for_status()
    ingestion_job = upload.json()
    print("ingestion_job:", ingestion_job.get("id"), ingestion_job.get("status"))
    finished = wait_job(headers, ingestion_job["id"])
    print("ingestion:", finished.get("status"), (finished.get("error_message") or "")[:200])

    documents = requests.get(f"{BASE}/api/projects/{PROJECT_ID}/knowledge/documents", headers=headers, timeout=60).json()
    document = next(item for item in documents if item.get("file_name") == "real-fragment-check.xlsx")
    versions = requests.get(f"{BASE}/api/knowledge/documents/{document['id']}/versions", params={"project_id": PROJECT_ID}, headers=headers, timeout=60).json()
    version = versions[0]
    print("document:", document["id"], "version:", version["id"], version.get("parse_status"), "units:", (version.get("parse_summary_json") or {}).get("unit_count"))
    if version.get("parse_status") in {"parsed", "parsed_with_warnings"} or version.get("lifecycle_status") == "pending_review":
        activate = requests.post(f"{BASE}/api/knowledge/document-versions/{version['id']}/activate", params={"project_id": PROJECT_ID}, headers=headers, timeout=60)
        print("activate:", activate.status_code, activate.text[:160])

    reindex = requests.post(
        f"{BASE}/api/projects/{PROJECT_ID}/semantic-index/reindex",
        headers=headers,
        json={"chunk_strategy": "knowledge-fragment-v1", "fragment_max_tokens": 480, "force": True},
        timeout=120,
    )
    print("reindex:", reindex.status_code, reindex.text[:200])
    if reindex.status_code >= 400:
        return 1
    reindex_job = reindex.json()
    result = wait_job(headers, reindex_job["id"], timeout=1800)
    print("reindex job:", result.get("status"), (result.get("error_message") or "")[:300])
    print("reindex result:", json.dumps(result.get("result_summary_json"), ensure_ascii=False)[:800])

    status = requests.get(f"{BASE}/api/projects/{PROJECT_ID}/semantic-index/status", headers=headers, timeout=60).json()
    print("status:", json.dumps({key: status.get(key) for key in ("mode", "milvus_health", "active_index_current", "chunk_count", "document_count")}, ensure_ascii=False)[:600])
    active = status.get("latest_index") or {}
    print("latest_index:", json.dumps(active, ensure_ascii=False)[:900])

    search = requests.post(
        f"{BASE}/api/projects/{PROJECT_ID}/knowledge/planned-search",
        headers=headers,
        json={"query": "贷款余额 剔除已核销 委托贷款 出资比例", "top_k": 5},
        timeout=120,
    )
    items = (search.json().get("items") if search.ok else []) or []
    print("search:", search.status_code, "items:", len(items))
    for item in items[:3]:
        locator = item.get("locator") or {}
        print(json.dumps({"citation_id": item.get("citation_id"), "title": item.get("title"), "fragment": {k: locator.get(k) for k in ("fragment_index", "fragment_char_start", "fragment_char_end", "parent_unit_id") if k in locator}}, ensure_ascii=False))

    hybrid = requests.post(
        f"{BASE}/api/projects/{PROJECT_ID}/knowledge/hybrid-search",
        headers=headers,
        json={"query": "贷款余额 剔除已核销 委托贷款 出资比例", "top_k": 5},
        timeout=120,
    )
    hybrid_items = (hybrid.json().get("items") if hybrid.ok else []) or []
    print("hybrid:", hybrid.status_code, "items:", len(hybrid_items))
    hybrid_meta = []
    for item in hybrid_items[:3]:
        locator = item.get("locator") or {}
        hybrid_meta.append({k: locator.get(k) for k in ("fragment_index", "fragment_char_start", "fragment_char_end", "parent_unit_id") if k in locator})
    print("hybrid fragment meta:", json.dumps(hybrid_meta, ensure_ascii=False))

    out = Path("scripts/out/semantic-index-real-run.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "document_id": document["id"],
                "version_id": version["id"],
                "unit_count": (version.get("parse_summary_json") or {}).get("unit_count"),
                "ingestion_job": {"id": ingestion_job.get("id"), "status": finished.get("status")},
                "reindex_job": {"id": reindex_job.get("id"), "status": result.get("status"), "result": result.get("result_summary_json")},
                "status": status,
                "search_items": items,
                "hybrid_items": hybrid_items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("written:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
