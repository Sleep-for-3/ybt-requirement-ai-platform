from copy import deepcopy

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.uat import router as uat_router
from app.models import UatCase, UatCaseResult, UatRun, ReviewTask, Project, ScriptFile
from app.models.requirement import RequirementUatLink
from app.services.auth.dependencies import Principal
from app.services.governance.workflow import decide_task
from app.services.requirement_revisions import load_revision
from app.services.uat.execution import execute_uat_run
from test_requirement_snapshot_api import snapshot_api, snapshot_db
from test_requirement_paths import setup_path, confirm
from test_requirement_formal_delivery import _reviewers


def confirmed_sample(sample, multilayer=False):
    client, db, project, field, req, membership = sample
    client.app.include_router(uat_router)
    base, unit, _ = setup_path(sample, multilayer)
    assert confirm(client, base)[0].status_code == 201
    policy = client.get(base + "/policy-comparison?content_version=3").json()
    response = client.post(base + "/policy-comparison", json={"expected_content_version": 3,
        "basis_hash": policy["basis_hash"], "decisions": [{"unit_id": unit.id, "status": "matched",
            "rule_ids": [r["rule_id"] for r in policy["rules"]], "rationale": "脱敏样本核验原值取数"}]})
    assert response.status_code == 201, response.text
    return base


def approve_suite(client, db, project, suite_id):
    reviewers = _reviewers(db, project.id)
    response = client.post(f"/uat-suites/{suite_id}/requirement-review", json={})
    assert response.status_code == 201, response.text
    tasks = response.json()["tasks"]
    for task in tasks:
        role = "technical_reviewer" if task["step_key"] == "technical_review" else "final_reviewer"
        user = reviewers[role]
        decide_task(db, db.get(ReviewTask, task["id"]), Principal(user.id, user.username, None), "approved", "已核验规则与预期结果")


@pytest.mark.parametrize("multilayer", [False, True])
def test_confirmed_rules_create_reviewed_manual_uat_with_fixed_evidence(snapshot_api, multilayer):
    client, db, project, field, req, membership = snapshot_api
    base = confirmed_sample(snapshot_api, multilayer)
    frozen = deepcopy(load_revision(db, project.id, req.id, 4).content_json)
    response = client.post(base + "/uat-suites", json={"expected_content_version":4})
    assert response.status_code == 201, response.text
    link = response.json(); suite_id = link["suite_id"]
    assert client.post(base + "/uat-suites", json={"expected_content_version":4}).json()["id"] == link["id"]
    suite = client.get(f"/uat-suites/{suite_id}").json()
    assert len(suite["cases"]) == (3 if multilayer else 1)
    assert all(c["execution_mode"] == "manual" for c in suite["cases"])
    assert client.post(f"/uat-suites/{suite_id}/runs", json={"run_name":"未审核禁止执行"}).status_code == 409
    assert client.post(f"/uat-suites/{suite_id}/clone", json={}).status_code == 409
    approve_suite(client, db, project, suite_id)
    assert client.get(f"/uat-suites/{suite_id}/requirement-review").json()["status"] == "approved"
    run = client.post(f"/uat-suites/{suite_id}/runs", json={"run_name":"隔离人工验证"})
    assert run.status_code == 201, run.text
    summary = execute_uat_run(db, run.json()["id"])
    assert summary["pending_count"] == len(suite["cases"]) and summary["passed_count"] == 0
    results = list(db.scalars(select(UatCaseResult).where(UatCaseResult.uat_run_id == run.json()["id"])))
    for result in results:
        url = f"/uat-case-results/{result.id}/complete-manual"
        assert client.post(url, json={"status":"passed","actual_result_json":{},"evidence_json":{}}).status_code == 422
        payload = {"status":"passed","actual_result_json":{"expected_value":"120.00", "actual_value":"120.00", "conclusion":"合成原值样本一致"},
            "evidence_json":{"sample":"sanitized-case-A", "verification":"人工逐项核验记录", "requirement_evidence":{"rule_id":"forged"}}}
        completed = client.post(url, json=payload)
        assert completed.status_code == 200, completed.text
        evidence = completed.json()["evidence_json"]["requirement_evidence"]
        assert evidence["content_hash"] == load_revision(db, project.id, req.id, 4).content_hash
        assert evidence["rule_id"] != "forged"
        attached = client.post(f"/uat-case-results/{result.id}/attach-evidence", json={"evidence":{"requirement_evidence":{"rule_id":"forged-again"}}})
        assert attached.status_code == 200
        assert attached.json()["evidence_json"]["requirement_evidence"] == evidence
    assert db.get(UatRun, run.json()["id"]).status == "passed"
    assert load_revision(db, project.id, req.id, 4).content_json == frozen


def test_unconfirmed_conflicting_and_stale_requirements_cannot_create_tests(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    base, _, _ = setup_path(snapshot_api)
    assert client.post(base + "/uat-suites", json={"expected_content_version":2}).status_code == 409
    assert confirm(client, base)[0].status_code == 201
    assert client.post(base + "/uat-suites", json={"expected_content_version":3}).status_code == 409


def test_uat_permissions_drift_and_tampering_are_enforced(snapshot_api):
    client, db, project, _, req, membership = snapshot_api
    base = confirmed_sample(snapshot_api)
    membership.project_role = "viewer"; db.flush()
    assert client.post(base + "/uat-suites", json={"expected_content_version":4}).status_code == 403
    other = Project(name="另一个机构项目"); db.add(other); db.flush()
    assert client.get(f"/projects/{other.id}/requirements/{req.id}/uat-suites").status_code == 404
    membership.project_role = "project_manager"; db.flush()
    link = client.post(base + "/uat-suites", json={"expected_content_version":4}).json()
    approve_suite(client, db, project, link["suite_id"])
    script = db.scalar(select(ScriptFile).where(ScriptFile.project_id == project.id))
    script.current_version_no += 1; db.flush()
    assert client.get(base + "/uat-suites").json()[0]["pending_review"]
    assert client.post(f"/uat-suites/{link['suite_id']}/runs", json={"run_name":"旧依据"}).status_code == 409
    script.current_version_no -= 1; db.flush()
    case = db.scalar(select(UatCase).where(UatCase.uat_suite_id == link["suite_id"]))
    case.expected_result_json = {"forged":True}; db.flush()
    assert client.post(f"/uat-suites/{link['suite_id']}/runs", json={"run_name":"已篡改"}).status_code == 409


def test_author_cannot_review_own_cases(snapshot_api):
    client, db, project, _, _, membership = snapshot_api
    base = confirmed_sample(snapshot_api)
    link = client.post(base + "/uat-suites", json={"expected_content_version":4}).json()
    tasks = client.post(f"/uat-suites/{link['suite_id']}/requirement-review", json={}).json()["tasks"]
    task = db.get(ReviewTask, tasks[0]["id"])
    membership.project_role = "technical_reviewer"; db.flush()
    with pytest.raises(HTTPException) as exc:
        decide_task(db, task, Principal(membership.user_id, "synthetic-author", None), "approved", "不能自审")
    assert exc.value.status_code == 409
