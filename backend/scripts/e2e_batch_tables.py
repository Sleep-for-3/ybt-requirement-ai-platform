r"""批量验收：把多张一表通基础表各跑一遍「脚本 → 需求 → 候选 → 采纳 → 冻结 → 导出」。

单张表跑通只能说明"能跑"，说明不了"稳定"。这个脚本按表循环，把每一步的
真实返回记下来（哪一步失败、失败原因、耗时），产出可直接引用的证据 JSON。

刻意不做的事：
- 不伪造候选正文：生成失败的项原样记为 blocked/failed，不做"填空"。
- 不替业务确认：采集范围/报送范围确认/EAST 差异写的是可从产物核对的事实，
  不确定的一律写"需业务确认"，导出页因此会显示待补充，而不是一段看似完整的话。

用法（在 `ai-platform/backend` 下）：

    $env:PYTHONPATH="."
    .\.venv\Scripts\python.exe scripts\e2e_batch_tables.py T_1_2 T_3_8 T_10_1 --max-wait 2400

参数是 table_code 列表；`--max-wait` 是单表等待生成的秒数上限。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND.parent / "scripts"))

from e2e_20261024 import BASE, ApiError, Client  # noqa: E402

OUT = BACKEND / "scripts" / "out"
EVIDENCE = BACKEND.parent / "docs" / "requirement-delivery-upgrade" / "evidence"
PROJECT_ID = 9
SECTIONS = ["business", "lineage"]
SECTION_FIELDS = {
    "business": ("business_definition", "final_content"),
    "lineage": ("processing_logic", "final_content"),
}
POLL_SECONDS = 20


def call(client: Client, method: str, path: str, **kwargs):
    """调接口并返回 (payload, error)。Client 成功时返解析后的 JSON，失败抛 ApiError。

    批量验收一张表要跑十几分钟，而访问令牌十几分钟就过期：令牌过期时自动重新登录
    再重试一次，否则轮询会在 401 上空转到超时（第一次批量验收就是这样废掉的）。
    """
    for attempt in range(2):
        try:
            return client.request(method, path, **kwargs), None
        except ApiError as exc:
            if exc.status == 401 and attempt == 0:
                client.login()
                continue
            return None, {"status": exc.status, "detail": exc.detail}


def load_context() -> dict:
    """直接从库里取目标表与脚本版本映射（平台没有 target-table 列表端点）。"""
    from app.core.database import SessionLocal
    from app.models import ScriptFile, ScriptFileVersion, TargetField, TargetTable

    db = SessionLocal()
    try:
        tables = {
            table.table_code: table
            for table in db.query(TargetTable).filter(TargetTable.project_id == PROJECT_ID).all()
        }
        table_ids = [table.id for table in tables.values()]
        fields: dict[int, list[int]] = {}
        codes: dict[int, str] = {}
        for field in db.query(TargetField).filter(TargetField.target_table_id.in_(table_ids)).all():
            fields.setdefault(field.target_table_id, []).append(field.id)
            codes[field.id] = field.field_code
        versions = {
            row[0]: row[1]
            for row in db.query(ScriptFile.file_name, ScriptFileVersion.id)
            .join(ScriptFileVersion, ScriptFileVersion.script_file_id == ScriptFile.id)
            .filter(ScriptFile.project_id == PROJECT_ID)
            .all()
        }
        return {"tables": tables, "fields": fields, "codes": codes, "versions": versions, "scenario_id": 2}
    finally:
        db.close()


def scope_texts(table_code: str, field_count: int, script_name: str) -> dict:
    return {
        "background": (
            f"{table_code} 的监管字段需求由跑批脚本 {script_name} 的静态解析结果生成，"
            "字段口径、来源表与加工逻辑取自脚本血缘与一表通调研表的集市映射。"
        ),
        "objective": (
            f"{table_code} 全部 {field_count} 个数据项纳入本次需求范围；"
            f"目标表由 {script_name} 写入监管集市。"
        ),
        "inclusion": (
            f"本表全部 {field_count} 个数据项；取数日期由跑批参数 DATA_DATE 决定"
            "（脚本中已参数化，未写死具体日期）。"
        ),
        "exclusion": "与 EAST 报送口径的差异尚未完成人工比对，需业务确认。",
    }


def preview(client: Client, script_version_id: int, table_code: str):
    body, error = call(
        client, "POST", f"/api/projects/{PROJECT_ID}/requirements/script-preview",
        json_body={"script_version_ids": [script_version_id]},
    )
    if error:
        raise RuntimeError(f"script-preview {error['status']}: {error['detail']}")
    target = None
    for item in body.get("targets") or []:
        if table_code in str(item.get("key")):
            target = item
            break
    if target is None:
        keys = [str(item.get("key")) for item in body.get("targets") or []]
        raise RuntimeError(f"预览里没有 {table_code} 的写入目标：{keys}")
    return body, target


def field_bindings(target: dict, field_codes: dict[int, str], table_field_ids: list[int]) -> dict[int, str]:
    """脚本输出列 → 目标字段：只绑定同名字段，其余保持未绑定（形成缺口，不猜）。"""
    by_code = {field_codes[field_id]: field_id for field_id in table_field_ids if field_id in field_codes}
    bindings: dict[int, str] = {}
    for column in [str(column) for column in target.get("columns") or []]:
        field_id = by_code.get(column)
        if field_id is not None:
            bindings[field_id] = column
    return bindings


def wait_items(client: Client, requirement_id: int, input_id: int, expected: int, max_wait: int, log) -> dict:
    started = time.time()
    last_state = None
    while time.time() - started < max_wait:
        payload, error = call(
            client, "GET", f"/api/projects/{PROJECT_ID}/requirements/{requirement_id}/generation-runs"
        )
        if error:
            log(f"  查询生成轮次失败 {error['status']}: {str(error['detail'])[:160]}")
            time.sleep(POLL_SECONDS)
            continue
        runs = payload.get("runs") if isinstance(payload, dict) else (payload or [])
        run = next((item for item in runs if item.get("id") == input_id), (runs or [None])[0])
        items: list[dict] = list((run or {}).get("items") or [])
        counts: dict[str, int] = {}
        for item in items:
            status = item.get("status", "?")
            counts[status] = counts.get(status, 0) + 1
        done = counts.get("completed", 0) + counts.get("blocked", 0) + counts.get("failed", 0)
        if counts != last_state:
            log(f"  生成进度 {counts}（{done}/{expected}）")
            last_state = counts
        if done >= expected:
            return {"items": items, "counts": counts, "seconds": round(time.time() - started, 1)}
        time.sleep(POLL_SECONDS)
    raise TimeoutError(f"等待生成超时（{max_wait}s），最后状态 {last_state}")


def adopt(client: Client, requirement_id: int, items: list[dict], input_id: int, log) -> dict:
    selections = []
    for item in items:
        if item.get("status") != "completed":
            continue
        body, error = call(
            client, "GET",
            f"/api/projects/{PROJECT_ID}/requirements/{requirement_id}/generation-items/{item['id']}",
        )
        if error:
            log(f"  候选详情读取失败 item={item['id']} {error['status']}")
            continue
        fields = [
            change.get("field")
            for change in (body.get("changes") or [])
            if change.get("changed") and change.get("field") in SECTION_FIELDS.get(item.get("section"), ())
        ]
        if not fields:
            continue
        candidate_hash = body.get("candidate_hash") or item.get("candidate_hash")
        if not candidate_hash:
            continue
        selections.append({
            "item_id": item["id"],
            "candidate_hash": candidate_hash,
            "selected_fields": fields,
        })
    if not selections:
        return {"adopted": 0, "skipped": "no-candidate-changes"}

    document, error = call(client, "GET", f"/api/projects/{PROJECT_ID}/requirements/{requirement_id}/document")
    if error:
        return {"adopted": 0, "error": f"{error['status']}: {str(error['detail'])[:300]}"}
    body, error = call(
        client, "POST",
        f"/api/projects/{PROJECT_ID}/requirements/{requirement_id}/generation-candidates/adopt",
        json_body={
            "expected_content_version": document["revision"]["content_version"],
            "selections": selections,
        },
    )
    if error:
        return {"adopted": 0, "error": f"{error['status']}: {str(error['detail'])[:300]}"}
    return {
        "adopted": body.get("adopted"),
        "content_version": (body.get("document") or {}).get("content_version") or body.get("content_version"),
        "keys": sorted(body.keys())[:8],
    }


def freeze(client: Client, requirement_id: int) -> dict:
    document, error = call(client, "GET", f"/api/projects/{PROJECT_ID}/requirements/{requirement_id}/document")
    if error:
        return {"error": f"document {error['status']}: {str(error['detail'])[:200]}"}
    # 平台没有 GET /requirements/{id} 路由（405），需求版本号在 document["requirement"] 里。
    version = (document.get("requirement") or {}).get("version")
    if not version:
        return {"error": "document 里没有需求版本号，无法冻结"}
    body, error = call(
        client, "POST", f"/api/projects/{PROJECT_ID}/requirements/{requirement_id}/snapshots",
        json_body={"expected_version": version, "expected_hash": document["content_hash"]},
    )
    if error:
        return {"error": f"snapshot {error['status']}: {str(error['detail'])[:300]}"}
    return body


def export_survey(client: Client, requirement_id: int, snapshot_id: int, name: str) -> dict:
    response = requests.post(
        f"{BASE}/api/projects/{PROJECT_ID}/requirements/{requirement_id}/exports",
        headers={"Authorization": f"Bearer {client.token}"},
        data={"format": "xlsx", "source_kind": "draft_snapshot", "source_id": str(snapshot_id), "layout": "survey"},
        timeout=300,
    )
    if response.status_code != 200:
        return {"error": f"{response.status_code}: {response.text[:300]}"}
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}-survey.xlsx"
    path.write_bytes(response.content)
    return {
        "bytes": len(response.content),
        "path": str(path.name),
        "renderer": response.headers.get("x-requirement-renderer-version"),
        "artifact_id": response.headers.get("x-requirement-render-artifact-id"),
    }


def run_table(client: Client, context: dict, table_code: str, max_wait: int, log,
              resume_requirement_id: int | None = None) -> dict:
    result: dict = {"table_code": table_code, "steps": {}}
    table = context["tables"].get(table_code)
    if table is None:
        result["error"] = "target table not found"
        return result
    table_field_ids = context["fields"].get(table.id, [])
    result["field_count"] = len(table_field_ids)
    script_name = f"YBT_{table_code}.sql"
    version_id = context["versions"].get(script_name)
    if version_id is None:
        result["error"] = f"script version not found: {script_name}"
        return result
    result["script_version_id"] = version_id

    started = time.time()
    if resume_requirement_id is not None:
        # 续跑：需求已建好、生成已派发（例如令牌过期导致轮询中断），
        # 直接从最近一次生成输入等结果，不重复付模型调用。
        return _resume_table(client, table_code, resume_requirement_id, max_wait, log, result)
    preview_body, target = preview(client, version_id, table_code)
    result["steps"]["preview"] = {
        "targets": len(preview_body.get("targets") or []),
        "rules": len(preview_body.get("rules") or []),
        "gaps": len(preview_body.get("gaps") or []),
        "preview_hash": preview_body.get("preview_hash"),
    }
    bindings = field_bindings(target, context["codes"], table_field_ids)
    result["bound_fields"] = len(bindings)
    # 需求范围包含该表全部监管字段（文档要列全，缺依据的字段显示缺口），
    # 但只有"脚本确有输出且能同名匹配"的字段才派发生成：系统字段没有脚本依据，
    # 硬生成只会让模型编出无根据的正文。
    scope_field_ids = list(table_field_ids)
    generation_field_ids = list(bindings.keys())
    result["scoped_fields"] = len(scope_field_ids)
    result["generated_fields"] = len(generation_field_ids)
    if not generation_field_ids:
        result["error"] = "脚本输出列与目标字段没有同名匹配，无法建立绑定"
        return result

    scope = {
        "name": f"{table_code} 监管字段需求（跑批脚本生成）",
        "target_table_id": table.id,
        "field_ids": scope_field_ids,
        "scenario_id": context["scenario_id"],
    }
    created, error = call(
        client, "POST", f"/api/projects/{PROJECT_ID}/requirements/from-scripts",
        json_body={
            "preview_hash": preview_body["preview_hash"],
            "script_version_ids": [version_id],
            "idempotency_key": f"batch-{table_code}-{int(time.time())}",
            "targets": [{
                "scope": scope,
                "target_key": str(target["key"]),
                "field_bindings": {str(column): field_id for field_id, column in bindings.items()},
                "template_version_id": 2,
            }],
        },
    )
    if error:
        result["error"] = f"from-scripts {error['status']}: {str(error['detail'])[:300]}"
        return result
    requirement = created["requirements"][0]
    requirement_id = requirement["requirement_id"]
    result["requirement_id"] = requirement_id
    result["steps"]["create"] = {"content_version": requirement.get("content_version")}

    texts = scope_texts(table_code, len(scope_field_ids), script_name)
    update, error = call(
        client, "PUT", f"/api/projects/{PROJECT_ID}/requirements/{requirement_id}",
        json_body={
            "name": scope["name"],
            **texts,
            "target_table_id": table.id,
            "field_ids": scope_field_ids,
            "scenario_id": context["scenario_id"],
            "expected_version": 1,
            "expected_content_version": requirement.get("content_version", 2),
        },
    )
    result["steps"]["scope_text"] = "ok" if not error else f"{error['status']}: {str(error['detail'])[:200]}"

    document, error = call(client, "GET", f"/api/projects/{PROJECT_ID}/requirements/{requirement_id}/document")
    if error:
        result["error"] = f"document {error['status']}: {str(error['detail'])[:200]}"
        return result
    content_version = document["revision"]["content_version"]
    generation, error = call(
        client, "POST", f"/api/projects/{PROJECT_ID}/requirements/{requirement_id}/generation-runs",
        json_body={
            "expected_content_version": content_version,
            "field_ids": generation_field_ids,
            "sections": SECTIONS,
            "idempotency_key": f"batch-{table_code}-gen-{int(time.time())}",
        },
    )
    if error:
        result["error"] = f"generation-runs {error['status']}: {str(error['detail'])[:300]}"
        return result
    input_id = generation.get("input_id")
    result["input_id"] = input_id
    expected = len(generation_field_ids) * len(SECTIONS)
    log(f"  已派发生成：input={input_id}，预期 {expected} 项")

    waited = wait_items(client, requirement_id, input_id, expected, max_wait, log)
    result["steps"]["generation"] = {"counts": waited["counts"], "seconds": waited["seconds"]}
    result["failures"] = [
        {"id": item["id"], "status": item["status"], "reason": item.get("reason_code")}
        for item in waited["items"]
        if item.get("status") in ("blocked", "failed")
    ]

    result["steps"]["adopt"] = adopt(client, requirement_id, waited["items"], input_id or 0, log)
    result["steps"]["freeze"] = freeze(client, requirement_id)
    snapshot_id = result["steps"]["freeze"].get("id")
    if snapshot_id:
        result["steps"]["export"] = export_survey(client, requirement_id, snapshot_id, table_code)
    result["seconds"] = round(time.time() - started, 1)
    return result


def _latest_run(client: Client, requirement_id: int):
    payload, error = call(
        client, "GET", f"/api/projects/{PROJECT_ID}/requirements/{requirement_id}/generation-runs"
    )
    if error:
        raise RuntimeError(f"generation-runs {error['status']}: {str(error['detail'])[:200]}")
    runs = payload.get("runs") if isinstance(payload, dict) else (payload or [])
    if not runs:
        raise RuntimeError("该需求还没有生成输入")
    return max(runs, key=lambda item: item["id"])


def _resume_table(client: Client, table_code: str, requirement_id: int, max_wait: int, log, result: dict) -> dict:
    run = _latest_run(client, requirement_id)
    input_id = run["id"]
    expected = int(run.get("total") or len(run.get("items") or []))
    result["requirement_id"] = requirement_id
    result["input_id"] = input_id
    result["steps"]["resume"] = {"input_id": input_id, "total": expected, "counts": run.get("counts")}
    log(f"  续跑：requirement={requirement_id} input={input_id} 预期 {expected} 项")
    waited = wait_items(client, requirement_id, input_id, expected, max_wait, log)
    result["steps"]["generation"] = {"counts": waited["counts"], "seconds": waited["seconds"]}
    result["failures"] = [
        {"id": item["id"], "status": item["status"], "reason": item.get("reason_code")}
        for item in waited["items"]
        if item.get("status") in ("blocked", "failed")
    ]
    result["steps"]["adopt"] = adopt(client, requirement_id, waited["items"], input_id, log)
    result["steps"]["freeze"] = freeze(client, requirement_id)
    snapshot_id = result["steps"]["freeze"].get("id")
    if snapshot_id:
        result["steps"]["export"] = export_survey(client, requirement_id, snapshot_id, table_code)
    result["seconds"] = result["steps"]["generation"]["seconds"]
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tables", nargs="+")
    parser.add_argument("--max-wait", type=int, default=2400)
    parser.add_argument(
        "--resume", action="append", default=[], metavar="TABLE=REQ_ID",
        help="续跑已建好需求的表，例如 --resume T_1_2=13",
    )
    args = parser.parse_args(argv)

    def log(message: str) -> None:
        print(message, flush=True)

    client = Client()
    client.login()
    context = load_context()
    log(f"上下文：目标表 {len(context['tables'])} 张，脚本版本 {len(context['versions'])} 个")

    resume: dict[str, int] = {}
    for item in args.resume:
        name, _, value = item.partition("=")
        resume[name.strip()] = int(value)

    results = []
    for table_code in args.tables:
        log(f"[{table_code}] 开始")
        try:
            results.append(run_table(client, context, table_code, args.max_wait, log,
                                     resume.get(table_code)))
        except Exception as exc:  # noqa: BLE001 - 批量验收要把失败原样记下来
            results.append({"table_code": table_code, "error": f"{type(exc).__name__}: {exc}"})
        log(f"[{table_code}] 结果 {json.dumps(results[-1], ensure_ascii=False)[:500]}")

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = EVIDENCE / f"batch-tables-{stamp}.json"
    path.write_text(
        json.dumps({"project_id": PROJECT_ID, "tables": args.tables, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"证据已写入 {path}")
    ok = sum(
        1
        for item in results
        if not item.get("error") and (item.get("steps", {}).get("export") or {}).get("bytes")
    )
    print(f"完成 {ok}/{len(results)} 张表")
    return 0 if ok == len(results) else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
