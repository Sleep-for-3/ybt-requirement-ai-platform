r"""Regenerate T_5_1 requirement content with the M1 knowledge corpus.

Why: the content adopted in round 74 (content_version 3) was generated while
project 9 had **no** usable knowledge units, so every candidate carried
``evidence = []`` and ``claim_support.status = unknown``.  After M1 seeded 166
units, the same fields must be regenerated so the model can cite evidence and
the claim-support verifier can mark claims as supported.

Usage::

    cd backend
    $env:PYTHONPATH="."; .\.venv\Scripts\python.exe scripts\regenerate_t51.py --apply
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8011/api"
PROJECT_ID = 9
REQUIREMENT_ID = 30
OUT_DIR = Path(__file__).resolve().parent / "out" / "probe"
TOKEN_FILE = OUT_DIR / "token.txt"
FIELD_IDS = [978, 979, 980, 981, 982, 983, 984, 985, 987, 988, 989, 990, 991, 992, 993, 994, 995, 986]


def login() -> str:
    response = requests.post(f"{BASE}/auth/login", json={"username": "ybt-lead", "password": "Ybt#20261024lead"}, timeout=60)
    response.raise_for_status()
    token = response.json()["access_token"]
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    return token


def call(token: str, method: str, path: str, **kwargs):
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.request(method, f"{BASE}{path}", headers=headers, timeout=180, **kwargs)
    if response.status_code == 401:
        token = login()
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.request(method, f"{BASE}{path}", headers=headers, timeout=180, **kwargs)
    return response, token


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="actually enqueue generation (default: dry-run)")
    parser.add_argument("--poll-seconds", type=int, default=2400)
    args = parser.parse_args()

    token = login()
    status, token = call(token, "GET", f"/projects/{PROJECT_ID}/requirements-status")
    status.raise_for_status()
    item = next(row for row in status.json()["items"] if row["requirement_id"] == REQUIREMENT_ID)
    version = item["content_version"]
    print(json.dumps({"content_version": version, "requirement_version": item["requirement_version"],
                      "current_content_hash": item["current_content_hash"]}, ensure_ascii=False))
    if not args.apply:
        print("dry-run: would prepare generation for content_version", version)
        return

    idempotency = f"t51-20261026-evidence-v{version}-a"
    body = {"expected_content_version": version, "field_ids": FIELD_IDS,
            "sections": ["business", "lineage"], "idempotency_key": idempotency}
    prepared, token = call(token, "POST", f"/projects/{PROJECT_ID}/requirements/{REQUIREMENT_ID}/generation-inputs", json=body)
    print("generation-inputs", prepared.status_code)
    prepared.raise_for_status()
    input_row = prepared.json()
    evidence = input_row.get("evidence") or []
    print(json.dumps({"input_id": input_row["id"], "evidence_count": len(evidence),
                      "evidence_titles": [row.get("title") for row in evidence][:5]}, ensure_ascii=False))

    started, token = call(token, "POST", f"/projects/{PROJECT_ID}/requirements/{REQUIREMENT_ID}/generation-runs", json=body)
    print("generation-runs", started.status_code, started.text[:300])
    started.raise_for_status()
    run = started.json()

    deadline = time.time() + args.poll_seconds
    summary = None
    while time.time() < deadline:
        listing, token = call(token, "GET", f"/projects/{PROJECT_ID}/requirements/{REQUIREMENT_ID}/generation-runs")
        listing.raise_for_status()
        summary = listing.json()[0]
        counts = summary["counts"]
        print(time.strftime("%H:%M:%S"), summary["id"], summary["status"], counts, "total", summary["total"], flush=True)
        if summary["status"] in {"completed", "failed", "blocked", "partially_completed"}:
            break
        time.sleep(15)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "t51_regen_runs.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if summary is None:
        raise SystemExit("no generation summary returned")
    blocked = [row for row in summary["items"] if row["status"] in {"blocked", "failed"}]
    print(json.dumps({"run_id": summary["id"], "status": summary["status"], "counts": summary["counts"],
                      "blocked": [{"item_id": row["id"], "field_id": row["field_id"], "section": row["section"],
                                   "reason_code": row.get("reason_code"), "failure_detail": row.get("failure_detail")}
                                  for row in blocked]}, ensure_ascii=False, indent=2))
    print("started_run", json.dumps(run, ensure_ascii=False))


if __name__ == "__main__":
    main()
