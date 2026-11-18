"""Exercise answer citation revalidation across generation and judge await windows."""
from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import threading
from urllib.parse import quote
from unittest.mock import patch

import httpx


BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))
LONG_RUN = REPOSITORY / ".local-run" / "rag-long-run"
RUNTIME = LONG_RUN / "runtime-20261117-53"
PRIVATE = LONG_RUN / "private-rag-p0-r53"
API_URL = "http://127.0.0.1:18137"

FIXTURES = (
    ("round60-generator.txt", "Round60 generator marker R60GEN8421 confirms BLUE only."),
    ("round60-judge.txt", "Round60 judge marker R60JUDGE9753 confirms GREEN only."),
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _checked(response: httpx.Response):
    response.raise_for_status()
    return response.json()


def _record(results: list[dict], name: str, passed: bool, **details) -> None:
    results.append({"name": name, "passed": bool(passed), **details})


def _set_withdrawn(version_id: int, withdrawn: bool) -> None:
    from app.core.database import SessionLocal
    from app.models import KnowledgeDocumentVersion

    with SessionLocal() as db:
        version = db.get(KnowledgeDocumentVersion, version_id)
        if version is None:
            raise RuntimeError("Round60 fixture version disappeared")
        version.lifecycle_status = "withdrawn" if withdrawn else "active"
        db.commit()


def _run_answer(project_id: int, version_unit_id: int, query: str, *, settings, hold_stage: str,
                trigger: threading.Event, released: threading.Event) -> dict:
    import app.services.rag.grounded_answer_service as grounded

    async def planner(_db, _project_id, original, _history, _settings, **_kwargs):
        return {
            "queries": [{"query": original, "role": "primary"}],
            "clarification_question": None,
        }

    async def execute(*_args, **_kwargs):
        if hold_stage == "generation":
            trigger.set()
            if not await asyncio.to_thread(released.wait, 60):
                raise TimeoutError("generation barrier was not released")
        return ({
            "answer": f"测试值为 {'BLUE' if '8421' in query else 'GREEN'} [{version_unit_id}]",
            "supported_claims": [],
            "unsupported_claims": [],
            "open_questions": [],
            "confidence_level": "high",
            "cannot_answer_reason": None,
        }, {"execution_kind": "mock_model", "model_name": "round60-controlled-mock"})

    async def judge(*_args, **_kwargs):
        trigger.set()
        if not await asyncio.to_thread(released.wait, 60):
            raise TimeoutError("judge barrier was not released")
        return {}

    with patch.object(grounded, "plan_query", planner), \
            patch.object(grounded, "execute_runtime_chat_with_metadata", execute), \
            patch.object(grounded, "check_citation_support", judge), \
            patch.object(grounded, "claim_support_summary", lambda _result: None), \
            patch.object(grounded, "get_settings", lambda: settings):
        from app.core.database import SessionLocal

        with SessionLocal() as db:
            return asyncio.run(grounded.grounded_answer(
                db, project_id, query, principal=None, commit=True,
                include_items=True,
            ))


def run(output: Path) -> dict:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Round60 output already contains evidence; use a fresh directory")
    output.mkdir(parents=True, exist_ok=True)
    bootstrap = _configure_database()
    from rag_review_environment import source_identity
    from rag_component_acceptance import authenticate_client, checked, reindex, upload

    identity = source_identity()
    results: list[dict] = []
    with httpx.Client(base_url=API_URL, timeout=180) as client:
        version_info = checked(client.get("/version"))
        expected_commit = identity["git_head"] + "+worktree." + identity["code_hash"][:12]
        if version_info.get("app_commit") != expected_commit:
            raise RuntimeError("Round60 API source identity does not match the current worktree")
        _record(results, "running_api_source_identity_matches", True,
                app_commit=version_info["app_commit"])
        authenticate_client(client, bootstrap)
        institution_id = _json(RUNTIME / "bootstrap-state.json")["institution_id"]
        project = checked(client.post("/api/projects", json={
            "name": "RAG Round60 in-flight governance",
            "bank_name": "RAG isolated component acceptance",
            "institution_id": institution_id,
        }))
        project_id = project["id"]
        uploaded = []
        for filename, text in FIXTURES:
            uploaded.append(upload(
                client, project_id, filename, text.encode("utf-8"),
                version=f"R60-{filename}", knowledge_type="regulatory_policy",
                source_category="internal_policy",
            ))
        reindex(client, project_id)

    from app.core.database import SessionLocal
    from app.models import KnowledgeUnit
    from sqlalchemy import select
    import app.services.rag.grounded_answer_service as grounded

    versions = [item["version_id"] for item in uploaded]
    version_unit_ids = []
    with SessionLocal() as db:
        for version_id in versions:
            unit_id = db.scalar(select(KnowledgeUnit.id).where(
                KnowledgeUnit.document_version_id == version_id,
                KnowledgeUnit.enabled.is_(True),
            ).order_by(KnowledgeUnit.id).limit(1))
            if unit_id is None:
                raise RuntimeError("Round60 fixture produced no enabled evidence unit")
            version_unit_ids.append(unit_id)
    settings = grounded.get_settings()

    def exercise(version_id: int, unit_id: int, query: str, stage: str) -> dict:
        trigger = threading.Event()
        released = threading.Event()
        original_settings = settings
        if stage == "judge":
            class JudgeSettings:
                def __getattr__(self, name):
                    return getattr(original_settings, name)

                citation_support_check = "judge"

            selected_settings = JudgeSettings()
        else:
            selected_settings = original_settings

        outcome: dict = {}

        def caller():
            try:
                outcome["answer"] = _run_answer(
                    project_id, unit_id, query, settings=selected_settings,
                    hold_stage=stage, trigger=trigger, released=released,
                )
            except Exception as exc:
                outcome["error"] = {
                    "type": type(exc).__name__,
                    "message": str(exc)[:240],
                }

        def revoke_after_barrier():
            if not trigger.wait(60):
                outcome["barrier_timeout"] = True
                return
            _set_withdrawn(version_id, True)
            outcome["withdrawal_committed_at"] = datetime.now(timezone.utc).isoformat()
            released.set()

        with ThreadPoolExecutor(max_workers=2) as pool:
            call_future = pool.submit(caller)
            if stage == "normal":
                call_future.result(timeout=180)
            else:
                revoke_future = pool.submit(revoke_after_barrier)
                call_future.result(timeout=180)
                revoke_future.result(timeout=180)

        returned = outcome.get("answer")
        if stage == "normal":
            return {
                "answer": returned,
                "error": outcome.get("error"),
                "barrier_timeout": bool(outcome.get("barrier_timeout")),
            }
        failed_closed = (
            not outcome.get("barrier_timeout")
            and outcome.get("withdrawal_committed_at") is not None
            and isinstance(outcome.get("error"), dict)
            and outcome["error"]["type"] == "ValueError"
            and returned is None
        )
        return {
            "passed": failed_closed,
            "stage": stage,
            "failure_closed": failed_closed,
            "answer_returned": returned is not None,
            "error_type": (outcome.get("error") or {}).get("type"),
            "withdrawal_committed_at": outcome.get("withdrawal_committed_at"),
            "barrier_timeout": bool(outcome.get("barrier_timeout")),
        }

    try:
        baseline = exercise(
            versions[0], version_unit_ids[0],
            "Round60 generator marker R60GEN8421 what value is confirmed?", "normal",
        )
        baseline_citation_versions = sorted({
            item.get("document_version_id")
            for item in (baseline.get("answer") or {}).get("citations", [])
            if item.get("document_version_id") is not None
        })
        baseline_cited_unit_ids = (baseline.get("answer") or {}).get("cited_unit_ids", [])
        _record(results, "unchanged_evidence_remains_available",
                baseline.get("answer") is not None
                and not baseline.get("error")
                and versions[0] in baseline_citation_versions
                and version_unit_ids[0] in baseline_cited_unit_ids,
                citation_version_ids=baseline_citation_versions,
                cited_unit_ids=baseline_cited_unit_ids,
                error_type=(baseline.get("error") or {}).get("type"))

        first_result = exercise(
            versions[0], version_unit_ids[0],
            "Round60 generator marker R60GEN8421 what value is confirmed?", "generation",
        )
        _record(results, "withdrawal_during_generation_fails_closed",
                first_result["passed"], **{k: v for k, v in first_result.items() if k != "passed"})
        _set_withdrawn(versions[0], False)
        second_result = exercise(
            versions[1], version_unit_ids[1],
            "Round60 judge marker R60JUDGE9753 what value is confirmed?", "judge",
        )
        _record(results, "withdrawal_during_judge_fails_closed",
                second_result["passed"], **{k: v for k, v in second_result.items() if k != "passed"})
    finally:
        for version_id in versions:
            _set_withdrawn(version_id, False)

    return {
        "round": 60,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "evidence_tier": "real_isolated_postgresql_redis_celery_milvus_local_embedding_controlled_mock_generator_judge",
        "source_is_synthetic": True,
        "gold": False,
        "holdout": False,
        "source": {
            "app_commit": version_info["app_commit"],
            "code_hash": identity["code_hash"],
        },
        "project_id": project_id,
        "fixture_version_ids": versions,
        "checks": results,
        "passed": sum(item["passed"] for item in results),
        "failed": sum(not item["passed"] for item in results),
        "external_provider_requests": 0,
        "external_provider_tokens": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    try:
        result = run(output)
        (output / "results.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except Exception as error:
        output.mkdir(parents=True, exist_ok=True)
        (output / "failure-attempt.json").write_text(json.dumps({
            "round": 60,
            "error_type": type(error).__name__,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
