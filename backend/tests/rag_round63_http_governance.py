"""Verify the HTTP boundary for in-flight evidence withdrawal on isolated PostgreSQL."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import traceback
from pathlib import Path
import sys
from unittest.mock import patch

import httpx

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

from rag_round60_inflight_governance import _configure_database, _json, RUNTIME

QUERY = "Round63 R63HTTP6182 what value is confirmed?"
SOURCE = b"Round63 R63HTTP6182 confirms BLUE only."
CONFLICT_MESSAGE = "回答期间引用资料状态发生变化，本次回答未返回。请重新提问。"


async def exercise(project_id: int, version_id: int, unit_id: int, credentials: dict,
                   output: Path) -> list[dict]:
    from app.core.database import SessionLocal
    from app.main import app
    from app.models import KnowledgeDocumentVersion, KnowledgeUnit
    import app.services.rag.grounded_answer_service as grounded

    settings = grounded.get_settings()
    if settings.llm_provider != "mock":
        raise RuntimeError("This acceptance requires a Mock LLM")
    if settings.vector_store_provider != "milvus":
        raise RuntimeError("Expected the isolated formal runtime configuration")
    results = []
    state = {"stage": "normal", "change": None, "generator_calls": 0, "judge_calls": 0}
    mutations = []

    def change_evidence(change: str | None) -> None:
        with SessionLocal() as db:
            version = db.get(KnowledgeDocumentVersion, version_id)
            unit = db.get(KnowledgeUnit, unit_id)
            if (version is None or unit is None or version.project_id != project_id
                    or unit.project_id != project_id or unit.document_version_id != version_id):
                raise RuntimeError("The acceptance fixture identity changed")
            version.lifecycle_status = "withdrawn" if change == "withdrawn" else "active"
            unit.enabled = change != "disabled"
            db.commit()
        mutations.append({"change": change or "restore", "committed_at": datetime.now(timezone.utc).isoformat()})

    class ControlledSettings:
        @property
        def citation_support_check(self):
            return "judge" if state["stage"] == "judge" else "off"

        def __getattr__(self, name):
            return getattr(settings, name)

    async def planner(_db, _project_id, original, _history, _settings, **_kwargs):
        return {"queries": [{"query": original, "role": "primary"}], "clarification_question": None}

    async def generator(*_args, **_kwargs):
        state["generator_calls"] += 1
        if state["stage"] == "generation":
            await asyncio.to_thread(change_evidence, state["change"])
        return ({
            "answer": f"测试值为 BLUE [{unit_id}]",
            "supported_claims": [],
            "unsupported_claims": [],
            "open_questions": [],
            "confidence_level": "high",
            "cannot_answer_reason": None,
        }, {"execution_kind": "mock_model", "model_name": "round63-controlled-mock"})

    async def judge(*_args, **_kwargs):
        state["judge_calls"] += 1
        await asyncio.to_thread(change_evidence, state["change"])
        return {}

    with patch.object(grounded, "plan_query", planner), \
            patch.object(grounded, "execute_runtime_chat_with_metadata", generator), \
            patch.object(grounded, "check_citation_support", judge), \
            patch.object(grounded, "claim_support_summary", lambda _result: None), \
            patch.object(grounded, "get_settings", lambda: ControlledSettings()):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://isolated-asgi", timeout=180) as client:
            login = await client.post("/api/auth/login", json=credentials)
            if login.status_code != 200:
                raise RuntimeError("Isolated HTTP authentication failed")
            client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
            results.append({"name": "real_authentication_over_asgi", "passed": True, "http_status": 200})

            async def submit(name: str, changed: bool) -> None:
                response = await client.post(f"/api/projects/{project_id}/knowledge/ask", json={
                    "query": QUERY, "retrieval_mode": "keyword_only", "top_k": 5,
                })
                body = response.json()
                used = [item.get("knowledge_unit_id") for item in body.get("citations", [])]
                if changed:
                    passed = (
                        response.status_code == 409
                        and body.get("detail") == CONFLICT_MESSAGE
                        and "answer" not in body and not used
                    )
                else:
                    passed = response.status_code == 200 and unit_id in used
                results.append({
                    "name": name, "passed": passed, "http_status": response.status_code,
                    "answer_present": "answer" in body,
                    "target_cited": unit_id in used,
                    "stage": state["stage"], "change": state["change"],
                    "generator_calls": state["generator_calls"], "judge_calls": state["judge_calls"],
                    "mutation_count": len(mutations),
                    "safe_detail": body.get("detail") if isinstance(body.get("detail"), str) else None,
                })
                if not passed:
                    (output / "partial-results.json").write_text(
                        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    raise AssertionError(f"HTTP governance acceptance failed: {name}")

            try:
                await submit("unchanged_evidence_returns_http_200_with_citation", False)
                for change in ("withdrawn", "disabled"):
                    for stage in ("generation", "judge"):
                        state.update(stage=stage, change=change)
                        before_generator = state["generator_calls"]
                        before_judge = state["judge_calls"]
                        await submit(f"{change}_during_{stage}_returns_409_without_answer", True)
                        if state["generator_calls"] != before_generator + 1:
                            raise AssertionError("The selected generation window was not reached")
                        if stage == "judge" and state["judge_calls"] != before_judge + 1:
                            raise AssertionError("The selected judge window was not reached")
                        await asyncio.to_thread(change_evidence, None)
                        state.update(stage="normal", change=None)
                        await submit(f"restored_after_{change}_{stage}_returns_200", False)
                async def invalid(*_args, **_kwargs):
                    raise ValueError("Invalid filter value")
                with patch("app.api.knowledge_rag.grounded_answer", invalid):
                    response = await client.post(f"/api/projects/{project_id}/knowledge/ask", json={
                        "query": QUERY, "retrieval_mode": "keyword_only",
                    })
                passed = (response.status_code == 400
                          and response.json().get("detail") == "Invalid filter value")
                results.append({"name": "ordinary_value_error_remains_400", "passed": passed,
                                "http_status": response.status_code,
                                "safe_detail": response.json().get("detail")})
                if not passed:
                    (output / "partial-results.json").write_text(
                        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    raise AssertionError("Ordinary validation error mapping changed")
            finally:
                await asyncio.to_thread(change_evidence, None)
    return results


def seed_fixture(output: Path) -> tuple[int, int, int]:
    from app.core.database import SessionLocal
    from app.models import KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeUnit, Project
    from app.services.retrieval.keyword_index import index_knowledge_unit

    institution_id = _json(RUNTIME / "bootstrap-state.json")["institution_id"]
    with SessionLocal() as db:
        project = Project(name="RAG Round63 HTTP isolated acceptance",
                          bank_name="RAG isolated HTTP acceptance", institution_id=institution_id)
        db.add(project)
        db.flush()
        document = KnowledgeDocument(
            project_id=project.id, file_name="round63-http-policy.txt", file_type="txt",
            source_type="upload", storage_path="round63-synthetic-not-for-preview",
            document_status="indexed", source_category="internal_policy",
        )
        db.add(document)
        db.flush()
        version = KnowledgeDocumentVersion(
            project_id=project.id, document_id=document.id, version_no=1,
            file_name=document.file_name, storage_path=document.storage_path,
            file_hash=hashlib.sha256(SOURCE).hexdigest(),
            lifecycle_status="active", regulatory_version="R63-HTTP-V1",
        )
        db.add(version)
        db.flush()
        document.current_version_id = version.id
        document.current_version_no = 1
        unit = KnowledgeUnit(
            project_id=project.id, document_id=document.id, document_version_id=version.id,
            knowledge_type="regulatory_policy", knowledge_scope="project", unit_type="paragraph",
            content=SOURCE.decode(), normalized_content=SOURCE.decode(),
            source_file_name=document.file_name, confidentiality_level="internal", enabled=True,
            content_hash=version.file_hash,
        )
        db.add(unit)
        db.flush()
        index_knowledge_unit(db, unit)
        identities = (project.id, version.id, unit.id)
        db.commit()
    (output / "fixture.json").write_text(json.dumps({
        "project_id": identities[0], "version_id": identities[1], "unit_id": identities[2],
        "source_is_synthetic": True, "gold": False, "holdout": False,
        "fixture_mode": "new_orm_rows_keyword_index_no_upload_or_vector_index",
    }, indent=2) + "\n", encoding="utf-8")
    return identities


def run(output: Path) -> dict:
    if output.exists():
        raise FileExistsError("Use a new attempt directory")
    output.mkdir(parents=True)
    credentials = _configure_database()
    from app.core.settings import get_settings
    from sqlalchemy.engine import make_url
    from rag_review_environment import source_identity

    settings = get_settings()
    database = make_url(settings.database_url)
    if (settings.llm_provider != "mock" or settings.embedding_provider != "local_vllm"
            or settings.vector_store_provider != "milvus"
            or database.host != "127.0.0.1" or database.port != 15442
            or database.database != "ragp0"
            or settings.milvus_collection_prefix != "rag_p0_r53_formal"):
        raise RuntimeError("Only the owned Round53 local isolation is allowed")
    identity = source_identity()
    project_id, version_id, unit_id = seed_fixture(output)
    checks = asyncio.run(exercise(project_id, version_id, unit_id, credentials, output))
    return {
        "round": 63, "checked_at": datetime.now(timezone.utc).isoformat(),
        "evidence_tier": "in_process_asgi_http_real_auth_postgresql_controlled_candidate_snapshot_and_models",
        "source": {"git_head": identity["git_head"], "code_hash": identity["code_hash"],
                   "served_by": "current_in_process_application"},
        "project_id": project_id, "version_id": version_id, "unit_id": unit_id,
        "source_is_synthetic": True, "gold": False, "holdout": False,
        "retrieval_mode": "controlled_candidate_snapshot", "milvus_index_created": False,
        "existing_milvus_vectors_changed": False,
        "checks": checks, "passed": sum(item["passed"] for item in checks),
        "failed": sum(not item["passed"] for item in checks),
        "external_provider_requests": 0, "external_provider_tokens": 0,
        "existing_fixtures_changed": False, "remote_write": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    output = parser.parse_args().output.resolve()
    try:
        result = run(output)
    except Exception as error:
        if output.exists() and not (output / "results.json").exists():
            (output / "failure-attempt.json").write_text(json.dumps({
                "round": 63, "error_type": type(error).__name__,
                "error_message": str(error)[:240],
                "traceback": traceback.format_exc(limit=6),
            }, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"round": 63, "error_type": type(error).__name__,
                          "error_message": str(error)[:240]}))
        return 1
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"round": 63, "passed": result["passed"], "failed": result["failed"]}))
    return int(bool(result["failed"]))


if __name__ == "__main__":
    raise SystemExit(main())
