"""Run the Product 5.1 real-runtime agent benchmark.

The agent phase deliberately has no reference-data import.  Golden truth is
loaded only by the evaluation phase, after all field generations have been
completed.  This keeps the benchmark useful as a regression harness and
prevents accidental leakage of expected answers into model prompts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bootstrap_product_5_1_platform import Api


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / ".local-run" / "product_5_1_real_agent_results.json"
FIELD_ORDER = (
    "E010001", "E010002", "E010003", "E010004", "E010005", "E010007",
    "E010008", "E010009", "E010010", "E010011", "E010012", "E010013",
    "E010014", "E010015", "E010018", "E010016", "E010017",
)
FATAL_STATUS_CODES = {401, 402, 403, 404, 429}


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


def _status_from_error(exc: Exception) -> int | None:
    match = re.search(r"->\s*(\d{3})", str(exc))
    return int(match.group(1)) if match else None


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(value), ensure_ascii=False, indent=2), encoding="utf-8")


def _login(api: Api, username: str, password: str) -> None:
    session = api.post("/auth/login", {"username": username, "password": password})
    api.authorize(session["access_token"])


def _field_tasks(api: Api, field: dict[str, Any]) -> dict[str, Any]:
    field_id = field["id"]
    mart = api.get(f"/target-fields/{field_id}/mart-to-ybt-mappings")
    business = api.get(f"/target-fields/{field_id}/scenario-business-mappings")
    technical = api.get(f"/target-fields/{field_id}/scenario-technical-lineages")
    return {
        "mart_to_ybt": mart[0] if mart else None,
        "business": business[0] if business else None,
        "technical": technical[0] if technical else None,
    }


def _source_mapping(api: Api, field: dict[str, Any], mart_task: dict[str, Any] | None) -> dict[str, Any] | None:
    # The formal bootstrap links a source mapping through the imported Mart
    # field.  Prefer that canonical link and avoid guessing by name.
    mart_id = (mart_task or {}).get("mart_field_id")
    if not mart_id:
        # Older Product 5.1 demo rows did not persist mart_field_id on the
        # Mart-to-YBT task.  The verified lineage graph is the authoritative
        # fallback and still avoids guessing by mapping name.
        graph = api.get(
            f"/target-fields/{field['id']}/lineage",
            params={"direction": "both", "depth": 3, "limit": 100},
        )
        mart_ids = [item.get("mart_field_id") for item in graph.get("nodes", []) if item.get("mart_field_id")]
        mart_id = mart_ids[0] if mart_ids else None
    if not mart_id:
        return None
    rows = api.get(f"/mart-fields/{mart_id}/source-to-mart-mappings")
    return rows[0] if rows else None


def _is_generated(task: dict[str, Any] | None) -> bool:
    if not task:
        return False
    return bool(task.get("ai_generated_content"))


def _call_generation(api: Api, path: str, task: dict[str, Any] | None) -> dict[str, Any]:
    if task is None:
        return {"status": "missing_task", "path": path}
    if _is_generated(task):
        # Reusing an already generated draft must still preserve the draft in
        # the benchmark artifact.  The previous harness kept only the task id,
        # which made the post-run Golden evaluator inspect an empty string and
        # under-report otherwise real outputs.  This is a read-only reuse; no
        # model call is made and no expected-answer data is introduced.
        return {
            "status": "reused_existing_success",
            "path": path,
            "task_id": task.get("id"),
            "result": task,
            "latency_ms": 0,
            "token_usage": {"usage_available": False, "reused": True},
        }
    started = time.perf_counter()
    try:
        result = api.post(path, {})
        return {
            "status": "success",
            "path": path,
            "task_id": result.get("id"),
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "result": result,
        }
    except Exception as exc:
        return {
            "status": "error",
            "path": path,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "error": str(exc)[:2000],
            "http_status": _status_from_error(exc),
        }


def run_agents(
    api: Api,
    *,
    project_id: int,
    output_path: Path,
    username: str,
    password: str,
) -> dict[str, Any]:
    runtime = api.get("/ai-runtime/status")
    if runtime["llm"].get("is_mock") or runtime["embedding"].get("is_mock") or runtime["vector_store"].get("is_mock"):
        result = {
            "status": "REAL_AGENT_BENCHMARK_BLOCKED",
            "blocked_reason": "Runtime gate reports a mock component; no agent call was made.",
            "runtime": runtime,
            "fields": [],
        }
        _write(output_path, result)
        return result

    fields = api.get("/fields", params={"project_id": project_id, "target_table_id": 3})
    by_code = {item["field_code"]: item for item in fields}
    records: list[dict[str, Any]] = []
    fatal_error: dict[str, Any] | None = None
    for code in FIELD_ORDER:
        # Access tokens are intentionally short-lived in production. Refresh
        # before each field so a long real-model run does not lose its session.
        _login(api, username, password)
        field = by_code.get(code)
        if field is None:
            records.append({"field_code": code, "status": "missing_field"})
            continue
        tasks = _field_tasks(api, field)
        source = _source_mapping(api, field, tasks["mart_to_ybt"])
        generation = {
            "source_to_mart": _call_generation(
                api,
                f"/source-to-mart-mappings/{source['id']}/generate-draft" if source else "",
                source,
            ),
            "mart_to_ybt": _call_generation(
                api,
                f"/mart-to-ybt-mappings/{tasks['mart_to_ybt']['id']}/generate-draft" if tasks["mart_to_ybt"] else "",
                tasks["mart_to_ybt"],
            ),
            "requirement_business": _call_generation(
                api,
                f"/scenario-business-mappings/{tasks['business']['id']}/generate-draft" if tasks["business"] else "",
                tasks["business"],
            ),
            "requirement_technical": _call_generation(
                api,
                f"/scenario-technical-lineages/{tasks['technical']['id']}/generate-draft" if tasks["technical"] else "",
                tasks["technical"],
            ),
        }
        context_params = {
            "as_of": "2026-08-30",
            "target_table_id": field.get("target_table_id"),
            "target_field_id": field["id"],
            "reporting_period": "2026-08",
            "mode": "candidate",
            "candidate_limit": 50,
        }
        try:
            context = api.get(f"/projects/{project_id}/regulatory-context", params=context_params)
        except RuntimeError as exc:
            if _status_from_error(exc) != 401:
                raise
            _login(api, username, password)
            context = api.get(f"/projects/{project_id}/regulatory-context", params=context_params)
        lineage = api.get(
            f"/target-fields/{field['id']}/lineage",
            params={"direction": "both", "depth": 8, "limit": 1000},
        )
        calls = api.get(f"/projects/{project_id}/model-calls", params={"page_size": 100})
        field_statuses = [item.get("status") for item in generation.values()]
        field_ok = all(status in {"success", "reused_existing_success"} for status in field_statuses)
        records.append({
            "field_code": code,
            "target_field": field,
            "regulatory_context": {
                "context_hash": context.get("context_hash") or (context.get("build_metadata") or {}).get("context_hash"),
                "context_schema_version": context.get("context_schema_version"),
                "fact_count": (context.get("build_metadata") or {}).get("fact_count", 0),
                "retrieved_evidence": len(context.get("knowledge_evidence") or []),
                "semantic_context": len(context.get("semantic") or []),
                "candidate_mart_assets": len(context.get("candidates") or []),
                "candidate_source_assets": len(context.get("metadata") or []),
                "open_questions": len(context.get("open_questions") or []),
                "retrieved_evidence_items": context.get("knowledge_evidence") or [],
                "semantic_context_items": context.get("semantic") or [],
                "candidate_mart_assets_items": context.get("candidates") or [],
                "candidate_source_assets_items": context.get("metadata") or [],
                "open_question_items": context.get("open_questions") or [],
            },
            "lineage": {
                "node_count": len(lineage.get("nodes") or []),
                "edge_count": len(lineage.get("edges") or []),
                "unresolved_nodes": sum(bool(item.get("unresolved_flag")) for item in lineage.get("nodes") or []),
            },
            "generation": generation,
            "model_calls_total": calls.get("total", 0),
            "status": "success" if field_ok else "partial",
        })
        for item in generation.values():
            if item.get("http_status") in FATAL_STATUS_CODES:
                fatal_error = item
                break
        _write(output_path, {
            "status": "RUNNING",
            "runtime": runtime,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "fields": records,
            "fatal_error": fatal_error,
        })
        if fatal_error:
            break

    all_success = len(records) == len(FIELD_ORDER) and all(item.get("status") == "success" for item in records)
    status = "REAL_AGENT_BENCHMARK_PASS" if all_success and fatal_error is None else "REAL_AGENT_BENCHMARK_PARTIAL"
    result = {
        "status": status,
        "runtime": runtime,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "fields": records,
        "fatal_error": fatal_error,
        "golden_evaluation": "NOT_RUN (agent phase only; golden truth was not read)",
    }
    _write(output_path, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("PRODUCT_5_1_BASE_URL", "http://127.0.0.1:8000/api"))
    parser.add_argument("--username", default=os.getenv("PRODUCT_5_1_ADMIN_USERNAME", "smoke_admin"))
    parser.add_argument("--password", default=os.getenv("PRODUCT_5_1_ADMIN_PASSWORD", "smoke-only-platform-admin-password"))
    parser.add_argument("--project-id", type=int, default=5)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    api = Api(args.base_url, timeout=180, max_rate_limit_retries=0)
    try:
        _login(api, args.username, args.password)
        result = run_agents(
            api,
            project_id=args.project_id,
            output_path=args.output,
            username=args.username,
            password=args.password,
        )
        print(json.dumps({"status": result["status"], "field_count": len(result.get("fields", [])), "output": str(args.output)}, ensure_ascii=False))
    finally:
        api.close()


if __name__ == "__main__":
    main()
