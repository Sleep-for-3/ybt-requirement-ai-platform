import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import (AISkillDefinition, AISkillVersion, AISkillScopeBinding, Institution,
    ModelProfile, ModelCallLog, RequirementGenerationItem)
from app.schemas.ai_skill import SkillScope
from app.schemas.ai_skill_control import SkillContent
from app.services.ai_skills import runtime
from app.services.ai_skills.control import scope_key
from app.services.ai_skills.evaluation import dependencies
from app.services.ai_skills.requirement_context import build_requirement_envelope, validate_requirement_output
from app.services.llm.execution_metadata import stable_hash
from app.services.requirement_candidate_contract import RequirementCandidate
from test_ai_skill_control import control_env
from test_requirement_snapshot_api import snapshot_api, snapshot_db


KEY = "requirement_candidate_generation"


def sample(scope):
    project = SimpleNamespace(id=scope["project_id"], institution_id=scope["institution_id"], confidentiality_level="internal")
    context = {"project_id": project.id, "field_ids": [1], "sections": ["business"],
        "fields": [{"target": {"id": 1}, "authored": {"business": {"final_content": "人工正文"}}}],
        "physical_sources": [{"kind": "source", "table_id": 2, "field_id": 3}],
        "script_basis": {"rules": [{"rule_id": "fixed-rule"}]},
        "evidence": [{"unit_id": 4, "document_version_id": 5, "content_hash": "fixed-hash", "content": "有效制度条款",
            "source_category": "regulatory_formal", "confidentiality_level": "internal", "locator": {"paragraph_index": 1}}]}
    row = SimpleNamespace(id=7, project_id=project.id, input_json=context, input_hash=stable_hash(context))
    item = SimpleNamespace(input_id=7, field_id=1, section="business")
    return build_requirement_envelope(project, row, item)


def test_requirement_projection_separates_policy_and_rejects_wrong_references():
    envelope = sample({"project_id": 1, "institution_id": 2})
    assert "evidence" not in envelope.facts[0].value
    assert len(envelope.policy_evidence) == 1
    good = RequirementCandidate(final_content="候选", evidence_unit_ids=[4], script_rule_ids=["fixed-rule"])
    validate_requirement_output(good, envelope)
    for updates in ({"evidence_unit_ids": [999]}, {"script_rule_ids": ["invented"]},
                    {"physical_references": [{"kind": "source", "table_id": 2, "field_id": 999}]}):
        with pytest.raises(ValueError):
            validate_requirement_output(RequirementCandidate.model_validate({**good.model_dump(), **updates}), envelope)
    forged = envelope.model_copy(deep=True)
    forged.policy_evidence[0].value["source_category"] = "technical_document"
    with pytest.raises(ValueError, match="classification mismatch"):
        validate_requirement_output(good, forged)


def test_native_requirement_publish_gate_and_runtime_use_the_same_schema(control_env):
    client, factory, login, scope, content = control_env
    root = f"/ai-skills/{KEY}"
    assert client.post("/ai-skills", json={"skill_key": KEY, "task_key": KEY, "display_name": "需求候选"}).status_code == 201
    login("manager")
    response = client.post(root + "/versions", json={"scope": scope,
        "content": {**content, "output_schema_key": "requirement_candidate_v1"}})
    assert response.status_code == 201, response.text
    item = response.json()
    envelope = sample(scope)
    assert client.post(root + "/test-cases", json={"name": "固定需求", "input": envelope.model_dump(mode="json"),
        "replay_output": {"candidate": {"final_content": "回放候选", "evidence_unit_ids": [4]}}}).status_code == 201
    lock = item["lock_version"]
    for mode in ("deterministic", "mock_model", "replay"):
        response = client.post(root + "/test-runs", json={"version": 1, "project_id": scope["project_id"],
            "mode": mode, "expected_lock_version": lock})
        assert response.status_code == 201, response.text
        assert response.json()["status"] == "passed", response.text
        lock += 1
    response = client.post(root + "/versions/1/submit", json={"expected_lock_version": lock, "test_project_id": scope["project_id"]})
    assert response.status_code == 200, response.text
    login("bank_admin")
    response = client.post(root + "/versions/1/publish", json={"expected_lock_version": lock + 1, "test_project_id": scope["project_id"]})
    assert response.status_code == 200, response.text
    with factory() as db:
        from test_ai_skill_runtime import principal
        from app.models import PromptTemplateVersion
        snapshot = db.scalar(select(PromptTemplateVersion).where(PromptTemplateVersion.skill_version_id == item["id"]))
        assert snapshot.output_schema_json == runtime.output_schema(KEY).model_json_schema()
        result = asyncio.run(runtime.execute_skill(db, principal(db), envelope))
        assert result["candidate"]["final_content"]
        assert result["execution_metadata"]["runtime_mode"] == "skill"
        assert result["execution_metadata"]["execution_kind"] == "mock_model"
        assert result["execution_metadata"]["skill_version_id"] == item["id"]
        log = db.get(ModelCallLog, result["execution_metadata"]["run_id"])
        assert log.skill_version_id == item["id"]


@pytest.mark.parametrize("mode", ["valid", "invalid_output", "no_binding", "profile_drift"])
def test_bound_requirement_worker_stores_only_valid_candidate_without_adoption(snapshot_api, monkeypatch, mode):
    from app.services.task_queue.inline import InlineTaskQueue
    client, db, project, field, requirement, membership = snapshot_api
    institution = Institution(institution_code="skill-bank", institution_name="隔离银行", institution_type="bank")
    profile = ModelProfile(profile_name="candidate-mock", provider_type="mock", local_only=True,
        enabled=True, max_context_tokens=64000)
    definition = AISkillDefinition(skill_key=KEY, task_key=KEY, display_name="需求候选", created_by=membership.user_id)
    db.add_all([institution, profile, definition])
    db.flush()
    project.institution_id = institution.id
    scope = SkillScope(scope_type="project", institution_id=institution.id, project_id=project.id)
    content = SkillContent(system_prompt="仅生成待人工采用的需求候选", model_profile_id=profile.id,
        output_schema_key="requirement_candidate_v1").model_dump(mode="json")
    version = AISkillVersion(definition_id=definition.id, version_no=1, **scope.model_dump(), scope_key=scope_key(scope),
        content_json=content, content_hash=stable_hash(content), created_by=membership.user_id, edited_by=membership.user_id)
    db.add(version)
    db.flush()
    version.release_dependency_hash = dependencies(db, version)
    version.status = "published"
    version.published_at = datetime.now(timezone.utc)
    if mode != "no_binding":
        db.add(AISkillScopeBinding(definition_id=definition.id, version_id=version.id,
            **scope.model_dump(), scope_key=scope_key(scope), updated_by=membership.user_id))
    db.commit()
    if mode != "no_binding":
        monkeypatch.setattr("app.services.requirement_generation_worker.get_prompt_runtime",
            lambda *args: pytest.fail("An existing Skill binding must not silently fall back to Legacy"))
    if mode == "profile_drift":
        profile.model_name = "changed-provider-model"
        db.commit()
    if mode == "invalid_output":
        class InvalidService:
            last_call = None
            async def chat_structured(self, system, prompt, schema):
                return schema(candidate={"final_content": "非法引用候选", "evidence_unit_ids": [999999]})
        monkeypatch.setattr(runtime, "get_runtime_llm_service", lambda *args, **kwargs: InvalidService())
    base = f"/projects/{project.id}/requirements/{requirement.id}"
    assert client.post(base + "/revisions", json={"expected_version": 1}).status_code in {200, 201}
    before = deepcopy(client.get(base + "/document").json())
    monkeypatch.setattr("app.services.task_queue.factory.get_task_queue", lambda: InlineTaskQueue())
    response = client.post(base + "/generation-runs", json={"expected_content_version": 1,
        "field_ids": [field.id], "sections": ["business"], "idempotency_key": "bound-skill"})
    assert response.status_code == 201, response.text
    item = db.scalar(select(RequirementGenerationItem))
    blocked = mode in {"invalid_output", "profile_drift"}
    assert item.status == ("blocked" if blocked else "completed")
    assert item.decision == "pending"
    if blocked:
        assert item.candidate_json is None
    elif mode == "no_binding":
        assert item.candidate_json["execution_metadata"].get("runtime_mode", "legacy") == "legacy"
    else:
        assert item.candidate_json["execution_metadata"]["skill_version_id"] == version.id
        assert item.candidate_json["runtime"]["test_provider"] is True
    if not blocked:
        detail = client.get(base + f"/generation-items/{item.id}")
        assert detail.status_code == 200, detail.text
        metadata = detail.json()["execution_metadata"]
        assert metadata["runtime_mode"] == ("legacy" if mode == "no_binding" else "skill")
        assert metadata["execution_kind"] == "mock_model"
        assert "regression_input" not in detail.json()
        assert "system_prompt" not in metadata
        if mode == "valid":
            assert metadata["skill_version_id"] == version.id
            assert metadata["run_id"] > 0 and len(metadata["context_hash"]) == 64
    assert client.get(base + "/document").json() == before
