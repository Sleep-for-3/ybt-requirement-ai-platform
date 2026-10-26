r"""Regenerate T_5_1 candidates in field batches, then adopt each batch.

Why batches: the generation input carries the frozen script basis, the field
records and the field-scoped evidence.  Eighteen fields together exceed the
128KB safety budget even after field scoping, so the requirement is regenerated
in batches of 3-4 fields (measured 49-108KB per batch).  Every batch is a real
API run: generation-inputs -> generation-runs -> poll -> adopt, and the adopt
raises the requirement content version, so the next batch must re-read
``delivery-status`` for ``content_version``.

Usage:
  python scripts/regenerate_t51_batched.py --dry-run
  python scripts/regenerate_t51_batched.py --apply [--only 0,1]

Evidence: every batch writes ``scripts/out/retrieval/regen_batch_<n>.json`` and
the run writes ``scripts/out/retrieval/regenerate_t51_summary.json``.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8011/api"
PROJECT = 9
REQUIREMENT = 30
TOKEN_FILE = Path(__file__).resolve().parent / "out" / "probe" / "token.txt"
OUT = Path(__file__).resolve().parent / "out" / "retrieval"

# 18 fields of T_5_1, grouped so that each batch stays inside the 128KB budget.
BATCHES = [
    [978, 979, 980],
    [981, 982, 983, 984],
    [985, 987, 988, 989],
    [990, 991, 992, 993],
    [994, 995, 986],
]
SECTION_FIELDS = {"business": ("business_definition", "final_content"),
                  "lineage": ("processing_logic", "final_content")}
SPECIAL_FIELDS = {"business": ("evidence",), "lineage": ("physical_references", "evidence")}
TERMINAL = {"completed", "partially_completed", "failed", "blocked"}


def login() -> str:
    response = requests.post(f"{BASE}/auth/login", json={"username": "ybt-lead", "password": "Ybt#20261024lead"}, timeout=60)
    response.raise_for_status()
    token = response.json()["access_token"]
    TOKEN_FILE.write_text(token, encoding="utf-8")
    return token


class Client:
    def __init__(self) -> None:
        self.token = TOKEN_FILE.read_text(encoding="utf-8").strip() if TOKEN_FILE.exists() else login()

    def request(self, method: str, path: str, **kwargs):
        for attempt in range(2):
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.request(method, BASE + path, headers=headers, timeout=180, **kwargs)
            if response.status_code == 401 and attempt == 0:
                self.token = login()
                continue
            return response
        return response

    def get(self, path: str, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs):
        return self.request("POST", path, **kwargs)


def content_version(client: Client) -> tuple[int, int]:
    response = client.get(f"/projects/{PROJECT}/requirements-status")
    response.raise_for_status()
    item = next(row for row in response.json()["items"] if row["requirement_id"] == REQUIREMENT)
    return item["content_version"], item["requirement_version"]


def run_batch(client: Client, index: int, field_ids: list[int], reuse_input: int | None = None, label: str = "") -> dict:
    version, requirement_version = content_version(client)
    if reuse_input is not None:
        input_id = reuse_input
        print(f"[batch {index}] reusing input={input_id} fields={field_ids}", flush=True)
    else:
        stamp = datetime.now().strftime("%H%M%S")
        body = {"expected_content_version": version, "field_ids": field_ids,
                "sections": ["business", "lineage"], "idempotency_key": f"t51batch{index}{label}-{stamp}"}
        prepared = client.post(f"/projects/{PROJECT}/requirements/{REQUIREMENT}/generation-inputs", json=body)
        if prepared.status_code // 100 != 2:
            raise SystemExit(f"batch {index}: generation-inputs failed {prepared.status_code} {prepared.text[:400]}")
        input_id = prepared.json()["id"]
        started = client.post(f"/projects/{PROJECT}/requirements/{REQUIREMENT}/generation-runs", json=body)
        if started.status_code // 100 != 2:
            raise SystemExit(f"batch {index}: generation-runs failed {started.status_code} {started.text[:400]}")
        job = started.json()
        print(f"[batch {index}] content_version={version} input={input_id} job={job.get('job_id')} fields={field_ids}", flush=True)

    deadline = time.time() + 2400
    summary = None
    while time.time() < deadline:
        response = client.get(f"/projects/{PROJECT}/requirements/{REQUIREMENT}/generation-runs")
        response.raise_for_status()
        runs = response.json()
        summary = next(run for run in runs if run["id"] == input_id)
        counts = summary["counts"]
        print(f"[batch {index}] {time.strftime('%H:%M:%S')} {summary['status']} {counts}", flush=True)
        if summary["status"] in TERMINAL:
            break
        time.sleep(15)
    if summary is None or summary["status"] not in TERMINAL:
        raise SystemExit(f"batch {index}: timeout waiting for generation")

    selections = []
    blocked = []
    for item in summary["items"]:
        if item["status"] == "blocked":
            blocked.append({"item_id": item["id"], "field_id": item["field_id"],
                            "section": item["section"], "reason_code": item.get("reason_code"),
                            "detail": item.get("failure_detail")})
            continue
        if item["status"] != "completed":
            continue
        detail = client.get(f"/projects/{PROJECT}/requirements/{REQUIREMENT}/generation-items/{item['id']}")
        if detail.status_code // 100 != 2:
            print(f"[batch {index}] item {item['id']} detail {detail.status_code}", flush=True)
            continue
        payload = detail.json()
        changes = payload.get("changes") or []
        selected = [change["field"] for change in changes
                    if change.get("changed") and isinstance(change.get("proposed"), str) and change["proposed"].strip()]
        if payload.get("evidence"):
            selected.append("evidence")
        if not selected:
            print(f"[batch {index}] item {item['id']} has no changed text, skipped", flush=True)
            continue
        selections.append({"item_id": item["id"], "candidate_hash": payload["candidate_hash"],
                           "selected_fields": selected, "detail": payload})

    record = {"batch": index, "content_version": version, "requirement_version": requirement_version,
              "input_id": input_id, "status": summary["status"], "counts": summary["counts"],
              "blocked": blocked, "selections": [{k: v for k, v in s.items() if k != "detail"} for s in selections]}
    if not selections:
        record["adopt"] = {"skipped": True}
        return record

    adopt_body = {"expected_content_version": version,
                  "selections": [{"item_id": s["item_id"], "candidate_hash": s["candidate_hash"],
                                  "selected_fields": s["selected_fields"], "replace_manual_fields": []}
                                 for s in selections]}
    adopted = client.post(f"/projects/{PROJECT}/requirements/{REQUIREMENT}/generation-candidates/adopt", json=adopt_body)
    record["adopt"] = {"status_code": adopted.status_code,
                       "body": adopted.json() if adopted.headers.get("content-type", "").startswith("application/json") else adopted.text[:500]}
    print(f"[batch {index}] adopt {adopted.status_code} selections={len(selections)}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"regen_batch_{index}.json").write_text(json.dumps({"record": record, "details": selections},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write to the platform (default: dry run)")
    parser.add_argument("--only", default="", help="comma separated batch indexes")
    parser.add_argument("--input", type=int, default=None, help="reuse an existing generation input id")
    parser.add_argument("--fields", default="", help="comma separated field ids; overrides BATCHES with one batch")
    parser.add_argument("--tag", default="", help="suffix for the regen_batch_<n>.json evidence file")
    args = parser.parse_args()
    client = Client()
    version, requirement_version = content_version(client)
    print(f"start content_version={version} requirement_version={requirement_version} batches={len(BATCHES)}", flush=True)
    batches = BATCHES
    if args.fields:
        batches = [[int(part) for part in args.fields.split(",") if part.strip()]]
    only = {int(part) for part in args.only.split(",") if part.strip()} if args.only else set(range(len(batches)))
    if not args.apply:
        for index, field_ids in enumerate(batches):
            print(f"  batch {index}: fields={field_ids}")
        print("dry run; pass --apply to execute")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    summary = []
    for index, field_ids in enumerate(batches):
        if index not in only:
            continue
        summary.append(run_batch(client, index, field_ids, reuse_input=args.input, label=args.tag))
        (OUT / "regenerate_t51_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", json.dumps([{"batch": r["batch"], "status": r["status"],
                               "adopt": (r.get("adopt") or {}).get("status_code"),
                               "blocked": len(r.get("blocked") or [])} for r in summary], ensure_ascii=False))


if __name__ == "__main__":
    main()
