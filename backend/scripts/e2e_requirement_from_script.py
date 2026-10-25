"""真实链路（一表通 20261024）：由 GBase 跑批脚本生成监管字段需求 → 生成候选 → 导出。

分步执行，每步打印结构化结果，便于在真实组件上定位问题：

    .venv/Scripts/python.exe scripts/e2e_requirement_from_script.py preview
    .venv/Scripts/python.exe scripts/e2e_requirement_from_script.py create
    .venv/Scripts/python.exe scripts/e2e_requirement_from_script.py generate
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND.parent / "scripts"))

from e2e_20261024 import BASE, PASSWORD, USER, Client  # noqa: E402

PROJECT_ID = 9
IMPORT_BATCH_ID = 4
SCRIPT_NAME = "YBT_T_8_1.sql"
TABLE_CODE = "T_8_1"
TEMPLATE_VERSION_ID = 2
STATE = BACKEND / "_e2e_state.json"


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def find_version(client: Client, name: str) -> int:
    options = client.request("GET", f"/api/projects/{PROJECT_ID}/requirements/script-options")
    for item in options.get("versions") or []:
        if item.get("path") == name:
            return int(item["id"])
    raise SystemExit(f"script not found: {name}")


def preview(client: Client, state: dict) -> dict:
    version_id = state.get("script_version_id") or find_version(client, SCRIPT_NAME)
    state["script_version_id"] = version_id
    payload = client.request("POST", f"/api/projects/{PROJECT_ID}/requirements/script-preview",
                             json_body={"script_version_ids": [version_id]})
    state["preview"] = payload
    save_state(state)
    print("preview_hash:", payload.get("preview_hash"))
    for target in payload.get("targets") or []:
        print("target:", target.get("key"), target.get("table_name"),
              "columns:", len(target.get("columns") or []), (target.get("columns") or [])[:8])
    print("gap count:", len(payload.get("gaps") or []))
    for gap in (payload.get("gaps") or [])[:6]:
        print("  gap:", str(gap)[:160])
    print("rules:", len(payload.get("rules") or []))
    return payload


def _database_url() -> str:
    for line in (BACKEND / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("DATABASE_URL not found in .env")


def load_target_table(code: str) -> tuple[dict, list[dict]]:
    """读取监管目标表与其字段（平台没有列表/详情 REST 端点，这里直连同一个库）。"""

    from sqlalchemy import create_engine, text

    engine = create_engine(_database_url())
    with engine.connect() as conn:
        row = conn.execute(text(
            "select id, table_code, table_name from target_tables where project_id=:p and table_code=:c"
        ), {"p": PROJECT_ID, "c": code}).first()
        if row is None:
            raise SystemExit(f"target table {code} not found")
        fields = conn.execute(text(
            "select id, field_code, field_name from target_fields where target_table_id=:t order by id"
        ), {"t": row.id}).all()
    return {"id": row.id, "table_code": row.table_code, "table_name": row.table_name}, [
        {"id": item.id, "field_code": item.field_code, "field_name": item.field_name} for item in fields
    ]


def ensure_scenario(client: Client, state: dict) -> int:
    if state.get("scenario_id"):
        return state["scenario_id"]
    existing = client.request("GET", f"/api/projects/{PROJECT_ID}/scenarios")
    items = existing.get("items") if isinstance(existing, dict) else existing
    for item in items or []:
        if item.get("scenario_code") == "YBT20261024":
            state["scenario_id"] = item["id"]
            save_state(state)
            return item["id"]
    created = client.request("POST", f"/api/projects/{PROJECT_ID}/scenarios", json_body={
        "scenario_code": "YBT20261024",
        "scenario_name": "一表通监管报送（20261024 跑批）",
        "scenario_type": "regulatory_reporting",
    })
    state["scenario_id"] = created["id"]
    save_state(state)
    return created["id"]


def create(client: Client, state: dict) -> dict:
    preview_payload = state.get("preview") or preview(client, state)
    table, items = load_target_table(TABLE_CODE)
    print("target table:", {k: table.get(k) for k in ("id", "table_code", "table_name")}, "fields:", len(items))
    by_code = {}
    for field in items:
        by_code.setdefault(field["field_code"], field["id"])
    target = next(t for t in preview_payload["targets"] if t.get("table_name") == TABLE_CODE)
    bindings = {column: by_code[column] for column in target["columns"] if column in by_code}
    print("bindings:", len(bindings), "of columns", len(target["columns"]))
    state["target_table_id"] = table["id"]
    state["field_ids"] = sorted({field["id"] for field in items})
    state["bindings"] = bindings
    save_state(state)
    body = {
        "script_version_ids": [state["script_version_id"]],
        "idempotency_key": f"e2e-{TABLE_CODE}-{state['script_version_id']}",
        "preview_hash": preview_payload["preview_hash"],
        "import_batch_id": IMPORT_BATCH_ID,
        "targets": [{
            "scope": {
                "name": f"{TABLE_CODE} 监管字段需求（由跑批脚本生成）",
                "target_table_id": table["id"],
                "field_ids": state["field_ids"],
                "scenario_id": state["scenario_id"],
                "document_ids": [],
                "source_table_ids": [],
                "mart_table_ids": [],
            },
            "template_version_id": TEMPLATE_VERSION_ID,
            "target_key": target["key"],
            "field_bindings": bindings,
        }],
    }
    created = client.request("POST", f"/api/projects/{PROJECT_ID}/requirements/from-scripts", json_body=body)
    print("created:", json.dumps(created, ensure_ascii=False)[:600])
    requirement = (created.get("requirements") or [{}])[0]
    state["requirement_id"] = requirement.get("requirement_id")
    state["content_version"] = requirement.get("content_version")
    save_state(state)
    return created



def authed(client: Client, method: str, path: str, **kwargs):
    """会话失效时重登一次再重试；后端重启会让旧 token 变成 401，不能当成业务失败。"""

    from e2e_20261024 import ApiError

    try:
        return client.request(method, path, **kwargs)
    except ApiError as exc:
        if exc.code != 401:
            raise
        client.login(USER, PASSWORD)
        return client.request(method, path, **kwargs)


def generate(client: Client, state: dict) -> dict:
    import time

    requirement_id = state["requirement_id"]
    content_version = state["content_version"]
    created = authed(client, "POST", f"/api/projects/{PROJECT_ID}/requirements/{requirement_id}/generation-runs",
                             json_body={
                                 "expected_content_version": content_version,
                                 "field_ids": state["field_ids"],
                                 "sections": ["business", "lineage"],
                                 "idempotency_key": f"e2e-t81-v{content_version}-gen1",
                             })
    print("input:", json.dumps(created, ensure_ascii=False)[:500])
    state["input_id"] = created.get("input_id") or created.get("id")
    save_state(state)
    for _ in range(120):
        runs = authed(client, "GET", f"/api/projects/{PROJECT_ID}/requirements/{requirement_id}/generation-runs")
        items = runs.get("items") if isinstance(runs, dict) else runs
        runs_list = (items or {}).get("runs") if isinstance(items, dict) else None
        print("runs:", json.dumps(runs, ensure_ascii=False)[:300])
        time.sleep(15)
        if _all_done(runs):
            break
    return runs


def _all_done(payload) -> bool:
    text = json.dumps(payload, ensure_ascii=False)
    return '"status": "running"' not in text and '"status": "queued"' not in text

def main(argv: list[str]) -> int:
    action = argv[0] if argv else "preview"
    client = Client(BASE)
    client.login(USER, PASSWORD)
    state = load_state()
    if action == "preview":
        preview(client, state)
    elif action == "create":
        ensure_scenario(client, state)
        create(client, state)
    elif action == "generate":
        generate(client, state)
    else:
        raise SystemExit(f"unknown action {action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
