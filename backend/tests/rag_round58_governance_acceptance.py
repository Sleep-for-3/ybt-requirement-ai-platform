"""Verify knowledge lifecycle and project-scope contracts on the isolated R53 runtime."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
from urllib.parse import quote

import httpx


BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))
LONG_RUN = REPOSITORY / ".local-run" / "rag-long-run"
RUNTIME = LONG_RUN / "runtime-20261117-53"
PRIVATE = LONG_RUN / "private-rag-p0-r53"
API_URL = "http://127.0.0.1:18137"
FRONTEND_API_URL = "http://127.0.0.1:18135"
SYNTHETIC_BYTES = "Round58 合成制度：字段Q58001只能填A1，A1表示仅本测试。".encode()
QUERY = "字段Q58001应该填什么？"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _checked(response: httpx.Response):
    response.raise_for_status()
    return response.json()


def _configure_database() -> dict:
    environment = _json(RUNTIME / "formal-environment.json")
    credentials = _json(PRIVATE / "secrets.json")
    os.environ.update(environment)
    database = (
        f"postgresql+psycopg://{quote(credentials['postgres_user'], safe='')}:"
        f"{quote(credentials['postgres_password'], safe='')}@127.0.0.1:15442/"
        f"{quote(credentials['postgres_database'], safe='')}"
    )
    os.environ.update({
        "DATABASE_URL": database,
        "APP_SECRET_KEY": credentials["app_secret_key"],
        "JWT_SECRET_KEY": credentials["jwt_secret_key"],
        "RAG_MODEL_BUDGET_REQUIRED": "true",
    })
    return _json(PRIVATE / "bootstrap-secret.json")


def _source_identity() -> dict:
    from rag_review_environment import source_identity

    return source_identity()


def _record(results: list[dict], name: str, passed: bool, **details) -> None:
    results.append({"name": name, "passed": bool(passed), **details})


def run(output: Path) -> dict:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Round58 output already contains evidence; use a fresh directory")
    output.mkdir(parents=True, exist_ok=True)
    credentials = _configure_database()
    identity = _source_identity()
    results: list[dict] = []

    from app.core.database import SessionLocal
    from app.models import KnowledgeDocumentVersion, KnowledgeUnit, Project
    from rag_component_acceptance import authenticate_client, checked, reindex, upload
    from sqlalchemy import select

    with httpx.Client(base_url=API_URL, timeout=180) as client:
        version_info = checked(client.get("/version"))
        expected_commit = identity["git_head"] + "+worktree." + identity["code_hash"][:12]
        if version_info.get("app_commit") != expected_commit:
            raise RuntimeError("Round58 API source identity does not match the current worktree")
        _record(results, "api_source_identity_matches", True, app_commit=version_info["app_commit"])
        state = {"username": credentials["username"], "password": credentials["password"]}
        authenticate_client(client, state)
        institution_id = _json(RUNTIME / "bootstrap-state.json")["institution_id"]

        project = checked(client.post("/api/projects", json={
            "name": "RAG Round58 synthetic governance",
            "bank_name": "RAG isolated component acceptance",
            "institution_id": institution_id,
        }))
        project_id = project["id"]
        original = upload(
            client, project_id, "round58-governance.txt", SYNTHETIC_BYTES,
            version="R58-SYNTHETIC-01", knowledge_type="regulatory_policy",
            source_category="internal_policy",
        )
        reindex(client, project_id)

        before = checked(client.post(
            f"/api/projects/{project_id}/knowledge/hybrid-search",
            json={"query": QUERY, "retrieval_mode": "hybrid", "top_k": 10},
        ))
        expected_ids = {original["version_id"]}
        matched = [
            item for item in before.get("items", [])
            if item.get("document_version_id") in expected_ids
            and "Q58001" in str(item.get("content", ""))
        ]
        _record(results, "active_synthetic_version_is_retrievable", bool(matched),
                result_count=len(before.get("items", [])), expected_version_id=original["version_id"])

        task_response = client.post(
            f"/api/projects/{project_id}/agent/tasks",
            json={"objective": QUERY, "scenario_key": "knowledge_question", "auto_start": True},
        )
        if task_response.status_code not in {200, 201, 202}:
            raise RuntimeError(f"Synthetic knowledge task failed to start: {task_response.status_code}")
        task_payload = task_response.json()
        task_id = (task_payload.get("task") or task_payload).get("id")
        if not task_id:
            raise RuntimeError("Synthetic knowledge task returned no task id")
        deadline = time.monotonic() + 180
        task_detail = {}
        while time.monotonic() < deadline:
            task_detail = checked(client.get(f"/api/agent/tasks/{task_id}"))
            current_task = task_detail.get("task") or task_detail
            if current_task.get("status") in {
                "completed", "failed", "cancelled", "blocked", "waiting_human",
            }:
                break
            time.sleep(1)
        current_task = task_detail.get("task") or task_detail
        if current_task.get("status") not in {"completed", "waiting_human"}:
            raise RuntimeError(f"Synthetic knowledge task ended as {current_task.get('status')}")
        artifacts = task_detail.get("artifacts") or current_task.get("artifacts") or []
        answer = next((item for item in artifacts if item.get("artifact_type") == "knowledge_answer"), None)
        citations = (answer or {}).get("summary", {}).get("citations", [])
        if not any(item.get("document_version_id") == original["version_id"] for item in citations):
            raise RuntimeError("Synthetic knowledge task did not cite its indexed version")
        _record(results, "agent_task_cites_current_synthetic_version", True,
                task_id=task_id, status=current_task.get("status"))

        with SessionLocal() as db:
            version = db.get(KnowledgeDocumentVersion, original["version_id"])
            if version is None or version.project_id != project_id:
                raise RuntimeError("Synthetic version identity mismatch")
            version.lifecycle_status = "withdrawn"
            db.commit()

        withdrawn_search = checked(client.post(
            f"/api/projects/{project_id}/knowledge/hybrid-search",
            json={"query": QUERY, "retrieval_mode": "hybrid", "top_k": 10},
        ))
        withdrawn_matches = [
            item for item in withdrawn_search.get("items", [])
            if item.get("document_version_id") == original["version_id"]
        ]
        _record(results, "withdrawn_version_excluded_from_retrieval", not withdrawn_matches,
                matching_results=len(withdrawn_matches))

        preview = checked(client.get(
            f"/api/knowledge/documents/{original['document_id']}/preview",
            params={"project_id": project_id, "version_id": original["version_id"]},
        ))
        content = client.get(
            f"/api/knowledge/documents/{original['document_id']}/content",
            params={"project_id": project_id, "version_id": original["version_id"]},
        )
        expected_hash = hashlib.sha256(SYNTHETIC_BYTES).hexdigest()
        _record(results, "authorized_withdrawn_original_remains_auditable",
                content.status_code == 200
                and hashlib.sha256(content.content).hexdigest() == expected_hash
                and preview.get("lifecycle_status") == "withdrawn"
                and any("撤回" in warning for warning in preview.get("warnings", [])),
                status=content.status_code, sha256=hashlib.sha256(content.content).hexdigest()
                if content.status_code == 200 else None,
                warning_present=any("撤回" in warning for warning in preview.get("warnings", [])))

        cross_preview = client.get(
            f"/api/knowledge/documents/{original['document_id']}/preview",
            params={"project_id": project_id + 1000000, "version_id": original["version_id"]},
        )
        cross_content = client.get(
            f"/api/knowledge/documents/{original['document_id']}/content",
            params={"project_id": project_id + 1000000, "version_id": original["version_id"]},
        )
        _record(results, "cross_project_preview_and_original_are_hidden",
                cross_preview.status_code == 404 and cross_content.status_code == 404,
                preview_status=cross_preview.status_code, content_status=cross_content.status_code)

        with SessionLocal() as db:
            version = db.get(KnowledgeDocumentVersion, original["version_id"])
            version.lifecycle_status = "active"
            units = list(db.scalars(select(KnowledgeUnit).where(
                KnowledgeUnit.document_version_id == original["version_id"],
                KnowledgeUnit.enabled.is_(True),
            )))
            if not units:
                raise RuntimeError("Synthetic version has no enabled knowledge units")
            unit_ids = [unit.id for unit in units]
            for unit in units:
                unit.enabled = False
            db.commit()
        disabled_search = checked(client.post(
            f"/api/projects/{project_id}/knowledge/hybrid-search",
            json={"query": QUERY, "retrieval_mode": "hybrid", "top_k": 10},
        ))
        disabled_matches = [
            item for item in disabled_search.get("items", [])
            if item.get("document_version_id") == original["version_id"]
        ]
        _record(results, "disabled_units_excluded_despite_existing_vectors", not disabled_matches,
                matching_results=len(disabled_matches), index_rebuilt=False)
        active_preview = checked(client.get(
            f"/api/knowledge/documents/{original['document_id']}/preview",
            params={"project_id": project_id, "version_id": original["version_id"]},
        ))
        _record(results, "unit_disable_does_not_false_revoke_document_audit",
                active_preview.get("lifecycle_status") == "active"
                and not any("撤回" in warning for warning in active_preview.get("warnings", [])))

        with SessionLocal() as db:
            version = db.get(KnowledgeDocumentVersion, original["version_id"])
            version.lifecycle_status = "active"
            for unit_id in unit_ids:
                db.get(KnowledgeUnit, unit_id).enabled = True
            db.commit()

        barrier = threading.Barrier(9)
        transition = {}
        authorization = client.headers["Authorization"]

        def concurrent_search():
            barrier.wait()
            started = time.perf_counter()
            with httpx.Client(base_url=API_URL, timeout=60, headers={
                "Authorization": authorization,
            }) as concurrent_client:
                response = concurrent_client.post(
                    f"/api/projects/{project_id}/knowledge/hybrid-search",
                    json={"query": QUERY, "retrieval_mode": "hybrid", "top_k": 10},
                )
            finished = time.perf_counter()
            response.raise_for_status()
            payload = response.json()
            return {
                "started": started,
                "finished": finished,
                "status": response.status_code,
                "matching_citations": sum(
                    item.get("document_version_id") == original["version_id"]
                    for item in payload.get("items", [])
                ),
            }

        def withdraw_during_search():
            barrier.wait()
            time.sleep(0.01)
            with SessionLocal() as db:
                version = db.get(KnowledgeDocumentVersion, original["version_id"])
                version.lifecycle_status = "withdrawn"
                db.commit()
            transition["committed"] = time.perf_counter()

        with ThreadPoolExecutor(max_workers=9) as executor:
            searches = [executor.submit(concurrent_search) for _ in range(8)]
            mutation = executor.submit(withdraw_during_search)
            concurrent_results = [future.result() for future in searches]
            mutation.result()

        committed_at = transition["committed"]
        overlapping = [
            item for item in concurrent_results
            if item["started"] <= committed_at <= item["finished"]
        ]
        leaked_after_commit = [
            item for item in concurrent_results
            if item["finished"] >= committed_at and item["matching_citations"]
        ]
        _record(results, "withdrawal_during_api_search_does_not_return_post_commit_citation",
                bool(overlapping) and not leaked_after_commit,
                overlapping_requests=len(overlapping),
                completed_requests=len(concurrent_results),
                responses_with_citation_after_commit=len(leaked_after_commit))

        with SessionLocal() as db:
            for unit_id in unit_ids:
                db.get(KnowledgeUnit, unit_id).enabled = False
            db.commit()
        with SessionLocal() as db:
            version = db.get(KnowledgeDocumentVersion, original["version_id"])
            version.lifecycle_status = "withdrawn"
            db.commit()

        health = checked(client.get("/health/ready"))

    report = {
        "round": 58,
        "goal": "G-P0-B",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "evidence_tier": "real_isolated_postgresql_redis_celery_milvus_api",
        "source": {
            "app_commit": version_info["app_commit"],
            "code_hash": identity["code_hash"],
            "schema_head": version_info.get("schema_head"),
        },
        "runtime": {
            "name": "rag-p0-r53",
            "api_url": API_URL,
            "frontend_api_url": FRONTEND_API_URL,
            "postgres_port": 15442,
            "milvus_collection_prefix": os.environ.get("MILVUS_COLLECTION_PREFIX"),
            "project_id": project_id,
            "document_id": original["document_id"],
            "version_id": original["version_id"],
            "task_id": task_id,
        },
        "fixture": {
            "synthetic": True,
            "holdout": False,
            "source_sha256": expected_hash,
            "index_rebuilt": True,
        },
        "checks": results,
        "passed": sum(item["passed"] for item in results),
        "failed": [item["name"] for item in results if not item["passed"]],
        "readiness": health.get("status"),
        "final_fixture_state": {"lifecycle_status": "withdrawn", "enabled_units": 0},
        "external_provider_requests": 0,
        "browser_acceptance": "not_run",
        "inflight_status_change_race": "not_run",
        "p0_complete": False,
        "p1_p2_released": False,
        "public_traffic_switched": False,
    }
    (output / "api-results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if report["failed"]:
        raise SystemExit(json.dumps({"passed": report["passed"], "failed": report["failed"]}))
    print(json.dumps({"passed": report["passed"], "failed": report["failed"],
                      "external_provider_requests": 0}))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        run(arguments.output.resolve())
    except Exception as error:
        output = arguments.output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        failure_path = output / "failure-attempt.json"
        if not failure_path.exists():
            failure_path.write_text(json.dumps({
                "round": 58,
                "attempt": "failed",
                "error_type": type(error).__name__,
                "error": str(error)[:500],
                "production_code_changed": False,
                "external_provider_requests": 0,
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
