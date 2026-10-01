import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from fastapi import HTTPException
from sqlalchemy import select

from app.models import AISkillDefinition, AISkillVersion, AISkillScopeBinding, Institution, ModelProfile, ModelCallLog
from app.schemas.ai_skill import SkillInputEnvelope, SkillScope
from app.schemas.ai_skill_control import SkillContent
from app.services.ai_skills import runtime
from app.services.ai_skills.control import scope_key
from app.services.ai_skills.evaluation import dependencies, mandatory_assertions
from app.services.ai_skills.mapping_context import MAPPING_TASKS, validate_mapping_output, build_mapping_envelope
from app.services.llm.execution_metadata import stable_hash
from app.services.mapping import source_to_mart_generator, mart_to_ybt_generator, scenario_draft_generator
from app.services.mapping.generator_context import GenerationBlockedError, GenerationStaleError
from app.services.governance.double_layer_review import MappingGenerationNotEditable
from test_ai_skill_control import control_env
from test_double_layer_mapping import _source_service_session, _seed_mart_to_ybt_mapping, _principal
from test_scenario_traceability import _scenario_service_session


def sample(task_key, scope):
    short = MAPPING_TASKS[task_key][0]
    value = {"snapshot": {"task_type": short, "project": {"id": scope["project_id"], "institution_id": scope["institution_id"]},
        "task": {"id": 1, "project_id": scope["project_id"], "source_database_name": "old_db",
            "source_schema_name": "old_schema", "source_table_english_name": "old_table", "source_field_english_name": "old_field"}},
        "projection": {"task_type": short, "readiness": {"can_generate": True}, "truncated": False,
            "context_budget": {"complete": True}, "selected_fact_refs": ["source_metadata:1:field"],
            "physical_whitelist": [["db", "schema", "table", "field"]]}}
    return SkillInputEnvelope.model_validate({"skill_key": task_key, "task_key": task_key, "scope": scope,
        "subject_ref": f"{task_key}:1", "facts": [
            {"id": "mapping-context:1", "kind": "mapping_context", "value": value, "confidentiality": "internal",
             "source": {"source_type": "mapping_snapshot", "source_id": "1", "source_version": "fixed", "locator": "1", "scope": scope}},
            {"id": "source_metadata:1:field", "kind": "context_reference", "value": "固定字段元数据", "confidentiality": "internal",
             "source": {"source_type": "regulatory_context", "source_id": "1", "source_version": "fixed", "locator": "field", "scope": scope}}]})


@pytest.mark.parametrize("task_key", MAPPING_TASKS)
def test_native_mapping_contract_rejects_unknown_citations_and_human_decisions(task_key):
    envelope = sample(task_key, {"scope_type": "project", "project_id": 1, "institution_id": 2})
    schema = MAPPING_TASKS[task_key][1]
    validate_mapping_output(schema(final_content_draft="候选", citations=[{"fact_ref": "source_metadata:1:field"}]), envelope)
    with pytest.raises(ValueError, match="outside"):
        validate_mapping_output(schema(final_content_draft="候选", citations=[{"fact_ref": "foreign:99:secret"}]), envelope)
    with pytest.raises(ValidationError):
        schema(final_content_draft="候选", confirmed_by=1)
    assert mandatory_assertions(envelope)["native_unknown_reference_rejected"] is True


def test_technical_physical_sources_require_exact_whitelist_or_unchanged_current_tuple():
    key = "scenario_technical_lineage"
    envelope = sample(key, {"scope_type": "project", "project_id": 1, "institution_id": 2})
    schema = MAPPING_TASKS[key][1]
    names = ("source_database_name", "source_schema_name", "source_table_english_name", "source_field_english_name")
    for source in (("db", "schema", "table", "field"), ("old_db", "old_schema", "old_table", "old_field")):
        validate_mapping_output(schema(processing_logic="待确认", **dict(zip(names, source))), envelope)
    for source in (("db", "schema", "table", "invented"), ("db", "schema", "table", None)):
        with pytest.raises(ValueError, match="unproved"):
            validate_mapping_output(schema(processing_logic="待确认", **dict(zip(names, source))), envelope)


def test_colliding_legacy_references_preserve_every_source_and_highest_classification():
    key = "scenario_business_mapping"
    original = sample(key, {"scope_type": "project", "project_id": 1, "institution_id": 2})
    value = original.facts[0].value
    ref = "human_draft:1:field"
    value["projection"]["selected_fact_refs"] = [ref, ref]
    scope = SimpleNamespace(project_id=1, institution_id=2)
    def fact(model, level):
        material = {"source_model": model, "text": f"{model} 的固定人工内容"}
        return SimpleNamespace(source_type="human_draft", source_id=1, fact_type="field",
            provenance=SimpleNamespace(project_id=1, institution_id=2, confidentiality_level=level),
            model_dump=lambda **kwargs: material)
    context = SimpleNamespace(scope=scope, metadata=[], candidates=[fact("Business", "internal"), fact("Technical", "restricted")],
        mappings=[], semantic=[], regulatory=[], knowledge_evidence=[], historical=[], lineage=[], quality=[])
    snapshot = SimpleNamespace(project=SimpleNamespace(id=1, institution_id=2, confidentiality_level="internal"),
        task=SimpleNamespace(id=1), model_dump=lambda **kwargs: value["snapshot"])
    projection = SimpleNamespace(confidentiality_levels=["internal", "restricted"], selected_fact_refs=[ref, ref],
        context_gaps=[], model_dump=lambda **kwargs: value["projection"])
    result = build_mapping_envelope(SimpleNamespace(snapshot=snapshot, projection=projection, context=context), key)
    members = next(item for item in result.facts if item.id == ref)
    assert members.confidentiality == "restricted"
    assert {item["source_model"] for item in members.value["members"]} == {"Business", "Technical"}
    assert any(gap.code == "ambiguous_context_reference" and gap.source_ref == ref for gap in result.gaps)
    assert not result.policy_evidence


@pytest.mark.parametrize("task_key", MAPPING_TASKS)
def test_mapping_native_schema_passes_real_control_plane_evaluation_and_publish(control_env, task_key):
    client, factory, login, scope, content = control_env
    root = f"/ai-skills/{task_key}"
    assert client.post("/ai-skills", json={"skill_key": task_key, "task_key": task_key, "display_name": task_key}).status_code == 201
    login("manager")
    response = client.post(root + "/versions", json={"scope": scope,
        "content": {**content, "output_schema_key": "mapping_candidate_v1"}})
    assert response.status_code == 201, response.text
    item = response.json()
    assert client.post(root + "/test-cases", json={"name": "固定映射", "input": sample(task_key, scope).model_dump(mode="json"),
        "replay_output": {"candidate": {"final_content_draft": "回放草稿", "citations": [{"fact_ref": "source_metadata:1:field"}]}}}).status_code == 201
    lock = item["lock_version"]
    for mode in ("deterministic", "mock_model", "replay"):
        response = client.post(root + "/test-runs", json={"version": 1, "project_id": scope["project_id"],
            "mode": mode, "expected_lock_version": lock})
        assert response.status_code == 201, response.text
        assert response.json()["status"] == "passed", response.text
        lock += 1
    assert client.post(root + "/versions/1/submit", json={"expected_lock_version": lock, "test_project_id": scope["project_id"]}).status_code == 200
    login("bank_admin")
    response = client.post(root + "/versions/1/publish", json={"expected_lock_version": lock + 1, "test_project_id": scope["project_id"]})
    assert response.status_code == 200, response.text
    with factory() as db:
        from app.models import PromptTemplateVersion
        from app.services.ai_skills.runtime import output_schema
        snapshot = db.scalar(select(PromptTemplateVersion).where(PromptTemplateVersion.skill_version_id == item["id"]))
        assert snapshot.output_schema_json == output_schema(task_key).model_json_schema()


def bind(db, fixture, key):
    project = fixture["project"]
    bank = Institution(institution_code="mapping-bank", institution_name="Mapping 测试银行", institution_type="bank")
    model = ModelProfile(profile_name="mapping-local-mock", provider_type="mock", local_only=True, enabled=True, max_context_tokens=64000)
    definition = AISkillDefinition(skill_key=key, task_key=key, display_name=key, created_by=fixture["user"].id)
    db.add_all([bank, model, definition])
    db.flush()
    project.institution_id = bank.id
    scope = SkillScope(scope_type="project", project_id=project.id, institution_id=bank.id)
    content = SkillContent(system_prompt="只生成待人工确认的候选映射，不得修改正式口径", model_profile_id=model.id,
        output_schema_key="mapping_candidate_v1").model_dump(mode="json")
    version = AISkillVersion(definition_id=definition.id, version_no=1, **scope.model_dump(), scope_key=scope_key(scope),
        content_json=content, content_hash=stable_hash(content), created_by=fixture["user"].id, edited_by=fixture["user"].id)
    db.add(version)
    db.flush()
    version.release_dependency_hash = dependencies(db, version)
    version.status = "published"
    version.published_at = datetime.now(timezone.utc)
    db.add(AISkillScopeBinding(definition_id=definition.id, version_id=version.id, **scope.model_dump(),
        scope_key=scope_key(scope), updated_by=fixture["user"].id))
    db.commit()
    return version.id


def generator_fixture(db, fixture, task_key):
    if task_key == "source_to_mart_mapping":
        return source_to_mart_generator, source_to_mart_generator.generate_source_to_mart_draft, fixture["mapping"]
    if task_key == "mart_to_ybt_mapping":
        return mart_to_ybt_generator, mart_to_ybt_generator.generate_mart_to_ybt_draft, _seed_mart_to_ybt_mapping(db, fixture, "native")
    if task_key == "scenario_business_mapping":
        return scenario_draft_generator, scenario_draft_generator.generate_business_draft, fixture["mapping"]
    return scenario_draft_generator, scenario_draft_generator.generate_technical_draft, fixture["lineage"]


@pytest.mark.parametrize("task_key", MAPPING_TASKS)
def test_real_mapping_context_and_pinned_mock_keep_formal_content(tmp_path, monkeypatch, task_key):
    session = _scenario_service_session if task_key.startswith("scenario_") else _source_service_session
    with session(tmp_path, task_key) as (db, _, fixture):
        module, generate, row = generator_fixture(db, fixture, task_key)
        version_id = bind(db, fixture, task_key)
        monkeypatch.setattr(module, "get_prompt_runtime", lambda *args: pytest.fail("Bound Mapping must not call Legacy"))
        before = row.final_content
        result = asyncio.run(generate(db, row.id, authorized_project=fixture["project"], actor=_principal(fixture), as_of=date(2026, 9, 27)))
        assert result.final_content == before
        assert "Mock" in result.ai_generated_content
        log = db.scalars(select(ModelCallLog).where(ModelCallLog.skill_version_id == version_id)).one()
        assert log.execution_metadata_json["execution_kind"] == "mock_model"
        assert log.execution_metadata_json["runtime_mode"] == "skill"
        assert log.execution_metadata_json["context_complete"] is False
        assert result.confidence_level == "low"
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.mapping_evidence import router
        from app.core.database import get_db
        from app.services.auth.dependencies import get_current_principal, Principal
        from app.models import AuditLog
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_principal] = lambda: _principal(fixture)
        mapping_type = MAPPING_TASKS[task_key][0]
        path = f"/mappings/{mapping_type}/{row.id}/generation-provenance"
        with TestClient(app) as client:
            response = client.get(path)
            assert response.status_code == 200, response.text
            provenance = response.json()
            assert provenance["status"] == "current_text"
            assert provenance["execution_metadata"]["skill_version_id"] == version_id
            assert provenance["execution_metadata"]["run_id"] == log.id
            assert "citations" not in provenance["execution_metadata"]
            # A subsequent edit must not inherit the prior model's provenance.
            row.ai_generated_content = "合成的后续正文修改"
            db.commit()
            assert client.get(path).json()["status"] == "text_changed"
            event = db.get(AuditLog, provenance["audit_id"])
            event.after_summary_json = {key: value for key, value in event.after_summary_json.items() if key != "draft_hash"}
            db.commit()
            assert client.get(path).json()["status"] == "historical_unverified"
            assert client.get(f"/mappings/{mapping_type}/999999/generation-provenance").status_code == 404
            app.dependency_overrides[get_current_principal] = lambda: Principal(None, "legacy", None, True)
            assert client.get(path).status_code == 401


@pytest.mark.parametrize("task_key", MAPPING_TASKS)
@pytest.mark.parametrize("failure", ["bad_citation", "concurrent_edit", "permission_revoked"])
def test_native_mapping_cannot_bypass_output_or_final_write_guards(tmp_path, monkeypatch, task_key, failure):
    session = _scenario_service_session if task_key.startswith("scenario_") else _source_service_session
    with session(tmp_path, task_key) as (db, _, fixture):
        module, generate, row = generator_fixture(db, fixture, task_key)
        bind(db, fixture, task_key)
        monkeypatch.setattr(module, "get_prompt_runtime", lambda *args: pytest.fail("Must not fall back to Legacy"))
        before_final, before_ai = row.final_content, row.ai_generated_content
        class Provider:
            last_call = None
            async def chat_structured(self, system, prompt, schema):
                if failure == "concurrent_edit":
                    row.final_content = "另一位用户刚刚写入的人工正文"
                    db.commit()
                if failure == "permission_revoked":
                    fixture["membership"].project_role = "viewer"
                    db.commit()
                return schema(candidate={"final_content_draft": "不得写入的候选", "citations":
                    [{"fact_ref": "foreign:999:secret"}] if failure == "bad_citation" else []})
        monkeypatch.setattr(runtime, "get_runtime_llm_service", lambda *args, **kwargs: Provider())
        expected = GenerationBlockedError if failure == "bad_citation" else (GenerationStaleError, MappingGenerationNotEditable) if failure == "concurrent_edit" else HTTPException
        with pytest.raises(expected):
            asyncio.run(generate(db, row.id, authorized_project=fixture["project"], actor=_principal(fixture), as_of=date(2026, 9, 27)))
        db.refresh(row)
        assert row.ai_generated_content == before_ai
        assert row.final_content == ("另一位用户刚刚写入的人工正文" if failure == "concurrent_edit" else before_final)
