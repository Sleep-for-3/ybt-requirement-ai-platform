"""HTTP conflicts for evidence changes, with isolated SQLite and controlled models."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.api import knowledge_rag
from app.core.database import get_db
from app.core.settings import get_settings
from app.services.auth.dependencies import Principal, get_current_principal
from app.services.rag import grounded_answer_service as grounded
from app.services.rag.citation_validator import validate_citations
from test_retrieval_eligibility_unified import _seed


CONFLICT_MESSAGE = "回答期间引用资料状态发生变化，本次回答未返回。请重新提问。"


@pytest.fixture
def ask_api(db_session):
    api = FastAPI()
    api.include_router(knowledge_rag.router, prefix="/api")
    api.dependency_overrides[get_db] = lambda: db_session
    api.dependency_overrides[get_current_principal] = lambda: Principal(
        None, "isolated-test", None, True)
    return api


def _mutate(db, document, version, unit, change):
    if change == "withdrawn":
        version.lifecycle_status = "withdrawn"
    elif change == "disabled":
        unit.enabled = False
    elif change == "archived":
        document.document_status = "archived"
    elif change == "content":
        unit.content = "Different evidence."
    elif change == "content_hash":
        unit.content_hash = "e" * 64
    elif change == "scope":
        document.applicable_project_ids_json = [unit.project_id + 100]
    elif change == "unit_scope":
        unit.knowledge_scope = "unavailable"
    elif change == "classification":
        unit.confidentiality_level = "restricted"
    elif change == "version":
        version.regulatory_version = "V2"
    elif change == "deleted":
        db.delete(unit)
    else:
        raise AssertionError(change)
    db.commit()


def _controlled_answer(db, monkeypatch, *, change=None, stage="generation", judge_mode="off"):
    project, document, version, unit = _seed(db, text="The confirmed value is BLUE.")
    version.regulatory_version = "V1"
    db.commit()
    item = {
        "knowledge_unit_id": unit.id, "document_id": document.id,
        "document_version_id": version.id, "content_hash": unit.content_hash,
        "project_id": project.id, "knowledge_scope": unit.knowledge_scope,
        "content": unit.content, "title": document.file_name,
        "document_title": document.file_name, "source_file_name": document.file_name,
        "knowledge_type": unit.knowledge_type, "source_category": "internal_policy",
        "confidentiality_level": unit.confidentiality_level,
        "regulatory_version": "V1", "lifecycle_status": "active",
        "authority_rank": 5, "rerank_score": 1.0,
        "locator": {"block_id": f"knowledge-unit-{unit.id}"},
    }
    calls = {"generation": 0, "judge": 0}
    settings = get_settings()
    monkeypatch.setattr(settings, "citation_support_check", "off" if judge_mode == "off" else "judge")
    monkeypatch.setattr(settings, "rag_token_context_enabled", False)
    monkeypatch.setattr(grounded.HybridRetriever, "search", lambda *_a, **_k: (
        SimpleNamespace(id=None, filters_json={}), [item]))
    monkeypatch.setattr(grounded, "get_prompt_runtime", lambda *_a, **_k: None)
    monkeypatch.setattr(grounded, "evidence_runtime", lambda runtime: runtime)
    monkeypatch.setattr(grounded, "prepare_model_input", lambda *_a, **_k: "isolated evidence")
    monkeypatch.setattr(grounded, "_index_freshness", lambda *_a, **_k: {
        "formal_index_current": True})

    async def plan(_db, _project_id, query, *_a, **_k):
        return {"queries": [{"query": query, "role": "primary"}], "clarification_question": None}

    async def generate(*_a, **_k):
        calls["generation"] += 1
        if change is not None and stage == "generation":
            _mutate(db, document, version, unit, change)
        return {"answer": f"The confirmed value is BLUE [{unit.id}]",
                "confidence_level": "high"}, {"execution_kind": "mock_model"}

    async def judge(*_a, **_k):
        calls["judge"] += 1
        if change is not None and stage == "judge":
            _mutate(db, document, version, unit, change)
        return {
            "enabled": True, "verification": "verified" if judge_mode == "pass" else "degraded",
            "degraded": judge_mode == "fail",
            "supported_claims": [f"The confirmed value is BLUE [{unit.id}]"] if judge_mode == "pass" else [],
            "claims_total": 1, "claims_supported": int(judge_mode == "pass"),
            "claims_unjudged": int(judge_mode == "fail"),
            "claim_coverage": float(judge_mode == "pass"),
        }

    monkeypatch.setattr(grounded, "plan_query", plan)
    monkeypatch.setattr(grounded, "execute_runtime_chat_with_metadata", generate)
    monkeypatch.setattr(grounded, "check_citation_support", judge)
    return project, unit.id, calls


def _submit(api, project_id):
    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(
                app=api, raise_app_exceptions=False), base_url="http://isolated") as client:
            return await client.post(f"/api/projects/{project_id}/knowledge/ask", json={
                "query": "What value is confirmed?", "retrieval_mode": "keyword_only",
            })
    return asyncio.run(request())


@pytest.mark.parametrize("change", ["withdrawn", "disabled"])
@pytest.mark.parametrize("stage,judge_mode", [
    ("generation", "off"), ("generation", "pass"), ("generation", "fail"),
    ("judge", "pass"), ("judge", "fail"),
])
def test_inflight_changes_return_conflict_without_answer(
        db_session, monkeypatch, ask_api, change, stage, judge_mode):
    project, _, calls = _controlled_answer(
        db_session, monkeypatch, change=change, stage=stage, judge_mode=judge_mode)
    response = _submit(ask_api, project.id)
    assert calls["generation"] == 1
    assert calls["judge"] == int(stage == "judge")
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": CONFLICT_MESSAGE}


@pytest.mark.parametrize("change", [
    "archived", "content", "content_hash", "scope", "unit_scope", "classification", "deleted",
])
def test_other_snapshot_changes_use_the_same_safe_conflict(
        db_session, monkeypatch, ask_api, change):
    project, _, calls = _controlled_answer(db_session, monkeypatch, change=change)
    response = _submit(ask_api, project.id)
    assert calls["generation"] == 1
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": CONFLICT_MESSAGE}


@pytest.mark.parametrize("judge_mode", ["off", "pass", "fail"])
def test_unchanged_evidence_still_returns_answer_with_citation(
        db_session, monkeypatch, ask_api, judge_mode):
    project, unit_id, calls = _controlled_answer(db_session, monkeypatch, judge_mode=judge_mode)
    response = _submit(ask_api, project.id)
    assert response.status_code == 200, response.text
    assert unit_id in response.json()["cited_unit_ids"]
    assert unit_id in [item["knowledge_unit_id"] for item in response.json()["citations"]]
    assert calls == {"generation": 1, "judge": int(judge_mode != "off")}
    if judge_mode == "fail":
        assert response.json()["citation_support"]["verification"] == "degraded"


@pytest.mark.parametrize("mode", ["regulatory", "data_field"])
def test_general_value_error_keeps_http_400(db_session, monkeypatch, ask_api, mode):
    project, _, _, _ = _seed(db_session)

    async def invalid(*_a, **_k):
        raise ValueError("Invalid filter value")

    monkeypatch.setattr(knowledge_rag, "grounded_answer" if mode == "regulatory" else "data_field_answer", invalid)
    response = asyncio.run(_post_mode(ask_api, project.id, mode))
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid filter value"}


async def _post_mode(api, project_id, mode):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(
            app=api, raise_app_exceptions=False), base_url="http://isolated") as client:
        return await client.post(f"/api/projects/{project_id}/knowledge/ask", json={
            "query": "What value is confirmed?", "answer_mode": mode,
        })


@pytest.mark.parametrize("change", ["disabled", "unit_scope"])
def test_legacy_validation_without_snapshot_keeps_plain_value_error(db_session, change):
    project, document, version, unit = _seed(db_session)
    citation = {"knowledge_unit_id": unit.id}
    _mutate(db_session, document, version, unit, change)
    with pytest.raises(ValueError) as error:
        validate_citations(db_session, [citation], project_id=project.id)
    assert type(error.value) is ValueError


def test_malformed_citation_with_snapshot_is_still_an_input_error(db_session):
    with pytest.raises(ValueError) as error:
        validate_citations(db_session, [{}], check_governance=True, expected_content={})
    assert type(error.value) is ValueError


@pytest.mark.parametrize("snapshot", [{}, {123: "Unrelated evidence."}])
def test_unknown_citation_is_not_mistaken_for_a_snapshot_change(db_session, snapshot):
    with pytest.raises(ValueError) as error:
        validate_citations(db_session, [{"knowledge_unit_id": 999999}],
                           check_governance=True, expected_content=snapshot)
    assert type(error.value) is ValueError


def test_version_pin_change_is_a_snapshot_conflict(db_session):
    project, document, version, unit = _seed(db_session)
    version.regulatory_version = "V1"
    db_session.commit()
    options = dict(project_id=project.id, check_governance=True,
                   expected_content={unit.id: unit.content},
                   pinned_versions={document.file_name: "V1"})
    validate_citations(db_session, [{"knowledge_unit_id": unit.id}], **options)
    _mutate(db_session, document, version, unit, "version")
    with pytest.raises(ValueError) as error:
        validate_citations(db_session, [{"knowledge_unit_id": unit.id}], **options)
    assert type(error.value).__name__ == "CitationEvidenceChangedError"
