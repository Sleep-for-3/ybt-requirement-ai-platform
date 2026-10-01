"""B3-R1: explicit, bounded model rerank of an authorized field-candidate snapshot.

Every case here is Mock, deterministic or explicitly stubbed transport.  No real provider is
called, so nothing in this file is evidence of ranking quality.
"""
import re

import pytest
from sqlalchemy import func, select

from app.models import (AISkillVersion, CatalogColumn, DataSource, ModelCallLog, ModelProfile, Project,
                        ProjectMembership, User)
from app.schemas.ai_skill import EvidenceSource, SkillEvidence, SkillInputEnvelope, SkillScope
from app.schemas.ai_skill_ranking import FieldRankingCandidate, RankedCandidate, validate_field_ranking
from app.services.ai_skills import field_rerank
from app.services.llm.base import LLMProviderError, ModelCallMetadata
from app.services.llm.mock import MockLLMService
from app.services.llm.prompt_runtime import PromptRuntime, prepare_model_input
from app.services.security.content_redactor import ensure_external_allowed
from test_ai_skill_control import control_env
from test_ai_skill_field_candidates import seeded

RERANK_ROOT = "/ai-skills/field_semantic_matching"
RERANK_PATH = "/ai-skills/field-candidates/model-rerank"


def envelope_for(scope, ids=("catalog:1", "catalog:2"), confidentiality="internal"):
    facts = [SkillEvidence(id=value, kind="catalog_field", value={"column_name": value},
                           source=EvidenceSource(source_type="catalog_column", source_id=value.split(":")[1],
                                                 source_version="catalog-v1", locator=value, scope=scope),
                           confidentiality=confidentiality) for value in ids]
    return SkillInputEnvelope(skill_key="field_semantic_matching", task_key="field_semantic_matching",
                              scope=scope, subject_ref="field_candidates:1", facts=facts)


def cloud_transport(calls):
    """Stand-in for the cloud transport so the release gate can pass without a real provider."""

    class CloudTransport:
        def __init__(self, *args, **kwargs):
            self.provider = "openai_compatible"
            self.model = "stub-cloud"
            self.last_call = ModelCallMetadata(provider="openai_compatible", model="stub-cloud",
                                               token_usage={"usage_available": False})

        async def chat_structured(self, system_prompt, user_prompt, response_schema):
            calls.append(system_prompt)
            ids = list(dict.fromkeys(re.findall(r"catalog:[1-9][0-9]*", user_prompt)))
            return response_schema.model_validate({"claims": [], "gaps": [], "candidate": {"ranking": [
                {"candidate_id": value, "score": round(1.0 - index * 0.01, 6), "rationale": "stub",
                 "evidence_refs": [value]} for index, value in enumerate(ids)]}})

    return CloudTransport


def bind_rerank_skill(env, monkeypatch=None, calls=None, cloud=False):
    """Publish and pin a field_semantic_matching Skill through the real release gate."""

    client, factory, login, scope, content = env
    model_id = content["model_profile_id"]
    if cloud:
        with factory() as db:
            profile = ModelProfile(profile_name="cloud-stub", provider_type="openai_compatible",
                                   model_name="stub-cloud", local_only=False, enabled=True,
                                   max_context_tokens=64000)
            db.add(profile)
            db.commit()
            model_id = profile.id
        monkeypatch.setattr("app.services.llm.factory.OpenAICompatibleLLMService", cloud_transport(calls))
    login("platform")
    definition = client.post("/ai-skills", json={"skill_key": "field_semantic_matching",
                                                 "task_key": "field_semantic_matching", "display_name": "字段候选重排"})
    assert definition.status_code == 201, definition.text
    login("manager")
    version = client.post(RERANK_ROOT + "/versions", json={"scope": scope, "content": {
        "system_prompt": "仅重排给定候选，不新增字段。", "model_profile_id": model_id,
        "output_schema_key": "field_ranking_v1"}})
    assert version.status_code == 201, version.text
    number = version.json()["version_no"]
    case = envelope_for(scope, confidentiality="internal" if cloud else "confidential")
    created = client.post(RERANK_ROOT + "/test-cases", json={"name": "固定重排样例",
                                                             "input": case.model_dump(mode="json")})
    assert created.status_code == 201, created.text
    for lock, mode in ((1, "deterministic"), (2, "real_model" if cloud else "mock_model")):
        run = client.post(RERANK_ROOT + "/test-runs", json={"version": number, "project_id": scope["project_id"],
                                                            "mode": mode, "expected_lock_version": lock})
        assert run.status_code == 201, run.text
        assert run.json()["status"] == "passed", run.text
    submitted = client.post(RERANK_ROOT + f"/versions/{number}/submit",
                            json={"expected_lock_version": 3, "test_project_id": scope["project_id"]})
    assert submitted.status_code == 200, submitted.text
    login("bank_admin")
    published = client.post(RERANK_ROOT + f"/versions/{number}/publish",
                            json={"expected_lock_version": 4, "test_project_id": scope["project_id"]})
    assert published.status_code == 200, published.text
    login("manager")
    return version.json()


def recall(client, query):
    response = client.post("/ai-skills/field-candidates", json=query)
    assert response.status_code == 200, response.text
    return response.json()


def submit_rerank(client, query, snapshot, **overrides):
    return client.post(RERANK_PATH, json={"input": query, "context_hash": snapshot["context_hash"], **overrides})


def log_count(factory):
    with factory() as db:
        return db.scalar(select(func.count()).select_from(ModelCallLog))


def broken_mock(mutation):
    class BrokenMock(MockLLMService):
        async def chat_json(self, system_prompt, user_prompt):
            payload = await super().chat_json(system_prompt, user_prompt)
            if not system_prompt.startswith("[AI_SKILL_FIELD_RERANK_V1]"):
                return payload
            ranking = payload["candidate"]["ranking"]
            if mutation == "unknown":
                ranking[0]["candidate_id"] = "catalog:999999"
            elif mutation == "duplicate":
                ranking[0] = dict(ranking[1])
            elif mutation == "missing":
                ranking.pop()
            elif mutation == "out_of_range":
                ranking[0]["score"] = 1.5
            else:
                ranking[0]["evidence_refs"] = ["catalog:999999"]
            return payload

    return BrokenMock


@pytest.fixture(autouse=True)
def _default_outbound_policy(monkeypatch):
    """These tests assert the conservative default, so pin the outbound allowlist to empty: the
    ambient backend/.env may authorize demo projects, which must not change the policy under test."""
    from app.core.settings import get_settings
    monkeypatch.setattr(get_settings(), "ai_external_model_allowed_project_ids", "", raising=False)

def test_explicit_mock_rerank_keeps_the_whitelist_and_writes_no_business_state(control_env):
    query, _ = seeded(control_env)
    client, factory, _, _, _ = control_env
    version = bind_rerank_skill(control_env)
    baseline = recall(client, query)
    before = log_count(factory)
    response = submit_rerank(client, query, baseline)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ranking_mode"] == "model_rerank"
    assert body["execution_metadata"]["execution_kind"] == "mock_model"
    assert body["execution_metadata"]["provider_type"] == "mock"
    assert body["requires_human_confirmation"] is True and body["writes_mapping"] is False
    assert body["rerank"]["status"] == "applied" and body["rerank"]["error_code"] is None
    assert body["rerank"]["skill_version"]["version_no"] == version["version_no"]
    assert body["rerank"]["binding_scope"].startswith("project:")
    assert body["rerank"]["run_id"] is not None
    assert body["scanned_count"] == baseline["scanned_count"] == 2
    baseline_by_id = {item["candidate_id"]: item for item in baseline["candidates"]}
    assert {item["candidate_id"] for item in body["candidates"]} == set(baseline_by_id)
    # Mock reverses the supplied order, so the displayed order must actually differ.
    assert [item["candidate_id"] for item in body["candidates"]] == list(reversed(list(baseline_by_id)))
    for item in body["candidates"]:
        assert item["rank_source"] == "model"
        assert item["score"] != item["recall_score"]
        assert item["recall_score"] == baseline_by_id[item["candidate_id"]]["score"]
        assert item["recall_rationale"] == baseline_by_id[item["candidate_id"]]["rationale"]
        assert set(item["evidence_refs"]).issubset(set(baseline_by_id))
    assert "SECRET_MUST_NOT_APPEAR" not in response.text and "NEVER_CONNECT" not in response.text
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(CatalogColumn)) == 2
        log = db.scalar(select(ModelCallLog).where(ModelCallLog.skill_key == "field_semantic_matching").order_by(ModelCallLog.id.desc()))
        assert log.status == "success" and log.execution_kind == "mock_model"
        assert log.execution_metadata_json["candidate_references"]["ranking"] == [
            item["candidate_id"] for item in body["candidates"]]
    assert log_count(factory) == before + 1


def test_rerank_envelope_carries_only_catalog_metadata_under_the_confidentiality_floor(control_env):
    query, _ = seeded(control_env)
    client, factory, _, _, _ = control_env
    baseline = recall(client, query)
    with factory() as db:
        project = db.get(Project, query["project_id"])
        scope = SkillScope(scope_type="project", institution_id=project.institution_id, project_id=project.id)
        envelope, blocked = field_rerank.build_rerank_envelope(project, scope, query["target_field_id"], baseline)
    assert blocked is None
    text = envelope.model_dump_json()
    assert "SECRET_MUST_NOT_APPEAR" not in text and "NEVER_CONNECT" not in text
    for forbidden in ("host", "port", "username", "encrypted_password", "password"):
        assert forbidden not in text
    assert {item.confidentiality for item in envelope.facts} == {field_rerank.confidentiality_floor(project)}
    assert field_rerank.confidentiality_floor(project) in {"confidential", "restricted"}
    with pytest.raises(ValueError):
        ensure_external_allowed(field_rerank.confidentiality_floor(project), False)
    cloud = PromptRuntime(prompt_key="ai_skill:field_semantic_matching", version=1, system_prompt="s",
                          user_template="{facts}", model_profile_id=1, provider_type="openai_compatible",
                          base_url="http://127.0.0.1:1", model_name="m", api_key_env_name=None,
                          local_only=False, config={})
    with pytest.raises(ValueError):
        prepare_model_input(cloud, text, ["confidential"])


def test_cloud_profile_is_denied_before_any_content_leaves(control_env, monkeypatch):
    query, _ = seeded(control_env)
    client, factory, _, _, _ = control_env
    gate_calls = []
    bind_rerank_skill(control_env, monkeypatch=monkeypatch, calls=gate_calls, cloud=True)
    assert gate_calls  # the release gate itself used the stub transport
    baseline = recall(client, query)
    before = log_count(factory)
    response = submit_rerank(client, query, baseline)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error_code"] == "external_model_data_denied"
    assert log_count(factory) == before
    # The refusal is data-egress control, so it must leave an audit trail (denied, with reason).
    from sqlalchemy import select as sa_select

    from app.models import AuditLog
    with factory() as db:
        denied = db.scalars(sa_select(AuditLog).where(AuditLog.action == "external_model_data_denied")).all()
        assert len(denied) == 1
        assert denied[0].result == "denied"
        assert denied[0].after_summary_json["reason"] == "data_classification_policy"
    # The gate's stub is the same transport the endpoint would use: it must not be reached.
    assert len(gate_calls) == 1


@pytest.mark.parametrize("mutation", ["unknown", "duplicate", "missing", "out_of_range", "fabricated_evidence"])
def test_invalid_model_output_falls_back_with_an_explicit_deterministic_label(control_env, monkeypatch, mutation):
    query, _ = seeded(control_env)
    client, factory, _, _, _ = control_env
    bind_rerank_skill(control_env)
    baseline = recall(client, query)
    before = log_count(factory)
    monkeypatch.setattr("app.services.llm.factory.MockLLMService", broken_mock(mutation))
    response = submit_rerank(client, query, baseline)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ranking_mode"] == "deterministic_recall"
    assert body["execution_metadata"]["execution_kind"] == "deterministic"
    assert body["rerank"]["status"] == "failed" and body["rerank"]["error_code"]
    assert body["rerank"]["model_metadata"]["execution_kind"] == "degraded"
    assert [item["candidate_id"] for item in body["candidates"]] == [item["candidate_id"] for item in baseline["candidates"]]
    assert [item["score"] for item in body["candidates"]] == [item["score"] for item in baseline["candidates"]]
    assert {item["rank_source"] for item in body["candidates"]} == {"recall"}
    assert log_count(factory) == before + 1
    with factory() as db:
        log = db.scalar(select(ModelCallLog).where(ModelCallLog.skill_key == "field_semantic_matching").order_by(ModelCallLog.id.desc()))
        assert log.status == "failed"


def test_provider_failure_never_becomes_a_model_success(control_env, monkeypatch):
    query, _ = seeded(control_env)
    client, factory, _, _, _ = control_env
    bind_rerank_skill(control_env)
    baseline = recall(client, query)

    class FailingMock(MockLLMService):
        async def chat_json(self, system_prompt, user_prompt):
            if system_prompt.startswith("[AI_SKILL_FIELD_RERANK_V1]"):
                raise LLMProviderError("provider timeout", error_type="timeout")
            return await super().chat_json(system_prompt, user_prompt)

    monkeypatch.setattr("app.services.llm.factory.MockLLMService", FailingMock)
    response = submit_rerank(client, query, baseline)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ranking_mode"] == "deterministic_recall"
    assert body["execution_metadata"]["execution_kind"] == "deterministic"
    assert body["rerank"]["error_code"] == "timeout"
    assert body["rerank"]["model_metadata"]["degraded_reason"] == "timeout"
    assert [item["candidate_id"] for item in body["candidates"]] == [item["candidate_id"] for item in baseline["candidates"]]


def test_snapshot_recheck_after_the_call_discards_the_model_ordering(control_env, monkeypatch):
    query, ids = seeded(control_env)
    client, factory, _, _, _ = control_env
    bind_rerank_skill(control_env)
    baseline = recall(client, query)
    real = field_rerank.recall_fields
    calls = {"count": 0}

    def racing_recall(db, principal, payload):
        calls["count"] += 1
        if calls["count"] >= 2:
            with factory() as other:
                other.get(CatalogColumn, ids["column"]).column_comment = "调用后口径已变更"
                other.commit()
        return real(db, principal, payload)

    monkeypatch.setattr(field_rerank, "recall_fields", racing_recall)
    response = submit_rerank(client, query, baseline)
    assert response.status_code == 200, response.text
    body = response.json()
    assert calls["count"] == 2
    assert body["ranking_mode"] == "deterministic_recall"
    assert body["rerank"]["error_code"] == "candidate_snapshot_changed_after_call"
    assert body["rerank"]["snapshot_recheck"] == "changed_after_call"
    assert body["context_hash"] != baseline["context_hash"]
    assert {item["rank_source"] for item in body["candidates"]} == {"recall"}
    assert body["execution_metadata"]["execution_kind"] == "deterministic"


def test_missing_binding_blocks_the_call_without_a_legacy_fallback(control_env):
    query, _ = seeded(control_env)
    client, factory, login, scope, _ = control_env
    baseline = recall(client, query)
    before = log_count(factory)
    response = submit_rerank(client, query, baseline)
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "skill_binding_required"
    assert log_count(factory) == before
    login("manager")
    assert client.get("/ai-skills/resolve", params=dict(scope, skill_key="field_semantic_matching")).json()["runtime_mode"] == "legacy"


@pytest.mark.parametrize("change", ["archived_version", "model_drift"])
def test_unusable_or_drifted_binding_blocks_before_the_model_call(control_env, change):
    query, _ = seeded(control_env)
    client, factory, _, scope, content = control_env
    bind_rerank_skill(control_env)
    baseline = recall(client, query)
    before = log_count(factory)
    with factory() as db:
        if change == "archived_version":
            for version in db.scalars(select(AISkillVersion)):
                version.status = "archived"
        else:
            db.get(ModelProfile, content["model_profile_id"]).model_name = "changed-model"
        db.commit()
    response = submit_rerank(client, query, baseline)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error_code"] == {
        "archived_version": "skill_unavailable", "model_drift": "skill_dependency_changed"}[change]
    assert log_count(factory) == before


@pytest.mark.parametrize("change", ["metadata", "disabled_datasource", "disabled_schema", "broken_scope",
                                    "target_field", "permission"])
def test_changed_snapshot_or_permission_blocks_before_any_model_call(control_env, change):
    query, ids = seeded(control_env)
    client, factory, _, scope, _ = control_env
    bind_rerank_skill(control_env)
    baseline = recall(client, query)
    before = log_count(factory)
    with factory() as db:
        if change == "metadata":
            db.get(CatalogColumn, ids["column"]).column_comment = "新口径"
        elif change == "disabled_datasource":
            db.get(DataSource, ids["datasource"]).enabled = False
        elif change == "disabled_schema":
            from app.models import CatalogSchema
            db.get(CatalogSchema, ids["schema"]).enabled = False
        elif change == "broken_scope":
            from app.models import CatalogTable
            db.get(CatalogTable, ids["table"]).project_id += 1
        elif change == "target_field":
            from app.models import TargetField
            db.get(TargetField, query["target_field_id"]).field_code = "renamed_balance"
        else:
            manager = db.scalar(select(User).where(User.username == "manager"))
            db.scalar(select(ProjectMembership).where(ProjectMembership.project_id == scope["project_id"],
                                                      ProjectMembership.user_id == manager.id)).project_role = "viewer"
        db.commit()
    response = submit_rerank(client, query, baseline)
    assert response.status_code == (403 if change == "permission" else 409), response.text
    if change != "permission":
        assert response.json()["detail"]["error_code"] == "candidate_snapshot_changed"
    assert log_count(factory) == before


def test_rerank_is_isolated_to_the_calling_project(control_env):
    query, _ = seeded(control_env)
    client, factory, login, _, _ = control_env
    bind_rerank_skill(control_env)
    baseline = recall(client, query)
    before = log_count(factory)
    login("outsider")
    assert submit_rerank(client, query, baseline).status_code == 404
    login("legacy")
    assert submit_rerank(client, query, baseline).status_code == 401
    login("bank_admin")
    # An institution admin may read the project, but a recall snapshot is actor-bound, so a
    # different actor must never inherit someone else's model rerank.
    foreign_actor = submit_rerank(client, query, baseline)
    assert foreign_actor.status_code == 409, foreign_actor.text
    assert foreign_actor.json()["detail"]["error_code"] == "candidate_snapshot_changed"
    assert log_count(factory) == before  # only the release-gate run logged a model call


def test_context_budget_is_enforced_before_any_model_call(control_env, monkeypatch):
    query, _ = seeded(control_env)
    client, factory, _, _, _ = control_env
    bind_rerank_skill(control_env)
    baseline = recall(client, query)
    before = log_count(factory)
    monkeypatch.setattr(field_rerank, "RERANK_MAX_INPUT_BYTES", 64)
    response = submit_rerank(client, query, baseline)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error_code"] == "context_budget_exceeded"
    assert response.json()["detail"]["budget"]["limit"] == 64
    assert log_count(factory) == before


def test_ranking_contract_rejects_missing_duplicate_unknown_and_fabricated_references():
    with pytest.raises(Exception):
        RankedCandidate(candidate_id="catalog:0", score=0.5, rationale="probe")
    for score in (True, "0.5", float("nan"), float("inf"), -0.1, 1.1):
        with pytest.raises(Exception):
            RankedCandidate(candidate_id="catalog:1", score=score, rationale="probe")
    envelope = envelope_for(SkillScope(scope_type="project", institution_id=1, project_id=1))
    good = {"candidate_id": "catalog:1", "score": 0.5, "rationale": "probe", "evidence_refs": ["catalog:1"]}
    other = {"candidate_id": "catalog:2", "score": 0.4, "rationale": "probe", "evidence_refs": []}
    validate_field_ranking(FieldRankingCandidate(ranking=[good, other]), envelope)
    with pytest.raises(ValueError):
        validate_field_ranking(FieldRankingCandidate(ranking=[good]), envelope)
    with pytest.raises(ValueError):
        validate_field_ranking(FieldRankingCandidate(ranking=[good, good]), envelope)
    with pytest.raises(ValueError):
        validate_field_ranking(FieldRankingCandidate(ranking=[good, {**other, "candidate_id": "catalog:9"}]), envelope)
    with pytest.raises(ValueError):
        validate_field_ranking(FieldRankingCandidate(
            ranking=[{**good, "evidence_refs": ["catalog:9"]}, other]), envelope)
