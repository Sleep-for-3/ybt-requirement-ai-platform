"""一表通调研表 -> 监管字段需求文档 的真实链路驱动（create/generate/adopt/freeze/export）。

只做真实调用，不 mock：脚本版本号、字段 id 都从平台接口与目标表读取。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from e2e_20261024 import ApiError, Client  # noqa: E402

PROJECT_ID = 9
BASE = "http://127.0.0.1:8011"
USER = "ybt-lead"
PASSWORD = "Ybt#20261024lead"
DSN = "postgresql://ybt_dsh_handoff_v2:F6b8mDBi4tlx1VMDq7dBHuz4EHL6It0Q4vUMOOKc0831BWHR@127.0.0.1:5432/ybt_dsh_handoff_v2"
STATE = Path(__file__).with_name("_e2e_survey.json")
SCRIPT_NAME = "YBT_T_8_1.sql"


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def authed(client: Client, method: str, path: str, **kwargs):
    """后端重启会让旧 token 失效（401）：重登一次再重试，不要当成业务失败。"""

    try:
        return client.request(method, path, **kwargs)
    except ApiError as exc:
        if exc.status != 401:
            raise
        client.login(USER, PASSWORD)
        return client.request(method, path, **kwargs)


def target_fields() -> list[dict]:
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "select id, field_code, field_name from target_fields "
            "where project_id=%s and target_table_id=101 order by field_code",
            (PROJECT_ID,),
        )
        return [{"id": row[0], "field_code": row[1], "field_name": row[2]} for row in cur.fetchall()]


def template_version() -> int:
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "select id from template_versions where project_id=%s and parse_status='success' "
            "order by id desc limit 1",
            (PROJECT_ID,),
        )
        row = cur.fetchone()
    if row is None:
        raise SystemExit("no parsed template version in project")
    return int(row[0])


def script_version(client: Client) -> dict:
    options = authed(client, "GET", f"/api/projects/{PROJECT_ID}/requirements/script-options")
    for version in options.get("versions", []):
        if str(version.get("path", "")).endswith(SCRIPT_NAME):
            return version
    raise SystemExit(f"script version not found for {SCRIPT_NAME}")


def scenario_id(client: Client, state: dict) -> int:
    if state.get("scenario_id"):
        return int(state["scenario_id"])
    payload = {
        "scenario_code": "YBT20261024",
        "scenario_name": "一表通监管报送（20261024 跑批）",
        "scenario_type": "regulatory_reporting",
    }
    try:
        created = authed(client, "POST", f"/api/projects/{PROJECT_ID}/scenarios", json_body=payload)
        state["scenario_id"] = created["id"]
    except ApiError as exc:
        if exc.status != 409:
            raise
        rows = authed(client, "GET", f"/api/projects/{PROJECT_ID}/scenarios")
        items = rows if isinstance(rows, list) else rows.get("items", [])
        for item in items:
            if item.get("scenario_code") == payload["scenario_code"]:
                state["scenario_id"] = item["id"]
                break
    save_state(state)
    return int(state["scenario_id"])


def create(client: Client, state: dict) -> dict:
    version = script_version(client)
    fields = target_fields()
    preview = authed(client, "POST", f"/api/projects/{PROJECT_ID}/requirements/script-preview",
                     json_body={"script_version_ids": [version["id"]]})
    print("preview_hash:", preview["preview_hash"][:16], "targets:", [t["table_name"] for t in preview["targets"]],
          "rules:", len(preview["rules"]), "gaps:", len(preview["gaps"]))
    output_codes = {column for target in preview["targets"] for column in target["columns"]}
    bindings = {field["field_code"]: field["id"] for field in fields
                if any(str(field["field_code"]).lower() == str(code).lower() for code in output_codes)}
    print("bound fields:", len(bindings), "/", len(fields))
    created = authed(client, "POST", f"/api/projects/{PROJECT_ID}/requirements/from-scripts", json_body={
        "preview_hash": preview["preview_hash"],
        "script_version_ids": [version["id"]],
        "targets": [{
            "scope": {
                "name": "T_8_1 贷款借据 监管字段需求（跑批脚本生成）",
                "target_table_id": 101,
                "field_ids": [field["id"] for field in fields],
                "scenario_id": scenario_id(client, state),
            },
            "target_key": preview["targets"][0]["key"],
            "field_bindings": bindings,
            "template_version_id": int(state.get("template_version_id") or template_version()),
        }],
        "idempotency_key": f"e2e-survey-t81-{len(fields)}",
    })
    requirement = created["requirements"][0]
    state.update({"requirement_id": requirement["requirement_id"],
                  "content_version": requirement["content_version"],
                  "field_ids": [field["id"] for field in fields],
                  "script_version_ids": [version["id"]],
                  "bound_fields": sorted(bindings)})
    save_state(state)
    print("requirement:", json.dumps(requirement, ensure_ascii=False))
    return state


def runs(client: Client, requirement_id: int) -> dict:
    return authed(client, "GET", f"/api/projects/{PROJECT_ID}/requirements/{requirement_id}/generation-runs")


def generate(client: Client, state: dict) -> dict:
    requirement_id = state["requirement_id"]
    created = authed(client, "POST", f"/api/projects/{PROJECT_ID}/requirements/{requirement_id}/generation-runs",
                     json_body={
                         "expected_content_version": state["content_version"],
                         "field_ids": state["field_ids"],
                         "sections": ["business", "lineage"],
                         "idempotency_key": f"e2e-survey-gen-{state['content_version']}",
                     })
    print("generation run:", json.dumps(created, ensure_ascii=False)[:400])
    state["input_id"] = created.get("input_id") or created.get("id")
    save_state(state)
    for _ in range(160):
        payload = runs(client, requirement_id)
        statuses = _status_counts(payload)
        print("statuses:", statuses, flush=True)
        if not statuses.get("pending") and not statuses.get("running") and not statuses.get("queued"):
            return payload
        time.sleep(20)
    raise SystemExit("generation did not finish in time")


def _status_counts(payload: dict) -> dict:
    counts: dict[str, int] = {}
    items = payload.get("items") if isinstance(payload, dict) else payload
    runs_list = (items or {}).get("runs") if isinstance(items, dict) else items
    for run in runs_list or []:
        for item in run.get("items") or []:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
    return counts


def post_fields(client: Client, path: str, fields: dict[str, str], *, timeout: int = 600):
    """纯文本 multipart POST，返回 (body, headers)；导出需要读响应头里的产物身份。"""

    import urllib.request

    boundary = "----e2e-survey-boundary"
    chunks = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        for name, value in fields.items()
    ]
    chunks.append(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        f"{client.base}{path}",
        data=b"".join(chunks),
        headers=client._headers({"Content-Type": f"multipart/form-data; boundary={boundary}"}),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), dict(response.headers)


def freeze(client: Client, state: dict) -> dict:
    """冻结草稿：导出只接受冻结内容，未冻结的正文不能当正式文档来源。"""

    requirement_id = state["requirement_id"]
    # 冻结的乐观锁用「需求范围版本」(requirements.version)，不是正文的 content_version；
    # expected_hash 是当前文档内容的摘要（/document 返回的 content_hash）。
    current = authed(client, "GET", f"/api/projects/{PROJECT_ID}/requirements/{requirement_id}/document")
    scope_version = (current.get("requirement") or {}).get("version")
    snapshot = authed(client, "POST", f"/api/projects/{PROJECT_ID}/requirements/{requirement_id}/snapshots",
                      json_body={"expected_version": scope_version,
                                 "expected_hash": current.get("content_hash")})
    state["snapshot_id"] = snapshot["id"]
    state["snapshot_hash"] = snapshot.get("content_hash")
    save_state(state)
    print("snapshot:", json.dumps(snapshot, ensure_ascii=False)[:400])
    return snapshot


def export(client: Client, state: dict) -> dict:
    out_dir = Path(__file__).resolve().parent / "out"
    out_dir.mkdir(exist_ok=True)
    results = {}
    for label, fmt, layout in (("docx", "docx", "standard"),
                               ("xlsx-standard", "xlsx", "standard"),
                               ("xlsx-survey", "xlsx", "survey")):
        payload, headers = post_fields(
            client, f"/api/projects/{PROJECT_ID}/requirements/{state['requirement_id']}/exports",
            {"format": fmt, "layout": layout, "source_kind": "draft_snapshot",
             "source_id": str(state["snapshot_id"])},
        )
        lowered = {key.lower(): value for key, value in headers.items()}
        path = out_dir / f"T_8_1-requirement-{label}.{fmt}"
        path.write_bytes(payload)
        results[label] = {"path": str(path), "bytes": len(payload),
                          "render_artifact_id": lowered.get("x-requirement-render-artifact-id"),
                          "file_sha256": lowered.get("x-requirement-rendered-file-sha256"),
                          "renderer": lowered.get("x-requirement-renderer-version")}
        print(label, results[label])
    state["exports"] = results
    save_state(state)
    return results


def adopt(client: Client, state: dict) -> dict:
    """把已完成的候选按变化字段采纳进正文。

    只采纳"确有变化"的字段；被阻断/失败的条目如实列出来，不用占位文字顶替，
    人工仍然要在工作台复核。
    """

    requirement_id = state["requirement_id"]
    payload = runs(client, requirement_id)
    runs_list = payload.get("runs") if isinstance(payload, dict) else payload
    # 采纳接口要求所有候选来自同一次固定生成输入，因此只取当前 input 的那一次运行。
    target_input = state.get("input_id")
    scoped = [
        run for run in runs_list or []
        if target_input is None or run.get("id") == target_input or run.get("input_id") == target_input
    ] or list(runs_list or [])[:1]
    selections: list[dict] = []
    skipped: list[dict] = []
    for run in scoped:
        for item in run.get("items") or []:
            status = item.get("status")
            if status != "completed":
                skipped.append({"item_id": item.get("id"), "status": status,
                                "reason": item.get("reason_code")})
                continue
            detail = authed(client, "GET",
                            f"/api/projects/{PROJECT_ID}/requirements/{requirement_id}"
                            f"/generation-items/{item['id']}")
            fields = [change["field"] for change in detail.get("changes") or []
                      if change.get("changed")]
            if not detail.get("candidate_hash") or not fields:
                skipped.append({"item_id": item.get("id"), "status": status,
                                "reason": "candidate_empty_or_unchanged"})
                continue
            selections.append({"item_id": detail["id"], "candidate_hash": detail["candidate_hash"],
                               "selected_fields": fields})
    if not selections:
        raise SystemExit("没有可采纳的候选；先确认生成结果")
    result = authed(client, "POST",
                    f"/api/projects/{PROJECT_ID}/requirements/{requirement_id}"
                    f"/generation-candidates/adopt",
                    json_body={"expected_content_version": state["content_version"],
                               "selections": selections})
    document = result.get("document") or {}
    state["content_version"] = document.get("content_version") or state["content_version"]
    save_state(state)
    summary = {"adopted": len(selections), "idempotent": result.get("idempotent"),
               "content_version": state["content_version"], "skipped": skipped}
    print("adopt:", json.dumps(summary, ensure_ascii=False)[:1200])
    return summary


def main(argv: list[str]) -> int:
    action = argv[0] if argv else "create"
    client = Client(BASE)
    client.login(USER, PASSWORD)
    state = load_state()
    if action == "create":
        create(client, state)
    elif action == "generate":
        generate(client, state)
    elif action == "adopt":
        adopt(client, state)
    elif action == "freeze":
        freeze(client, state)
    elif action == "export":
        export(client, state)
    elif action == "runs":
        print(json.dumps(runs(client, state["requirement_id"]), ensure_ascii=False)[:2000])
    else:
        raise SystemExit(f"unknown action {action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
