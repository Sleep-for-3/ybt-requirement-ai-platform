import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models import AISkillDefinition, AISkillTestCase, AISkillTestResult, AISkillVersion, AISkillScopeBinding, AISkillReleaseEvent, AIUserFeedback, ModelCallLog, InstitutionMembership, User, ModelProfile, PromptTemplateVersion
from test_ai_skill_control import control_env, draft, ROOT
from test_ai_skill_runtime import envelope


def prepare(env, *, assertions=None):
    client, _, _, scope, _ = env
    item = draft(env)
    response = client.post(ROOT + "/test-cases", json={"name": "固定血缘样例", "input": envelope(scope).model_dump(mode="json"),
                                                      "assertions": assertions or {}})
    assert response.status_code == 201, response.text
    return item


def test_run(env, item, mode, lock):
    client, _, _, scope, _ = env
    result = client.post(ROOT + "/test-runs", json={"version": item["version_no"], "project_id": scope["project_id"],
                                                     "mode": mode, "expected_lock_version": lock})
    assert result.status_code == 201, result.text
    return result.json()


# This is a helper, not a pytest case.
test_run.__test__ = False


def ready(env):
    client, _, _, scope, _ = env
    item = prepare(env)
    assert test_run(env, item, "deterministic", 1)["status"] == "passed"
    assert test_run(env, item, "mock_model", 2)["status"] == "passed"
    submitted = client.post(ROOT + "/versions/1/submit", json={"expected_lock_version": 3, "test_project_id": scope["project_id"]})
    assert submitted.status_code == 200, submitted.text
    return item


def publish(env, **changes):
    client, _, login, scope, _ = env
    login("bank_admin")
    return client.post(ROOT + "/versions/1/publish", json={"expected_lock_version": 4, "test_project_id": scope["project_id"], **changes})


def test_publish_snapshot_binding_and_restore_closed_loop(control_env):
    client, factory, login, scope, _ = control_env
    item = ready(control_env)
    # Same editor cannot approve, even after acquiring broader roles.
    with factory() as db:
        manager = db.scalar(select(User).where(User.username == "manager"))
        db.add(InstitutionMembership(institution_id=scope["institution_id"], user_id=manager.id,
                                     role="institution_admin", status="active"))
        db.commit()
    same_editor = client.post(ROOT + "/versions/1/publish", json={"expected_lock_version": 4, "test_project_id": scope["project_id"]})
    assert same_editor.status_code == 403
    published = publish(control_env)
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    with factory() as db:
        prompt = db.scalar(select(PromptTemplateVersion).where(PromptTemplateVersion.skill_version_id == item["id"]))
        assert prompt.prompt_key == "ai_skill:lineage_edge_explanation"
        assert db.scalar(select(AISkillScopeBinding)).version_id == item["id"]
        assert db.scalars(select(AISkillReleaseEvent).where(AISkillReleaseEvent.action == "published")).one()
    assert client.post(ROOT + "/versions/1/deprecate", json={"expected_lock_version": 5}).status_code == 200
    # Existing pin stays valid; deprecated versions cannot acquire new pins.
    assert client.get("/ai-skills/resolve", params=dict(scope, skill_key="lineage_edge_explanation")).json()["runtime_mode"] == "skill"
    assert client.post(ROOT + "/bindings", json={"version": 1, "scope": scope, "expected_binding_lock": 1}).status_code == 409
    restored = client.post(ROOT + "/versions/1/restore")
    assert restored.status_code == 201
    assert restored.json()["status"] == "draft"
    assert restored.json()["restored_from_version_id"] == item["id"]


def test_model_fingerprint_change_invalidates_successful_runs(control_env):
    _, factory, _, _, content = control_env
    ready(control_env)
    with factory() as db:
        db.get(ModelProfile, content["model_profile_id"]).model_name = "changed-model"
        db.commit()
    result = publish(control_env)
    assert result.status_code == 409
    assert result.json()["detail"]["error_code"] == "release_gate_failed"
    with factory() as db:
        assert db.scalars(select(PromptTemplateVersion)).all() == []
        assert db.scalars(select(AISkillScopeBinding)).all() == []


def test_new_test_case_invalidates_successful_runs(control_env):
    client, _, _, scope, _ = control_env
    ready(control_env)
    assert client.post(ROOT + "/test-cases", json={"name": "新增反例", "input": envelope(scope).model_dump(mode="json")}).status_code == 201
    assert publish(control_env).status_code == 409


def test_binding_conflict_rolls_back_entire_release(control_env):
    _, factory, _, _, _ = control_env
    item = ready(control_env)
    result = publish(control_env, expected_binding_lock=999)
    assert result.status_code == 409
    with factory() as db:
        version = db.get(AISkillVersion, item["id"])
        assert version.status == "pending_approval"
        assert version.published_at is None
        assert db.scalars(select(PromptTemplateVersion)).all() == []
        assert db.scalars(select(AISkillScopeBinding)).all() == []
        assert db.scalars(select(AISkillReleaseEvent).where(AISkillReleaseEvent.action == "published")).all() == []


def test_failed_case_blocks_submit_and_mock_is_not_real(control_env):
    client, _, _, scope, _ = control_env
    item = prepare(control_env, assertions={"minimum_claims": 1})
    assert test_run(control_env, item, "deterministic", 1)["status"] == "passed"
    result = test_run(control_env, item, "mock_model", 2)
    assert result["status"] == "failed"
    assert result["metrics"]["real_model_successes"] == 0
    assert client.post(ROOT + "/versions/1/submit", json={"expected_lock_version": 3, "test_project_id": scope["project_id"]}).status_code == 409
    assert client.post(ROOT + "/test-runs", json={"version": 1, "project_id": scope["project_id"], "mode": "real_model", "expected_lock_version": 3}).status_code == 422


def _unusable_case(env):
    """Store a case whose own input violates the envelope contract (a legacy/hand-edited row).

    Test cases cannot be deleted through the API, so a contract-invalid row must stay visible
    without blocking every later run of the project scope.
    """
    _, factory, _, scope, _ = env
    with factory() as db:
        definition = db.scalar(select(AISkillDefinition).where(AISkillDefinition.skill_key == "lineage_edge_explanation"))
        case = AISkillTestCase(definition_id=definition.id, project_id=scope["project_id"], name="契约非法用例",
                               input_json={"skill_key": "lineage_edge_explanation", "task_key": "lineage_edge_explanation",
                                           "scope": scope, "subject_ref": "", "facts": [], "policy_evidence": [],
                                           "gaps": [], "max_input_bytes": 64000},
                               assertions_json={}, content_hash="contract-invalid", created_by=1)
        db.add(case)
        db.commit()
        return case.id


def test_contract_invalid_case_is_skipped_instead_of_blocking(control_env):
    client, factory, _, scope, _ = control_env
    item = prepare(control_env)
    _unusable_case(control_env)
    run = test_run(control_env, item, "deterministic", 1)
    assert run["status"] == "passed", run
    assert run["metrics"]["executed"] == 1
    assert run["metrics"]["skipped"] == 1
    model_run = test_run(control_env, item, "mock_model", 2)
    assert model_run["status"] == "passed", model_run
    assert model_run["metrics"]["executed"] == 1 and model_run["metrics"]["skipped"] == 1
    with factory() as db:
        skipped = db.scalar(select(AISkillTestResult).where(AISkillTestResult.run_id == run["id"],
                                                           AISkillTestResult.passed.is_(None)))
        assert skipped is not None and skipped.error_code == "ValidationError"
        assert skipped.assertions_json["case_defect"] is True
    submitted = client.post(ROOT + "/versions/1/submit", json={"expected_lock_version": 3, "test_project_id": scope["project_id"]})
    assert submitted.status_code == 200, submitted.text


def test_run_with_only_unusable_cases_fails(control_env):
    item = draft(control_env)
    _unusable_case(control_env)
    run = test_run(control_env, item, "deterministic", 1)
    assert run["status"] == "failed"
    assert run["metrics"]["executed"] == 0
    assert run["metrics"]["skipped"] == 1


def test_reset_to_draft_invalidates_even_identical_content(control_env):
    client, _, _, scope, _ = control_env
    ready(control_env)
    assert client.post(ROOT + "/versions/1/return-to-draft", json={"expected_lock_version": 4}).status_code == 200
    # Only rerun deterministic: old Mock pass must not carry across the reset.
    assert test_run(control_env, {"version_no": 1}, "deterministic", 5)["status"] == "passed"
    assert client.post(ROOT + "/versions/1/submit", json={"expected_lock_version": 6, "test_project_id": scope["project_id"]}).status_code == 409


def test_run_results_cross_project_denied_and_human_mode_needs_review(control_env):
    client, _, login, _, _ = control_env
    item = prepare(control_env)
    run = test_run(control_env, item, "human_review", 1)
    assert run["status"] == "pending_review"
    assert client.get(f'/ai-skill-test-runs/{run["id"]}/results').json()[0]["passed"] is None
    login("outsider")
    assert client.get(f'/ai-skill-test-runs/{run["id"]}').status_code == 404
    login("bank_admin")
    reviewed = client.post(f'/ai-skill-test-runs/{run["id"]}/human-review', json={"passed": True, "comment": "已审查合成输入"})
    assert reviewed.status_code == 200
    assert reviewed.json()["metrics"]["real_model_successes"] == 0
    assert client.post(f'/ai-skill-test-runs/{run["id"]}/human-review', json={"passed": False, "comment": "重复审核"}).status_code == 409
    assert client.get(f'/ai-skill-test-runs/{run["id"]}').json()["status"] == "passed"


def test_validation_reports_current_server_gate(control_env):
    client, _, _, scope, _ = control_env
    ready(control_env)
    response = client.post(ROOT + "/versions/1/validate", params={"test_project_id": scope["project_id"]})
    assert response.status_code == 200
    assert response.json()["release_ready"] is True
    assert response.json()["gate"] == "tests_passed"
    assert len(response.json()["test_run_ids"]) == 2


def test_published_profile_drift_blocks_execution_instead_of_switching_model(control_env):
    client, factory, _, scope, content = control_env
    ready(control_env)
    assert publish(control_env).status_code == 200
    with factory() as db:
        db.get(ModelProfile, content["model_profile_id"]).model_name = "different-model"
        db.commit()
    result = client.get("/ai-skills/resolve", params=dict(scope, skill_key="lineage_edge_explanation"))
    assert result.status_code == 409
    assert result.json()["detail"]["error_code"] == "skill_dependency_changed"


def test_database_guards_protect_published_content_and_prompt_snapshots(control_env):
    _, factory, _, _, _ = control_env
    item = ready(control_env)
    assert publish(control_env).status_code == 200
    with factory() as db:
        for sql in (
            "UPDATE ai_skill_versions SET content_hash='changed' WHERE id=:id",
            "DELETE FROM ai_skill_versions WHERE id=:id",
            "UPDATE prompt_template_versions SET user_prompt_template='changed' WHERE skill_version_id=:id",
            "DELETE FROM prompt_template_versions WHERE skill_version_id=:id",
        ):
            with pytest.raises(IntegrityError, match="immutable Skill history"):
                db.execute(text(sql), {"id": item["id"]})
            db.rollback()


def test_feedback_conversion_requires_exact_input_and_is_idempotent(control_env):
    client, factory, login, scope, _ = control_env
    ready(control_env)
    assert publish(control_env).status_code == 200
    with factory() as db:
        log = db.scalar(select(ModelCallLog))
        feedback = AIUserFeedback(project_id=scope["project_id"], model_call_log_id=log.id,
                                  feedback_type="fact_error", target_type="lineage_edge", target_id=1, rating="negative")
        db.add(feedback)
        db.commit()
        feedback_id = feedback.id
    login("manager")
    payload = {"name": "反馈回归", "input": envelope(scope).model_dump(mode="json")}
    first = client.post(ROOT + f"/feedback/{feedback_id}/test-case", json=payload)
    assert first.status_code == 200, first.text
    assert client.post(ROOT + f"/feedback/{feedback_id}/test-case", json=payload).json()["id"] == first.json()["id"]
    payload["input"]["facts"][0]["value"] = "篡改后的输入"
    assert client.post(ROOT + f"/feedback/{feedback_id}/test-case", json=payload).status_code == 409
    login("outsider")
    assert client.post(ROOT + f"/feedback/{feedback_id}/test-case", json=payload).status_code == 404
