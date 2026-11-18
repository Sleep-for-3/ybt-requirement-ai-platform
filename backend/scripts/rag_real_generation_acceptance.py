"""Run a bounded real-model RAG acceptance set against the isolated stack.

The dataset annotations are frozen source-backed expectations, but they are not
human-approved gold. The report keeps that distinction explicit and never
rewrites ``dataset.json``.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import time

import httpx


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    rank = (len(values) - 1) * p
    lower, upper = int(rank), min(int(rank) + 1, len(values) - 1)
    return round(values[lower] + (values[upper] - values[lower]) * (rank - lower), 2)


def authenticate(client: httpx.Client, state: dict) -> None:
    response = client.post("/api/auth/login", json={"username": state["username"], "password": state["password"]})
    response.raise_for_status()
    client.headers["Authorization"] = "Bearer " + response.json()["access_token"]


def expected(case: dict) -> dict:
    annotations = case.get("annotations") or []
    required = sorted({int(identity) for row in annotations for identity in
                       (row.get("expected", {}).get("required_units") or [])})
    refuse = any(row.get("expected", {}).get("must_refuse") is True for row in annotations)
    return {"required_ids": required, "must_refuse": refuse}


def assess(case: dict, response: dict, latency_ms: float) -> dict:
    expectation = expected(case)
    citations = response.get("citations") or []
    cited_ids = sorted({int(row["knowledge_unit_id"]) for row in citations
                        if str(row.get("knowledge_unit_id", "")).isdigit()})
    required = set(expectation["required_ids"])
    cited = set(cited_ids)
    status = response.get("answer_status")
    execution = response.get("execution_metadata") or {}
    real_model = execution.get("execution_kind") == "real_model"
    if expectation["must_refuse"]:
        # A refusal can be explicit or a governed confirmation state. A fully
        # grounded answer with no confirmation is a refusal failure.
        behavior_pass = status in {"needs_confirmation", "degraded"} or (
            "无法" in str(response.get("answer") or "") or
            "没有" in str(response.get("answer") or "")
        )
    else:
        behavior_pass = bool(required) and required.issubset(cited)
    return {
        "case_id": case["case_id"],
        "split": case["split"],
        "families": case.get("families") or [],
        "expected_required_ids": expectation["required_ids"],
        "expected_must_refuse": expectation["must_refuse"],
        "answer_status": status,
        "execution_kind": execution.get("execution_kind"),
        "provider": execution.get("provider_type") or execution.get("provider"),
        "model": execution.get("model_name"),
        "cited_ids": cited_ids,
        "citation_count": len(citations),
        "required_ids_covered": sorted(required & cited),
        "all_required_citations_present": bool(required) and required.issubset(cited),
        "behavior_pass_provisional": bool(behavior_pass),
        "verification_status": response.get("verification_status"),
        "trust_grade": (response.get("trustworthiness") or {}).get("grade"),
        "degraded_reason": response.get("degraded_reason"),
        "latency_ms": round(latency_ms, 2),
        "token_usage": execution.get("token_usage") or {},
        "retrieval_log_id": response.get("retrieval_log_id"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=20)
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    state = read_json(workspace / "state.json")
    dataset = read_json(Path(args.dataset).resolve())
    project_id = args.project_id or int(state["corpus_project_id"])
    rows: list[dict] = []
    errors: list[dict] = []
    started_at = datetime.now(timezone.utc).isoformat()
    with httpx.Client(base_url=state["backend_url"], timeout=240) as client:
        authenticate(client, state)
        for index, case in enumerate(dataset["cases"], start=1):
            # Access tokens in the isolated stack are short-lived. Refreshing
            # between bounded batches keeps a long real-model run from turning
            # into a misleading tail of HTTP 401s.
            if index > 1 and (index - 1) % 20 == 0:
                authenticate(client, state)
            started = time.perf_counter()
            try:
                response = client.post(
                    f"/api/projects/{project_id}/knowledge/ask",
                    json={"query": case["query"], "top_k": args.top_k,
                          "retrieval_mode": "hybrid", "history": []},
                )
                if response.status_code == 401:
                    authenticate(client, state)
                    response = client.post(
                        f"/api/projects/{project_id}/knowledge/ask",
                        json={"query": case["query"], "top_k": args.top_k,
                              "retrieval_mode": "hybrid", "history": []},
                    )
                response.raise_for_status()
                rows.append(assess(case, response.json(), (time.perf_counter() - started) * 1000))
            except Exception as exc:  # keep the complete set auditable
                errors.append({"case_id": case["case_id"], "error_type": type(exc).__name__,
                               "http_status": getattr(getattr(exc, "response", None), "status_code", None),
                               "latency_ms": round((time.perf_counter() - started) * 1000, 2)})
            if index % 10 == 0 or index == len(dataset["cases"]):
                print(json.dumps({"completed": index, "total": len(dataset["cases"]),
                                  "errors": len(errors)}), flush=True)

    latencies = [row["latency_ms"] for row in rows]
    real_rows = [row for row in rows if row["execution_kind"] == "real_model"]
    answer_rows = [row for row in rows if not row["expected_must_refuse"]]
    refuse_rows = [row for row in rows if row["expected_must_refuse"]]
    split = {}
    for name in ("tuning", "holdout"):
        subset = [row for row in rows if row["split"] == name]
        split[name] = {
            "cases": len(subset),
            "real_model": sum(row["execution_kind"] == "real_model" for row in subset),
            "status_counts": {status: sum(row["answer_status"] == status for row in subset)
                              for status in sorted({row["answer_status"] for row in subset})},
            "citation_complete": sum(row["all_required_citations_present"] for row in subset),
            "provisional_behavior_pass": sum(row["behavior_pass_provisional"] for row in subset),
            "p95_latency_ms": percentile([row["latency_ms"] for row in subset], .95),
        }
    report = {
        "schema": "rag-real-generation-acceptance-v1",
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "dataset_version": dataset.get("dataset_version"),
        "dataset_sha256": hashlib.sha256(Path(args.dataset).read_bytes()).hexdigest(),
        "workspace": workspace.name,
        "project_id": project_id,
        "evidence_tier": "real_components_real_model",
        "gold_status": "source_backed_annotations_not_human_approved",
        "human_gold_approved_cases": 0,
        "cases": len(dataset["cases"]),
        "completed": len(rows),
        "errors": len(errors),
        "real_model_calls": len(real_rows),
        "answer_cases": len(answer_rows),
        "refusal_cases": len(refuse_rows),
        "status_counts": {status: sum(row["answer_status"] == status for row in rows)
                          for status in sorted({row["answer_status"] for row in rows})},
        "execution_counts": {kind: sum(row["execution_kind"] == kind for row in rows)
                             for kind in sorted({row["execution_kind"] for row in rows})},
        "citation_complete_cases": sum(row["all_required_citations_present"] for row in answer_rows),
        "provisional_behavior_pass_cases": sum(row["behavior_pass_provisional"] for row in rows),
        "latency_ms": {"p50": percentile(latencies, .50), "p95": percentile(latencies, .95),
                       "max": max(latencies) if latencies else None},
        "split": split,
        "errors_detail": errors,
        "rows": rows,
        "blockers": [
            "human_gold_not_approved",
            "tuning_holdout_share_source_document",
        ],
    }
    write_json(Path(args.output).resolve(), report)
    print(json.dumps({key: report[key] for key in (
        "cases", "completed", "errors", "real_model_calls", "status_counts",
        "citation_complete_cases", "provisional_behavior_pass_cases", "latency_ms", "blockers")},
        ensure_ascii=False))


if __name__ == "__main__":
    main()
