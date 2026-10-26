"""Adopt T_5_1 generation candidates (requirement 30) in one governed batch.

Why one batch: adopt_candidates() only accepts candidates whose generation input
content_version still equals requirement.content_version.  A second, later adopt has to
raise 409 ("候选属于旧内容版本，请重新生成").  The workbench UI behaves the same way:
candidates are queued in a basket and submitted through the batch endpoint once.

Usage:
    python scripts/adopt_t51_candidates.py            # dry-run: build + print the plan
    python scripts/adopt_t51_candidates.py --apply    # POST the batch adopt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8011/api"
PROJECT = 9
REQUIREMENT = 30
TOKEN_FILE = Path(__file__).resolve().parent / "out" / "probe" / "token.txt"
OUT_DIR = Path(__file__).resolve().parent / "out" / "probe"


def login() -> str:
    response = requests.post(
        f"{BASE}/auth/login",
        json={"username": "ybt-lead", "password": "Ybt#20261024lead"},
        timeout=30,
    )
    response.raise_for_status()
    token = response.json()["access_token"]
    TOKEN_FILE.write_text(token, encoding="utf-8")
    return token


def request(method: str, path: str, *, token: str, **kwargs):
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.request(method, f"{BASE}{path}", headers=headers, timeout=120, **kwargs)
    if response.status_code == 401:
        token = login()
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.request(method, f"{BASE}{path}", headers=headers, timeout=120, **kwargs)
    return response


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="actually POST the batch adopt")
    args = parser.parse_args()

    token = TOKEN_FILE.read_text(encoding="utf-8").strip() or login()

    status = request("GET", f"/projects/{PROJECT}/requirements-status", token=token)
    status.raise_for_status()
    item = next(row for row in status.json()["items"] if row["requirement_id"] == REQUIREMENT)
    content_version = item["content_version"]

    runs = request(
        "GET", f"/projects/{PROJECT}/requirements/{REQUIREMENT}/generation-runs", token=token
    )
    runs.raise_for_status()
    summary = runs.json()[0]
    completed = [row for row in summary["items"] if row["status"] == "completed"]
    blocked = [row for row in summary["items"] if row["status"] != "completed"]
    print(f"run={summary['id']} status={summary['status']} completed={len(completed)} blocked={len(blocked)}")

    selections = []
    details = {}
    for row in completed:
        detail_response = request(
            "GET",
            f"/projects/{PROJECT}/requirements/{REQUIREMENT}/generation-items/{row['id']}",
            token=token,
        )
        detail_response.raise_for_status()
        detail = detail_response.json()
        details[str(row["id"])] = detail
        fields = [change["field"] for change in detail["changes"]]
        if detail.get("physical_references"):
            fields.append("physical_references")
        if detail.get("evidence"):
            fields.append("evidence")
        if not fields:
            print(f"skip {row['id']}: candidate has no adoptable text field")
            continue
        if len(fields) > 4 or len(set(fields)) != len(fields):
            print(f"skip {row['id']}: unexpected selected_fields {fields}")
            continue
        selections.append(
            {
                "item_id": row["id"],
                "candidate_hash": detail["candidate_hash"],
                "selected_fields": fields,
                "replace_manual_fields": [],
            }
        )

    (OUT_DIR / "t51_adopt_plan.json").write_text(
        json.dumps(
            {
                "expected_content_version": content_version,
                "selections": selections,
                "details": details,
                "blocked": blocked,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"planned {len(selections)} selections against content_version={content_version}")
    for selection in selections:
        print(" ", selection["item_id"], selection["selected_fields"])

    if not args.apply:
        return 0

    response = request(
        "POST",
        f"/projects/{PROJECT}/requirements/{REQUIREMENT}/generation-candidates/adopt",
        token=token,
        json={"expected_content_version": content_version, "selections": selections},
    )
    print("adopt status", response.status_code)
    if response.status_code != 200:
        print(response.text[:4000])
        return 1
    body = response.json()
    revision = body["document"]["revision"]
    print("revision content_version", revision["content_version"], "status", revision["status"])
    (OUT_DIR / "t51_adopt_result.json").write_text(
        json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
