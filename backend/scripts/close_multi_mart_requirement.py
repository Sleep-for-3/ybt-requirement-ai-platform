"""T_8_1 重跑后的收口：采纳 → 冻结 → 一表通调研表式导出 → 多集市映射核对。

用途：验证「同 sheet 多组集市列」解析出的多条 mart 映射能真实进入监管字段需求文档。
只做已经存在的动作（与页面按钮等价），不引入新的写库捷径。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8011"
USER = "ybt-lead"
PASSWORD = "Ybt#20261024lead"
PROJECT_ID = 9
REQUIREMENT_ID = 18
OUT = Path(__file__).resolve().parent / "out"


def login() -> str:
    response = requests.post(f"{BASE}/api/auth/login", json={"username": USER, "password": PASSWORD}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    return payload.get("access_token") or payload["accessToken"]


def get(token: str, path: str) -> dict:
    response = requests.get(f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, timeout=120)
    response.raise_for_status()
    return response.json()


def post(token: str, path: str, body: dict) -> dict:
    response = requests.post(
        f"{BASE}{path}", json=body, headers={"Authorization": f"Bearer {token}"}, timeout=600
    )
    if not response.ok:
        raise RuntimeError(f"{path} -> {response.status_code} {response.text[:400]}")
    return response.json()


def runs(token: str) -> list[dict]:
    payload = get(token, f"/api/projects/{PROJECT_ID}/requirements/{REQUIREMENT_ID}/generation-runs")
    return payload if isinstance(payload, list) else payload.get("runs") or []


def adopt(token: str, content_version: int) -> dict:
    latest = runs(token)[0]
    input_id = latest["id"]
    selections = []
    for item in latest.get("items") or []:
        if item.get("status") != "completed":
            continue
        detail = get(token, f"/api/projects/{PROJECT_ID}/requirements/{REQUIREMENT_ID}/generation-items/{item['id']}")
        changed = [change["field"] for change in detail.get("changes") or [] if change.get("changed")]
        if not changed:
            continue
        selections.append({"item_id": item["id"], "candidate_hash": detail["candidate_hash"], "selected_fields": changed})
    if not selections:
        return {"input_id": input_id, "adopted": 0}
    result = post(
        token,
        f"/api/projects/{PROJECT_ID}/requirements/{REQUIREMENT_ID}/generation-candidates/adopt",
        {"expected_content_version": content_version, "selections": selections},
    )
    return {"input_id": input_id, "selections": len(selections), "result": result}


def freeze(token: str) -> dict:
    document = get(token, f"/api/projects/{PROJECT_ID}/requirements/{REQUIREMENT_ID}/document")
    version = document["requirement"]["version"]
    snapshot = post(
        token,
        f"/api/projects/{PROJECT_ID}/requirements/{REQUIREMENT_ID}/snapshots",
        {"expected_version": version, "expected_hash": document["content_hash"]},
    )
    return {"document": document, "snapshot": snapshot}


def main() -> int:
    OUT.mkdir(exist_ok=True)
    token = login()
    action = sys.argv[1] if len(sys.argv) > 1 else "status"

    if action == "status":
        latest = runs(token)[0]
        print(json.dumps({k: latest.get(k) for k in ("id", "total", "counts", "status")}, ensure_ascii=False))
        return 0

    if action == "close":
        document = get(token, f"/api/projects/{PROJECT_ID}/requirements/{REQUIREMENT_ID}/document")
        adopted = adopt(token, document["requirement"]["content_version"])
        print("adopt:", json.dumps({k: adopted[k] for k in adopted if k != "result"}, ensure_ascii=False))
        frozen = freeze(token)
        snapshot = frozen["snapshot"]
        print("snapshot:", snapshot["id"], snapshot["content_hash"][:16])
        for layout, suffix in (("survey", "survey"), ("standard", "standard")):
            response = requests.post(
                f"{BASE}/api/projects/{PROJECT_ID}/requirements/{REQUIREMENT_ID}/exports",
                headers={"Authorization": f"Bearer {token}"},
                data={"format": "xlsx", "source_kind": "draft_snapshot", "source_id": str(snapshot["id"]), "layout": layout},
                timeout=600,
            )
            response.raise_for_status()
            path = OUT / f"T_8_1-{suffix}-multi-mart.xlsx"
            path.write_bytes(response.content)
            print(layout, len(response.content), response.headers.get("x-requirement-render-artifact-id"),
                  response.headers.get("x-requirement-renderer-version"))
        with (OUT / "T_8_1-multi-mart.json").open("w", encoding="utf-8") as handle:
            json.dump({"snapshot": snapshot, "adopted": {k: v for k, v in adopted.items() if k != "result"}}, handle,
                      ensure_ascii=False, indent=2)
        return 0

    raise SystemExit(f"unknown action: {action}")


if __name__ == "__main__":
    raise SystemExit(main())

