from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeUnit, Project, RetrievalLog
from app.services.retrieval.keyword_index import index_knowledge_unit
from app.services.retrieval.planned_search import query_plan, fuse_rounds
from test_ai_skill_control import control_env

GOLDEN = json.loads((Path(__file__).parent / "fixtures/ai_skill_b3_fusion_golden.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", GOLDEN, ids=[case["name"] for case in GOLDEN])
def test_fixed_rank_fusion_comparison(case, record_property):
    rounds = [[{"knowledge_unit_id": identity, "authority_rank": case["authority"][str(identity)],
                "content_hash": str(identity), "document_version_id": identity, "content": f"synthetic-{identity}"}
               for identity in ids] for ids in case["rounds"]]
    actual = [item["knowledge_unit_id"] for item in fuse_rounds(rounds, case["top_k"])]
    assert actual == case["expected"]
    relevant = set(case["relevant"])
    baseline = len(set(case["rounds"][0][:case["top_k"]]) & relevant) / max(1, len(relevant))
    merged = len(set(actual) & relevant) / max(1, len(relevant))
    record_property("synthetic_baseline_recall", baseline)
    record_property("synthetic_fused_recall", merged)
    assert merged >= baseline
    if case["name"] in {"consensus_promotes_supported_clause", "separate_question_evidence_retained"}:
        assert merged > baseline


def seed_document(db, project_id, content, *, expired=False, category="regulatory_formal"):
    digest = sha256(content.encode()).hexdigest()
    document = KnowledgeDocument(project_id=project_id, file_name="synthetic.txt", file_type="txt",
        source_type="manual", storage_path="fixture-only", document_status="active", source_category=category)
    db.add(document); db.flush()
    version = KnowledgeDocumentVersion(project_id=project_id, document_id=document.id, version_no=1,
        file_name="synthetic.txt", storage_path="fixture-only", file_hash=digest, lifecycle_status="active",
        expires_at=datetime(2000, 1, 1, tzinfo=timezone.utc) if expired else None)
    db.add(version); db.flush(); document.current_version_id = version.id
    unit = KnowledgeUnit(project_id=project_id, document_id=document.id, document_version_id=version.id,
        knowledge_type="regulatory_policy", knowledge_scope="project", unit_type="paragraph", title=content,
        content=content, normalized_content=content, source_file_name="synthetic.txt", content_hash=digest)
    db.add(unit); db.flush(); index_knowledge_unit(db, unit)
    return unit.id


@pytest.mark.parametrize("query,count", [("余额", 1), ("余额？利率？", 3), ("余额；余额；利率", 3),
    ("余额；利率；合同", 4), ("一；二；三；四", 1), ('说明 "A;B"；余额', 1), ("account.balance", 1)])
def test_plan_is_literal_bounded_and_preserves_full_query(query, count):
    plan = query_plan(query)
    assert plan["queries"][0] == query
    assert len(plan["queries"]) == count
    assert all(part in query for part in plan["queries"])
    assert plan["retrieval_mode"] == "keyword_only"


def test_fusion_deduplicates_prefers_authority_and_rejects_changed_evidence():
    def item(identity, authority):
        return {"knowledge_unit_id": identity, "authority_rank": authority, "content_hash": str(identity),
                "document_version_id": identity, "content": "fixed"}
    formal, informal = item(1, 6), item(2, 1)
    result = fuse_rounds([[informal, formal, formal], [informal]], 2)
    assert [item["knowledge_unit_id"] for item in result] == [1, 2]
    assert len(result[0]["retrieval_rounds"]) == 1
    assert len(result[1]["retrieval_rounds"]) == 2
    with pytest.raises(HTTPException) as error:
        fuse_rounds([[formal], [{**formal, "content_hash": "changed"}]], 2)
    assert error.value.status_code == 409


def environment(env):
    from app.api.knowledge_rag import router
    client, factory, login, scope, _ = env
    client.app.include_router(router)
    login("manager")
    with factory() as db:
        first = seed_document(db, scope["project_id"], "余额 balance")
        second = seed_document(db, scope["project_id"], "利率 interest_rate")
        seed_document(db, scope["project_id"], "余额 利率 过期", expired=True)
        foreign = db.scalar(select(Project).where(Project.id != scope["project_id"]))
        seed_document(db, foreign.id, "余额 利率 私有")
        db.commit()
    return f'/projects/{scope["project_id"]}/knowledge/planned-search', {first, second}


def test_real_retrieval_fixed_filters_evidence_and_audit(control_env, monkeypatch):
    from app.services.retrieval import hybrid_retriever
    route, expected = environment(control_env)
    def forbidden(*args, **kwargs):
        pytest.fail("Planned keyword search must not initialize an external provider")
    monkeypatch.setattr(hybrid_retriever, "get_embedding_service", forbidden)
    monkeypatch.setattr(hybrid_retriever, "get_vector_store", forbidden)
    response = control_env[0].post(route, json={"query": "balance；interest_rate", "top_k": 10,
        "knowledge_types": ["regulatory_policy"]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["rounds"]) == 3
    assert {item["knowledge_unit_id"] for item in result["items"]} == expected
    assert all(item["citation_id"] and item["content_hash"] and item["retrieval_rounds"] for item in result["items"])
    assert "私有" not in response.text and "过期" not in response.text
    with control_env[1]() as db:
        logs = list(db.scalars(select(RetrievalLog)))
        assert len(logs) == 4 and all(log.created_by == "manager" for log in logs)
        assert logs[-1].filters_json["child_log_ids"] == [log.id for log in logs[:-1]]
    # Explicit type filters must survive every subquery.
    assert control_env[0].post(route, json={"query": "余额；利率", "knowledge_types": ["manual_note"]}).json()["items"] == []


@pytest.mark.parametrize("identity,status", [("outsider", 404), ("legacy", 401)])
def test_identity_rejected_before_planning(control_env, monkeypatch, identity, status):
    from app.services.retrieval import planned_search
    route, _ = environment(control_env)
    control_env[2](identity)
    monkeypatch.setattr(planned_search, "query_plan", lambda _: pytest.fail("Must authorize before planning"))
    assert control_env[0].post(route, json={"query": "余额；利率"}).status_code == status


@pytest.mark.parametrize("payload", [{"query": " "}, {"query": "x" * 2001}, {"query": "余额", "top_k": True},
    {"query": "余额", "retrieval_mode": "hybrid"}, {"query": "余额", "include_history": True}])
def test_planning_budgets_and_mode_cannot_be_bypassed(control_env, payload):
    route, _ = environment(control_env)
    assert control_env[0].post(route, json=payload).status_code == 422


def test_invalid_scope_and_failed_round_leave_no_partial_logs(control_env, monkeypatch):
    from app.services.retrieval.planned_search import HybridRetriever
    route, _ = environment(control_env)
    assert control_env[0].post(route, json={"query": "余额；利率", "target_field_id": 999999}).status_code == 404
    original = HybridRetriever.search
    calls = []
    def fail_second(self, *args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise HTTPException(409, "synthetic round failure")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(HybridRetriever, "search", fail_second)
    assert control_env[0].post(route, json={"query": "余额；利率"}).status_code == 409
    with control_env[1]() as db:
        assert db.scalar(select(func.count()).select_from(RetrievalLog)) == 0


def test_evidence_disabled_between_rounds_is_not_returned(control_env, monkeypatch):
    from app.services.retrieval.planned_search import HybridRetriever
    route, expected = environment(control_env)
    original = HybridRetriever.search
    def disable_first(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        self.db.get(KnowledgeUnit, min(expected)).enabled = False
        self.db.flush()
        return result
    monkeypatch.setattr(HybridRetriever, "search", disable_first)
    response = control_env[0].post(route, json={"query": "余额；利率"})
    assert response.status_code == 409, response.text
    with control_env[1]() as db:
        assert db.scalar(select(func.count()).select_from(RetrievalLog)) == 0
