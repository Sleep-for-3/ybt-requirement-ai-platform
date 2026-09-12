from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from bootstrap_product_5_1_platform import Api
from product_5_1_common import DEFAULT_RUNTIME_ROOT, DEMO_PROJECT_NAME, write_json


ROOT = Path(__file__).resolve().parents[2]
V2_SQL = ROOT / "demo" / "product_5_1" / "sql" / "mart_to_regulatory" / "build_ybt_5_1_v2.sql"
V2_RELATIVE_PATH = "product_5_1/mart_to_regulatory/build_ybt_5_1.sql"
FOCUS_FIELDS = ("E010005", "E010007", "E010010", "E010012", "E010015", "E010018")


def run_verification(api: Api, runtime_root: Path, *, username: str, password: str) -> dict[str, Any]:
    session = api.post("/auth/login", {"username": username, "password": password})
    api.authorize(session["access_token"])
    project = next((item for item in api.get("/projects") if item["name"] == DEMO_PROJECT_NAME), None)
    if project is None:
        raise RuntimeError("Demo project is missing. Run bootstrap_product_5_1_platform.py first.")
    project_id = project["id"]
    target_table = next(
        item for item in api.get("/target-tables", params={"project_id": project_id})
        if item["table_code"] == "YBT_5_1_PRODUCT_BUSINESS_BASIC"
    )
    fields = {
        item["field_code"]: item
        for item in api.get(
            "/fields",
            params={"project_id": project_id, "target_table_id": target_table["id"]},
        )
    }
    cycles = api.get(f"/projects/{project_id}/reporting-cycles")
    runtime = api.get("/ai-runtime/status")
    llm_blocked = bool(runtime["llm"].get("is_mock"))

    scripts = api.get(f"/projects/{project_id}/scripts")
    target_script = next(item for item in scripts if item["relative_path"] == V2_RELATIVE_PATH)
    if target_script["current_version_no"] < 2:
        with V2_SQL.open("rb") as handle:
            v2_upload = api.request(
                "POST",
                f"/projects/{project_id}/scripts/upload",
                files={"file": (V2_SQL.name, handle, "text/plain")},
                data={
                    "relative_path": V2_RELATIVE_PATH,
                    "dialect": "sqlite",
                    "change_note": "v2: specialized-source inactive status overrides stale product-center status",
                },
            )
    else:
        changes = api.get(f"/projects/{project_id}/lineage/changes", params={"limit": 100})
        change = next(item for item in changes if item["script_file_id"] == target_script["id"])
        v2_upload = {
            "script_file_id": target_script["id"],
            "version_no": target_script["current_version_no"],
            "change_set_id": change["id"],
            "impact_id": change["impact_id"],
            "deduplicated": True,
        }

    change_set = api.get(f"/lineage/changes/{v2_upload['change_set_id']}")
    impact = api.get(f"/lineage/impacts/{v2_upload['impact_id']}")
    # Project-wide graph reads the full revision snapshot; direction/depth
    # require an explicit root and are covered by the field-level calls below.
    graph = api.get(f"/projects/{project_id}/lineage/graph", params={"limit": 2000})
    unresolved = api.get(f"/projects/{project_id}/lineage/unresolved", params={"limit": 500})
    workspace = api.get(
        f"/projects/{project_id}/requirement-workspace",
        params={"target_table_id": target_table["id"]},
    )
    contexts: dict[str, Any] = {}
    field_lineage: dict[str, Any] = {}
    for code in FOCUS_FIELDS:
        field = fields[code]
        contexts[code] = api.get(
            f"/projects/{project_id}/regulatory-context",
            params={
                "as_of": "2026-08-30",
                "target_table_id": target_table["id"],
                "target_field_id": field["id"],
                "reporting_period": "2026-08",
                "mode": "trusted",
                "candidate_limit": 50,
            },
        )
        field_lineage[code] = api.get(
            f"/target-fields/{field['id']}/lineage",
            params={"direction": "both", "depth": 5, "limit": 1000},
        )

    analytics = {
        item["cycle_code"]: api.get(
            f"/projects/{project_id}/analytics/overview",
            params={"cycle_id": item["id"]},
        )
        for item in cycles
    }
    dashboard = api.get(f"/projects/{project_id}/dashboard")
    cockpit = api.get("/cockpit")
    quality = api.get(f"/projects/{project_id}/quality-expectations")
    documents = api.get(f"/projects/{project_id}/knowledge/documents")
    tasks = api.get("/me/tasks")

    result = {
        "project": project,
        "target_table": target_table,
        "target_field_count": len(fields),
        "ai_runtime": runtime,
        "agent_generation": {
            "status": "BLOCKED_LLM_RUNTIME" if llm_blocked else "READY_REAL_LLM",
            "generation_invoked": False,
            "reason": (
                "The configured provider is mock; no generator endpoint was invoked and no evaluation metrics were fabricated."
                if llm_blocked
                else "A real runtime is available; generation must be started explicitly before evaluation."
            ),
        },
        "v2_upload": v2_upload,
        "change_set": change_set,
        "impact": impact,
        "lineage": {
            "node_count": len(graph["nodes"]),
            "edge_count": len(graph["edges"]),
            "unresolved_count": len(unresolved),
            "focus_fields": {
                code: {
                    "node_count": len(value["nodes"]),
                    "edge_count": len(value["edges"]),
                    "truncated": value["truncated"],
                }
                for code, value in field_lineage.items()
            },
        },
        "regulatory_context": {
            code: _context_summary(value) for code, value in contexts.items()
        },
        "requirement_workspace": _workspace_summary(workspace),
        "quality": {
            "configured_expectation_count": len(quality),
            "execution_engine_status": "NOT_IMPLEMENTED",
            "claim": "Expectation configured; not an execution result.",
        },
        "knowledge": {
            "document_count": len(documents),
            "documents": [
                {
                    "id": item["id"],
                    "file_name": item["file_name"],
                    "parse_status": item["parse_status"],
                    "document_status": item["document_status"],
                    "unit_count": (item.get("parse_summary_json") or {}).get("unit_count"),
                    "file_hash": item.get("file_hash"),
                }
                for item in documents
            ],
        },
        "analytics": analytics,
        "dashboard": dashboard,
        "cockpit": cockpit,
        "review_tasks": tasks,
    }
    write_json(runtime_root / "platform_verification_summary.json", result)
    return result


def _context_summary(context: dict[str, Any]) -> dict[str, Any]:
    build_metadata = context.get("build_metadata") or {}
    collection_keys = (
        "semantic",
        "regulatory",
        "metadata",
        "candidates",
        "mappings",
        "lineage",
        "knowledge_evidence",
        "historical",
        "quality",
        "conflicts",
        "open_questions",
    )
    return {
        "context_hash": context.get("context_hash") or build_metadata.get("context_hash"),
        "fact_count": build_metadata.get("fact_count"),
        **{key: len(context.get(key) or []) for key in collection_keys},
        "warnings": context.get("warnings") or [],
    }


def _workspace_summary(workspace: dict[str, Any]) -> dict[str, Any]:
    rows = workspace.get("records") or []
    return {
        "top_level_keys": sorted(workspace),
        "field_rows": len(rows),
        "summary": workspace.get("summary"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Product 5.1 demo through real platform APIs")
    parser.add_argument("--base-url", default=os.getenv("PRODUCT_5_1_BASE_URL", "http://127.0.0.1:8000/api"))
    parser.add_argument("--username", default=os.getenv("PRODUCT_5_1_ADMIN_USERNAME", "product_5_1_admin"))
    parser.add_argument("--password", default=os.getenv("PRODUCT_5_1_ADMIN_PASSWORD"))
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    args = parser.parse_args()
    if not args.password:
        raise SystemExit("Set PRODUCT_5_1_ADMIN_PASSWORD or pass --password.")
    api = Api(args.base_url)
    try:
        result = run_verification(api, args.runtime_root, username=args.username, password=args.password)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        api.close()


if __name__ == "__main__":
    main()
