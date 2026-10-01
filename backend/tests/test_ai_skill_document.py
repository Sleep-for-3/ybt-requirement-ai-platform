from copy import deepcopy

import pytest
from sqlalchemy import select

from app.api.requirements import router
from app.models import Requirement, RequirementRevision, ModelCallLog
from app.services.ai_skills import runtime
from app.services.ai_skills.document_context import TASK, build_document_envelope
from app.services.requirement_scope import content_digest
from test_ai_skill_control import control_env
from test_ai_skill_runtime import principal
from test_requirement_snapshot_api import snapshot_api, snapshot_db


def prepare(env, publish=True):
    client, factory, login, scope, config = env
    client.app.include_router(router)
    assert client.post("/ai-skills", json={"skill_key": TASK, "task_key": TASK, "display_name": "固定文档辅助"}).status_code == 201
    with factory() as db:
        req = Requirement(project_id=scope["project_id"], name="固定文档", content_version=1)
        db.add(req); db.flush()
        content = {"requirement": {"id": req.id, "content_version": 1, "background": "人工固定背景"},
                   "fields": [], "gaps": [{"message": "待补制度"}]}
        revision = RequirementRevision(project_id=req.project_id, requirement_id=req.id, content_version=1,
            scope_version=1, content_json=content, content_hash=content_digest(content), status="confirmed")
        db.add(revision); db.commit()
        req_id, revision_id = req.id, revision.id
        _, envelope = build_document_envelope(db, principal(db), req.project_id, req.id, 1)
    login("manager")
    root = f"/ai-skills/{TASK}"
    response = client.post(root + "/versions", json={"scope": scope, "content": {**config, "output_schema_key": "document_assistance_v1"}})
    assert response.status_code == 201, response.text
    assert client.post(root + "/test-cases", json={"name": "固定文档", "input": envelope.model_dump(mode="json"),
        "replay_output": {"candidate": {"background": [{"text": "人工背景摘要", "fact_ids": [envelope.facts[0].id]}]}}}).status_code == 201
    if publish:
        for lock, mode in enumerate(("deterministic", "mock_model", "replay"), 1):
            run = client.post(root + "/test-runs", json={"version": 1, "project_id": scope["project_id"], "mode": mode, "expected_lock_version": lock})
            assert run.status_code == 201 and run.json()["status"] == "passed", run.text
        assert client.post(root + "/versions/1/submit", json={"expected_lock_version": 4, "test_project_id": scope["project_id"]}).status_code == 200
        login("bank_admin")
        released = client.post(root + "/versions/1/publish", json={"expected_lock_version": 5, "test_project_id": scope["project_id"]})
        assert released.status_code == 200, released.text
        login("manager")
    path = f"/projects/{scope['project_id']}/requirements/{req_id}/revisions/1/document-assistance"
    return path, req_id, revision_id, content, envelope


@pytest.mark.parametrize("bad_reference", [False, True])
def test_fixed_document_candidate_never_mutates_confirmed_or_latest_content(control_env, monkeypatch, bad_reference):
    path, req_id, revision_id, original, envelope = prepare(control_env)
    client, factory, _, _, _ = control_env
    class Synthetic:
        last_call = None
        async def chat_structured(self, system, prompt, schema):
            assert "人工固定背景" in prompt and "后续背景" not in prompt
            return schema(candidate={"background": [{"text": "合成辅助摘要", "fact_ids": ["foreign:secret" if bad_reference else envelope.facts[0].id]}]})
    monkeypatch.setattr(runtime, "get_runtime_llm_service", lambda *args, **kwargs: Synthetic())
    with factory() as db:
        req = db.get(Requirement, req_id)
        req.content_version = 2
        db.add(RequirementRevision(project_id=req.project_id, requirement_id=req.id, content_version=2, scope_version=1,
            content_json={"requirement": {"background": "后续背景"}}, content_hash=content_digest({"requirement": {"background": "后续背景"}})))
        db.commit()
    response = client.post(path)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["content_version"] == 1 and result["status"] == "candidate_only"
    assert (result["candidate"] is None) == bad_reference
    assert result["execution_metadata"]["execution_kind"] == ("degraded" if bad_reference else "mock_model")
    with factory() as db:
        assert db.get(RequirementRevision, revision_id).content_json == original
        assert db.get(RequirementRevision, revision_id).status == "confirmed"
        assert db.get(Requirement, req_id).content_version == 2
        log = db.get(ModelCallLog, result["execution_metadata"]["run_id"])
        assert log.status == ("failed" if bad_reference else "success")
        assert log.citations_json == ([] if bad_reference else [{"fact_ids": [envelope.facts[0].id], "policy_clause_ids": [], "section": "background"}])


def test_document_requires_explicit_binding_and_real_scoped_identity(control_env):
    path, _, _, _, _ = prepare(control_env, publish=False)
    client, _, login, _, _ = control_env
    assert client.post(path).status_code == 409
    login("outsider")
    assert client.post(path).status_code == 404
    login("legacy")
    assert client.post(path).status_code == 401


def test_document_rechecks_actor_after_model_returns(control_env, monkeypatch):
    path, _, _, _, _ = prepare(control_env)
    client, factory, _, scope, _ = control_env
    class Revoking:
        last_call = None
        async def chat_structured(self, system, prompt, schema):
            from app.models import ProjectMembership
            with factory() as db:
                row = db.scalar(select(ProjectMembership).where(ProjectMembership.project_id == scope["project_id"]))
                row.status = "inactive"; db.commit()
            return schema(candidate={})
    monkeypatch.setattr(runtime, "get_runtime_llm_service", lambda *args, **kwargs: Revoking())
    assert client.post(path).status_code == 404


def test_document_refuses_tampered_fixed_revision(control_env, monkeypatch):
    path, _, revision_id, _, _ = prepare(control_env)
    client, factory, _, _, _ = control_env
    with factory() as db:
        row = db.get(RequirementRevision, revision_id)
        row.content_json = {**deepcopy(row.content_json), "fields": ["tampered"]}
        db.commit()
    monkeypatch.setattr(runtime, "get_runtime_llm_service", lambda *args, **kwargs: pytest.fail("No model for tampered revision"))
    assert client.post(path).status_code == 409


def test_document_does_not_send_full_revision_to_external_profile(control_env, monkeypatch):
    from app.models import ModelProfile
    client, factory, _, _, config = control_env
    with factory() as db:
        db.get(ModelProfile, config["model_profile_id"]).local_only = False
        db.commit()
    path, _, _, _, _ = prepare(control_env)
    monkeypatch.setattr(runtime, "get_runtime_llm_service", lambda *args, **kwargs: pytest.fail("No external model for full revision"))
    response = client.post(path)
    assert response.status_code == 409 and "本地模型" in response.text


def test_document_refuses_expired_frozen_evidence_before_model(snapshot_api, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from test_requirement_policy_comparison import setup_comparison
    client, db, _, _, _, _ = snapshot_api
    base, _, version, _, _ = setup_comparison(snapshot_api)
    version.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    monkeypatch.setattr(runtime, "get_runtime_llm_service", lambda *args, **kwargs: pytest.fail("No model for expired evidence"))
    response = client.post(base + "/revisions/2/document-assistance")
    assert response.status_code == 409 and "固定制度依据已失效" in response.text
