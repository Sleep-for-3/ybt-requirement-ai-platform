import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import InstitutionMembership, LineageRevision, ModelProfile, Project, ProjectMembership, User
from app.services.ai_skills.lineage_adapter import bounded_paths
from app.services.ai_skills import runtime
from app.services.auth.dependencies import Principal
from app.services.lineage.explanation import LineageEdgeExplanationRequest, explain_lineage_edge
from app.services.lineage.path_resolver import revision_edge_output_id
from app.services.lineage.revisions import LineageRevisionService
from test_ai_skill_control import control_env
from test_ai_skill_releases import ready, publish
from test_lineage_graph_contract import _seed_chain


def seeded_env(env):
    client, factory, login, scope, content = env
    with factory() as db:
        seeded = _seed_chain(db, code="SKILL")
        project = db.get(Project, seeded["project_id"])
        project.institution_id = scope["institution_id"]
        manager = db.scalar(select(User).where(User.username == "manager"))
        db.add(ProjectMembership(project_id=project.id, user_id=manager.id, project_role="project_manager", status="active"))
        model = db.get(ModelProfile, content["model_profile_id"])
        model.max_context_tokens = 64000
        db.commit()
        revision = db.get(LineageRevision, seeded["revision_id"])
        _, edges = LineageRevisionService(db).members(revision)
        edge_id = revision_edge_output_id(revision.id, edges[0]["edge_key"])
        principal = Principal(manager.id, manager.username, None)
    scope = dict(scope, project_id=seeded["project_id"])
    updated = client, factory, login, scope, content
    ready(updated)
    assert publish(updated).status_code == 200
    return updated, seeded, edge_id, principal


def test_published_skill_runs_on_authorized_fixed_lineage(control_env):
    env, seeded, edge_id, principal = seeded_env(control_env)
    with env[1]() as db:
        result = asyncio.run(explain_lineage_edge(db, seeded["project_id"], LineageEdgeExplanationRequest(
            edge_id=edge_id, revision_id=seeded["revision_id"]), principal=principal))
        assert result["status"] == "ready"
        assert result["execution_metadata"]["runtime_mode"] == "skill"
        assert result["execution_metadata"]["run_id"]
        assert result["execution_metadata"]["execution_kind"] == "mock_model"
        assert result["ai"]["regulatory_status"] == "missing_basis"
        assert result["human_confirmation"]["status"] == "pending"
        assert any(fact["kind"] == "bounded_paths" for fact in result["facts"])
        assert any(gap["code"] == "missing_basis" for gap in result["skill_result"]["gaps"])
        assert not any(gap["code"] == "policy_retrieval_failed" for gap in result["skill_result"]["gaps"])


def test_skill_provider_failure_keeps_fixed_facts(control_env, monkeypatch):
    env, seeded, edge_id, principal = seeded_env(control_env)
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(runtime, "get_runtime_llm_service", fail)
    with env[1]() as db:
        result = asyncio.run(explain_lineage_edge(db, seeded["project_id"], LineageEdgeExplanationRequest(
            edge_id=edge_id, revision_id=seeded["revision_id"]), principal=principal))
        assert result["status"] == "degraded"
        assert result["facts"]
        assert result["ai"] is None
        assert result["skill_result"]["claims"] == []


def test_bounded_path_caps_are_explicit_not_silent():
    selected = {"source_node_key": "b", "target_node_key": "c"}
    edges = [{"source_node_key": "a", "target_node_key": "b"},
             {"source_node_key": "z", "target_node_key": "a"},
             {"source_node_key": "c", "target_node_key": "d"}]
    paths, gaps = bounded_paths(edges, selected, 1, 10)
    assert any(gap.code == "path_depth_boundary" for gap in gaps)
    assert any(not path["complete"] for path in paths)
    with pytest.raises(HTTPException) as error:
        bounded_paths(edges, selected, 3, 1)
    assert error.value.detail["error_code"] == "path_scope_exceeded"


def test_policy_search_failure_preserves_facts_and_explicit_gap(control_env, monkeypatch):
    from app.services.ai_skills.lineage_adapter import HybridRetriever
    env, seeded, edge_id, principal = seeded_env(control_env)
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic retrieval failure")
    monkeypatch.setattr(HybridRetriever, "search", fail)
    with env[1]() as db:
        result = asyncio.run(explain_lineage_edge(db, seeded["project_id"], LineageEdgeExplanationRequest(
            edge_id=edge_id, revision_id=seeded["revision_id"]), principal=principal))
        assert result["facts"]
        assert result["ai"]["regulatory_status"] == "missing_basis"
        assert any(gap["code"] == "policy_retrieval_failed" for gap in result["skill_result"]["gaps"])


@pytest.mark.parametrize("invalid", [None, "expired", "withdrawn", "disabled", "technical", "locator", "other_project"])
def test_policy_clause_authority_rechecked_after_retrieval(control_env, monkeypatch, invalid):
    from datetime import datetime, timedelta, timezone
    from app.models import KnowledgeDocumentVersion
    from app.schemas.ai_skill import SkillScope
    from app.services.ai_skills.lineage_adapter import HybridRetriever, policy_clauses
    from test_requirement_resources import add_document
    from test_requirement_generation_input import add_unit
    _, factory, _, scope, _ = control_env
    with factory() as db:
        project = db.get(Project, scope["project_id"])
        owner_id = db.scalar(select(Project.id).where(Project.id != project.id)) if invalid == "other_project" else project.id
        document = add_document(db, owner_id, "有效条款测试")
        document.source_category = "technical_evidence" if invalid == "technical" else "regulatory_formal"
        unit = add_unit(db, owner_id, document, "余额应按期末余额报送。" * 150)
        unit.source_heading = "口径说明" if invalid == "locator" else "第十二条"
        unit.enabled = invalid != "disabled"
        version = db.get(KnowledgeDocumentVersion, unit.document_version_id)
        version.lifecycle_status = "withdrawn" if invalid == "withdrawn" else "active"
        if invalid == "expired":
            version.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        document.current_version_id = version.id
        db.commit()
        monkeypatch.setattr(HybridRetriever, "search", lambda *args, **kwargs: (None, [
            {"knowledge_unit_id": unit.id, "document_id": 999999, "document_version_id": 999999, "content": "untrusted search metadata"}]))
        evidence, citations, gaps = policy_clauses(db, project,
            {"source": {"technical_name": "balance"}, "target": {"technical_name": "balance"}}, SkillScope.model_validate(scope), 12)
        if invalid:
            assert evidence == [] and citations == []
            assert any(gap.code == "missing_basis" for gap in gaps)
        else:
            assert evidence[0].value["text"] == unit.content
            assert citations[0]["quoted_content"] == unit.content
            assert citations[0]["document_id"] == document.id
            assert citations[0]["document_version_id"] == version.id
