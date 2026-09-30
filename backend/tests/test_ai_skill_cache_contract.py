"""Cache boundary exercised with real fixed lineage, permissions and run logs."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import (KnowledgeDocumentVersion, ModelCallLog,
                        ModelProfile, Project, ProjectMembership, User)
from app.services.ai_skills import cache_contract as cache
from app.services.ai_skills import runtime
from app.services.ai_skills.lineage_adapter import HybridRetriever
from app.services.auth.dependencies import Principal
from app.services.lineage.explanation import LineageEdgeExplanationRequest, explain_lineage_edge
from test_ai_skill_control import control_env
from test_ai_skill_lineage_adapter import seeded_env
from test_requirement_resources import add_document
from test_requirement_generation_input import add_unit


@pytest.fixture
def cache_env(control_env):
    env, seeded, edge_id, principal = seeded_env(control_env)
    request = LineageEdgeExplanationRequest(edge_id=edge_id, revision_id=seeded["revision_id"])
    return env, seeded["project_id"], principal, request


def create_candidate(db, project_id, principal, request):
    access = cache.prepare_lineage_access(db, principal, project_id, request)
    result = asyncio.run(explain_lineage_edge(db, project_id, request, principal=principal))["skill_result"]
    candidate = cache.make_candidate(db, access, result)
    assert candidate is not None
    return candidate


def test_hit_rebuilds_evidence_without_new_model_execution(cache_env, monkeypatch):
    env, project_id, principal, request = cache_env
    with env[1]() as db:
        candidate = create_candidate(db, project_id, principal, request)
        before = db.scalar(select(func.count()).select_from(ModelCallLog))
        monkeypatch.setattr(runtime, "get_runtime_llm_service", lambda *a, **k: pytest.fail("cache lookup called model"))
        hit = cache.lookup_lineage_candidate(db, principal, project_id, request, candidate)
        assert hit["facts"]
        assert hit["provenance"]["execution_kind"] == "deterministic"
        assert hit["provenance"]["origin_execution_kind"] == "mock_model"
        assert hit["provenance"]["origin_run_id"] == candidate.origin_run_id
        assert db.scalar(select(func.count()).select_from(ModelCallLog)) == before
        assert cache.lookup_lineage_candidate(db, principal, project_id, request, candidate, force_refresh=True) is None


@pytest.mark.parametrize("change", ["expired", "tampered", "model_identity", "failed_run", "classification", "role"])
def test_invalidated_candidates_are_misses(cache_env, change):
    env, project_id, principal, request = cache_env
    with env[1]() as db:
        candidate = create_candidate(db, project_id, principal, request)
        if change == "expired":
            candidate = replace(candidate, expires_at=datetime.now(timezone.utc)-timedelta(seconds=1))
        elif change == "tampered":
            result = deepcopy(candidate.result)
            result["claims"] = [{"claim_type": "observed_fact", "text": "invented", "fact_ids": ["unknown"]}]
            candidate = replace(candidate, result=result)
        elif change == "model_identity":
            db.get(ModelCallLog, candidate.origin_run_id).model_name = "unapproved-model"
        elif change == "failed_run":
            db.get(ModelCallLog, candidate.origin_run_id).status = "failed"
        elif change == "classification":
            db.get(Project, project_id).confidentiality_level = "confidential"
        else:
            member = db.scalar(select(ProjectMembership).where(ProjectMembership.project_id == project_id,
                ProjectMembership.user_id == principal.user_id))
            member.project_role = "viewer"
        db.commit()
        assert cache.lookup_lineage_candidate(db, principal, project_id, request, candidate) is None


@pytest.mark.parametrize("change", ["revoked", "cross_tenant", "legacy", "profile_drift"])
def test_authorization_and_pinned_route_precede_hit(cache_env, change):
    env, project_id, principal, request = cache_env
    with env[1]() as db:
        candidate = create_candidate(db, project_id, principal, request)
        if change == "revoked":
            db.scalar(select(ProjectMembership).where(ProjectMembership.project_id == project_id,
                ProjectMembership.user_id == principal.user_id)).status = "inactive"
        elif change == "cross_tenant":
            user = db.scalar(select(User).where(User.username == "outsider"))
            principal = Principal(user.id, user.username, None)
        elif change == "legacy":
            principal = Principal(None, "legacy", None, True)
        else:
            db.get(ModelProfile, env[4]["model_profile_id"]).model_name = "changed-after-release"
        db.commit()
        with pytest.raises(HTTPException) as error:
            cache.lookup_lineage_candidate(db, principal, project_id, request, candidate)
        assert error.value.status_code in {401, 403, 404, 409}


def test_other_authorized_actor_cannot_reuse_candidate(cache_env):
    env, project_id, principal, request = cache_env
    with env[1]() as db:
        candidate = create_candidate(db, project_id, principal, request)
        user = db.scalar(select(User).where(User.username == "bank_admin"))
        other = Principal(user.id, user.username, None)
        assert cache.lookup_lineage_candidate(db, other, project_id, request, candidate) is None


@pytest.mark.parametrize("change", ["withdrawn", "expired", "disabled"])
def test_clause_effectivity_is_rechecked_before_hit(cache_env, monkeypatch, change):
    env, project_id, principal, request = cache_env
    with env[1]() as db:
        document = add_document(db, project_id, "cache synthetic policy")
        document.source_category = "regulatory_formal"
        unit = add_unit(db, project_id, document, "余额按期末报送。")
        unit.source_heading = "第十二条"
        version = db.get(KnowledgeDocumentVersion, unit.document_version_id)
        version.lifecycle_status = "active"
        document.current_version_id = version.id
        db.commit()
        unit_id = unit.id
        monkeypatch.setattr(HybridRetriever, "search", lambda *a, **k: (None, [{"knowledge_unit_id": unit_id}]))
        candidate = create_candidate(db, project_id, principal, request)
        assert candidate.result["policy_evidence"]
        if change == "withdrawn":
            version.lifecycle_status = "withdrawn"
        elif change == "expired":
            version.expires_at = datetime.now(timezone.utc)-timedelta(days=1)
        else:
            unit.enabled = False
        db.commit()
        assert cache.lookup_lineage_candidate(db, principal, project_id, request, candidate) is None


def test_degraded_or_test_run_is_not_cacheable(cache_env):
    env, project_id, principal, request = cache_env
    with env[1]() as db:
        candidate = create_candidate(db, project_id, principal, request)
        access = cache.prepare_lineage_access(db, principal, project_id, request)
        log = db.get(ModelCallLog, candidate.origin_run_id)
        log.execution_metadata_json = {**log.execution_metadata_json, "is_test": True}
        db.flush()
        assert cache.make_candidate(db, access, candidate.result) is None
        with pytest.raises(HTTPException):
            cache.make_candidate(db, access, candidate.result, ttl_seconds=301)
