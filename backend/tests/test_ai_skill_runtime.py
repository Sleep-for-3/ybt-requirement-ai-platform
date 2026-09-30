import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import AISkillDefinition, AISkillVersion, AISkillScopeBinding, ModelCallLog, ModelProfile, User
from app.schemas.ai_skill import SkillInputEnvelope, SkillScope
from app.services.ai_skills import runtime
from app.services.ai_skills.control import scope_key
from app.services.auth.dependencies import Principal
from app.services.llm.base import ModelCallMetadata
from test_ai_skill_control import control_env, draft, ROOT


def bind(env):
    item = draft(env)
    _, factory, _, scope, _ = env
    with factory() as db:
        version = db.get(AISkillVersion, item["id"])
        from app.services.ai_skills.evaluation import dependencies
        version.release_dependency_hash = dependencies(db, version)
        version.status = "published"
        version.published_at = datetime.now(timezone.utc)
        db.add(AISkillScopeBinding(definition_id=version.definition_id, version_id=version.id,
                                  **scope, scope_key=scope_key(SkillScope.model_validate(scope)), updated_by=version.created_by))
        db.commit()
    return item


def principal(db):
    user = db.scalar(select(User).where(User.username == "manager"))
    return Principal(user.id, user.username, None)


def envelope(scope, *, value="余额表达式", confidentiality="internal"):
    return SkillInputEnvelope.model_validate({"skill_key": "lineage_edge_explanation", "task_key": "lineage_edge_explanation",
        "scope": scope, "subject_ref": "edge:1", "facts": [{"id": "fact:1", "kind": "expression", "value": value,
        "confidentiality": confidentiality, "source": {"source_type": "script_version", "source_id": "1", "source_version": "1",
        "locator": "stmt:1", "scope": scope}}]})


def test_pinned_resolution_no_automatic_parent_or_latest_update(control_env):
    client, factory, _, scope, _ = control_env
    item = bind(control_env)
    draft(control_env)
    result = client.get("/ai-skills/resolve", params=dict(scope, skill_key="lineage_edge_explanation"))
    assert result.status_code == 200, result.text
    assert result.json()["skill_version_id"] == item["id"]
    assert "content" not in result.json()
    with factory() as db:
        task = SkillScope.model_validate(dict(scope, scope_type="task", invocation_key="graph"))
        assert runtime.resolve_skill(db, principal(db), "lineage_edge_explanation", task)[1].id == item["id"]
        version = db.get(AISkillVersion, item["id"])
        version.status = "archived"
        db.commit()
        with pytest.raises(HTTPException) as error:
            runtime.resolve_skill(db, principal(db), "lineage_edge_explanation", task)
        assert error.value.detail["error_code"] == "skill_unavailable"


def test_missing_binding_returns_explicit_legacy(control_env):
    _, factory, _, scope, _ = control_env
    draft(control_env)
    with factory() as db:
        assert asyncio.run(runtime.execute_skill(db, principal(db), envelope(scope))) is None
        assert db.scalars(select(ModelCallLog)).all() == []


def test_real_mock_provider_logs_actual_skill_identity(control_env):
    _, factory, _, scope, _ = control_env
    item = bind(control_env)
    with factory() as db:
        result = asyncio.run(runtime.execute_skill(db, principal(db), envelope(scope)))
        assert result["execution_metadata"]["execution_kind"] == "mock_model"
        assert result["execution_metadata"]["skill_version_id"] == item["id"]
        assert result["facts"][0]["id"] == "fact:1"
        db.commit()
        log = db.scalar(select(ModelCallLog))
        assert log.skill_key == "lineage_edge_explanation"
        assert log.context_hash == envelope(scope).context_hash()
        assert log.execution_metadata_json["runtime_mode"] == "skill"


@pytest.mark.parametrize("failure", ["budget", "external", "task"])
def test_invalid_inputs_never_start_a_model(control_env, monkeypatch, failure):
    _, factory, _, scope, content = control_env
    bind(control_env)
    def forbidden(*args, **kwargs):
        pytest.fail("Model service must not be constructed")
    monkeypatch.setattr(runtime, "get_runtime_llm_service", forbidden)
    with factory() as db:
        sample = envelope(scope, value="很长" * 4000 if failure == "budget" else "表达式",
                          confidentiality="restricted" if failure == "external" else "internal")
        if failure == "external":
            db.get(ModelProfile, content["model_profile_id"]).local_only = False
            db.flush()
        if failure == "task":
            sample.task_key = "regulatory_qa"
        with pytest.raises(HTTPException):
            asyncio.run(runtime.execute_skill(db, principal(db), sample))


@pytest.mark.parametrize("mode", ["good", "unknown_reference", "provider_failure"])
def test_claim_validation_and_failure_preserve_deterministic_facts(control_env, monkeypatch, mode):
    _, factory, _, scope, _ = control_env
    bind(control_env)
    class Provider:
        last_call = ModelCallMetadata(provider="mock", model="fixture-model")
        async def chat_structured(self, system, user, schema):
            if mode == "provider_failure":
                raise RuntimeError("unavailable")
            return schema.model_validate({"claims": [{"claim_type": "observed_fact", "text": "根据已提供的事实",
                "fact_ids": ["fact:1" if mode == "good" else "unknown"]}]})
    monkeypatch.setattr(runtime, "get_runtime_llm_service", lambda *args, **kwargs: Provider())
    with factory() as db:
        result = asyncio.run(runtime.execute_skill(db, principal(db), envelope(scope)))
        assert result["facts"][0]["id"] == "fact:1"
        assert bool(result["claims"]) == (mode == "good")
        assert result["execution_metadata"]["execution_kind"] == ("mock_model" if mode == "good" else "degraded")
        db.commit()
        log = db.scalar(select(ModelCallLog))
        assert log.status == ("success" if mode == "good" else "failed")
        if mode == "unknown_reference":
            assert log.rejected_claims_json[0]["reason"] == "unknown fact reference"


def test_compile_hash_distinguishes_original_projection_from_rendered_request(control_env):
    _, factory, _, scope, _ = control_env
    item = bind(control_env)
    with factory() as db:
        version = db.get(AISkillVersion, item["id"])
        definition = db.get(AISkillDefinition, version.definition_id)
        sample = envelope(scope)
        compiled = runtime.compile_input(db, definition, version, sample)
        assert compiled.context_hash == sample.context_hash()
        assert compiled.budget["used"] == len(compiled.runtime.system_prompt.encode()) + len(compiled.input_text.encode())
        assert "fact:1" in compiled.input_text


@pytest.mark.parametrize("policy_reference", ["policy:1", "unknown", "fact:1"])
def test_policy_comparison_candidates_require_both_authorized_reference_sets(control_env, monkeypatch, policy_reference):
    _, factory, _, scope, _ = control_env
    bind(control_env)
    sample = SkillInputEnvelope.model_validate({**envelope(scope).model_dump(mode="json"), "policy_evidence": [
        {"id": "policy:1", "kind": "policy_clause", "value": "第十二条：按期末余额报送", "confidentiality": "internal",
         "source": {"source_type": "knowledge_clause", "source_id": "1", "source_version": "1", "locator": "第十二条", "scope": scope}}]})
    class Provider:
        last_call = ModelCallMetadata(provider="mock", model="fixture-comparison")
        async def chat_structured(self, system, user, schema):
            return schema.model_validate({"policy_comparisons": [{"status": "conflict", "fact_ids": ["fact:1"],
                "policy_clause_ids": [policy_reference], "rationale": "对照固定表达式与条款", "difference": "表达式与要求的计算口径不同"}]})
    monkeypatch.setattr(runtime, "get_runtime_llm_service", lambda *args, **kwargs: Provider())
    with factory() as db:
        result = asyncio.run(runtime.execute_skill(db, principal(db), sample))
        assert bool(result["policy_comparisons"]) == (policy_reference == "policy:1")
        assert result["facts"] and result["policy_evidence"]
        if policy_reference == "policy:1":
            candidate = result["policy_comparisons"][0]
            assert candidate["requires_human_confirmation"] is True
            assert "confirmed_by" not in candidate
            assert result["execution_metadata"]["citations"][0]["policy_clause_ids"] == ["policy:1"]
        else:
            assert result["execution_metadata"]["execution_kind"] == "degraded"


def test_policy_comparison_cannot_claim_human_adoption_or_unexplained_conflict():
    from pydantic import ValidationError
    from app.schemas.ai_skill import SkillPolicyComparison
    valid = {"status": "conflict", "fact_ids": ["fact:1"], "policy_clause_ids": ["policy:1"],
             "rationale": "逐条核对", "difference": "计算差异"}
    for invalid in ({"requires_human_confirmation": False}, {"confirmed_by": 1}, {"difference": ""}, {"policy_clause_ids": []}):
        with pytest.raises(ValidationError):
            SkillPolicyComparison.model_validate({**valid, **invalid})
