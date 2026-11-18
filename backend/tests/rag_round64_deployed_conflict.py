"""Run an isolated Uvicorn API with controlled citation governance windows."""
from __future__ import annotations

import argparse
import asyncio
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import sys
import time
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

from rag_round60_inflight_governance import _configure_database
from rag_round63_http_governance import QUERY, seed_fixture

API_PORT = 18140
FRONTEND_PORT = 18141
INVALID_MESSAGE = "验收问题参数不正确，请修改问题后重试。"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate_environment() -> None:
    from app.core.settings import get_settings
    from app.services.llm.provider_budget import ProviderBudget
    from sqlalchemy.engine import make_url

    settings = get_settings()
    database = make_url(settings.database_url)
    if (settings.llm_provider != "mock" or database.host != "127.0.0.1"
            or database.port != 15442 or database.database != "ragp0"
            or settings.milvus_collection_prefix != "rag_p0_r53_formal"):
        raise RuntimeError("This acceptance requires the owned Round53 isolation and Mock LLM")
    budget = ProviderBudget.from_environment()
    if (os.environ.get("RAG_MODEL_BUDGET_REQUIRED") != "true" or budget is None
            or not budget.summary.is_file() or not budget.state.is_file()):
        raise RuntimeError("The shared provider budget must be required and available")


def set_fixture(fixture: dict, change: str = "restore") -> None:
    from app.core.database import SessionLocal
    from app.models import KnowledgeDocumentVersion, KnowledgeUnit

    with SessionLocal() as db:
        version = db.get(KnowledgeDocumentVersion, fixture["version_id"])
        unit = db.get(KnowledgeUnit, fixture["unit_id"])
        if (version is None or unit is None or version.project_id != fixture["project_id"]
                or unit.project_id != fixture["project_id"]
                or unit.document_version_id != version.id):
            raise RuntimeError("Acceptance fixture identity changed")
        version.lifecycle_status = "withdrawn" if change == "withdrawn" else "active"
        unit.enabled = change != "disabled"
        db.commit()


def serve(output: Path) -> None:
    validate_environment()
    import uvicorn
    from app.main import app
    import app.services.rag.grounded_answer_service as grounded

    fixture = read_json(output / "fixture.json")
    original_settings = grounded.get_settings()
    current = ContextVar("round64_window", default={"stage": "normal", "change": "restore"})

    def record(event: str, **details):
        with (output / "windows.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({
                "event": event, "at": datetime.now(timezone.utc).isoformat(),
                "project_id": fixture["project_id"], "version_id": fixture["version_id"],
                "unit_id": fixture["unit_id"], **details,
            }, ensure_ascii=False) + "\n")

    class ControlledSettings:
        @property
        def citation_support_check(self):
            return "judge" if current.get()["stage"] == "judge" else "off"

        def __getattr__(self, name):
            return getattr(original_settings, name)

    async def planner(_db, project_id, original, _history, _settings, **_kwargs):
        if project_id != fixture["project_id"] or not original.startswith(QUERY):
            raise ValueError(INVALID_MESSAGE)
        words = original.split()
        stage = next((value for value in ("generation", "judge") if value in words), "normal")
        change = next((value for value in ("withdrawn", "disabled") if value in words), "restore")
        current.set({"stage": stage, "change": change})
        await asyncio.to_thread(set_fixture, fixture)
        record("fixture_restored_before_retrieval", stage=stage)
        if "invalid" in words:
            raise ValueError(INVALID_MESSAGE)
        return {"queries": [{"query": original, "role": "primary"}], "clarification_question": None}

    async def change_during(stage: str):
        state = current.get()
        if state["stage"] == stage:
            record("window_entered", stage=stage, change=state["change"])
            await asyncio.sleep(0.25)
            await asyncio.to_thread(set_fixture, fixture, state["change"])
            record("mutation_committed", stage=stage, change=state["change"])

    async def generator(*_args, **_kwargs):
        await change_during("generation")
        return ({
            "answer": f"测试值为 BLUE [{fixture['unit_id']}]",
            "supported_claims": [], "unsupported_claims": [], "open_questions": [],
            "confidence_level": "high", "cannot_answer_reason": None,
        }, {"execution_kind": "mock_model", "model_name": "round64-controlled-mock"})

    async def judge(*_args, **_kwargs):
        await change_during("judge")
        return {}

    with patch.object(grounded, "plan_query", planner), \
            patch.object(grounded, "execute_runtime_chat_with_metadata", generator), \
            patch.object(grounded, "check_citation_support", judge), \
            patch.object(grounded, "claim_support_summary", lambda _result: None), \
            patch.object(grounded, "get_settings", lambda: ControlledSettings()):
        uvicorn.run(app, host="127.0.0.1", port=API_PORT, log_level="info")


def start(output: Path) -> dict:
    if output.exists():
        raise FileExistsError("Use a fresh runtime directory")
    for port in (API_PORT, FRONTEND_PORT):
        with socket.socket() as probe:
            probe.settimeout(1)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"Acceptance port occupied: {port}")
    _configure_database()
    os.environ.update({
        "RAG_MODEL_BUDGET_PATH": str(REPOSITORY / "docs/development/long-run/BUDGET.json"),
        "RAG_MODEL_BUDGET_STATE": str(REPOSITORY / ".local-run/rag-long-run/provider-budget.sqlite3"),
        "CORS_ORIGINS": f"http://127.0.0.1:{FRONTEND_PORT}",
        "SERVICE_COMPONENT": "api",
    })
    validate_environment()
    from rag_review_environment import source_identity
    from rag_round46_runtime import _spawn
    import httpx

    identity = source_identity()
    commit = identity["git_head"] + "+worktree." + identity["code_hash"][:12]
    build_time = datetime.now(timezone.utc).isoformat()
    os.environ.update(APP_COMMIT=commit, BUILD_TIME=build_time)
    output.mkdir(parents=True)
    project_id, version_id, unit_id = seed_fixture(output)
    pid = _spawn(output, "api", [
        sys.executable, str(Path(__file__).resolve()), "serve", str(output),
    ], dict(os.environ))
    with httpx.Client(base_url=f"http://127.0.0.1:{API_PORT}", timeout=10, trust_env=False) as client:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                response = client.get("/version")
                if response.status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(1)
        else:
            raise TimeoutError("Independent API startup timed out; preserve its log and process")
        version = response.json()
        if (version["app_commit"] != commit
                or datetime.fromisoformat(version["build_time"]) != datetime.fromisoformat(build_time)):
            raise RuntimeError("Independent API release identity mismatch")
        readiness = client.get("/health/ready")
        if readiness.status_code != 200 or readiness.json().get("status") != "ready":
            raise RuntimeError("Independent API dependencies are not ready")
    result = {
        "round": 64, "api_pid": pid, "api_port": API_PORT, "frontend_port": FRONTEND_PORT,
        "source_hash": identity["code_hash"], "api_identity": version,
        "project_id": project_id, "version_id": version_id, "unit_id": unit_id,
        "source_is_synthetic": True, "gold": False, "holdout": False,
        "query": QUERY, "invalid_message": INVALID_MESSAGE,
        "retrieval": "real_keyword_with_hybrid_no_active_index_degradation",
        "generator": "controlled_mock", "judge": "controlled_mock",
        "external_provider_requests": 0, "external_provider_tokens": 0,
        "existing_vectors_changed": False,
    }
    (output / "runtime.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("start", "serve", "restore"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if args.command == "start":
        start(output)
    elif args.command == "serve":
        serve(output)
    else:
        _configure_database()
        validate_environment()
        set_fixture(read_json(output / "fixture.json"))
        print(json.dumps({"round": 64, "fixture_restored": True}))


if __name__ == "__main__":
    main()
