from copy import deepcopy

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import (CatalogColumn, KnowledgeDocumentVersion, ScriptFile, ReviewTask,
    RequirementRevision, Project, TemplateVersion)
from app.models.requirement import RequirementRecheck
from app.services.requirement_revisions import load_revision
from app.services.auth.dependencies import Principal
from app.services.governance.workflow import decide_task
from test_requirement_snapshot_api import snapshot_api, snapshot_db
from test_requirement_uat import confirmed_sample
from test_requirement_formal_delivery import _reviewers


def changed_sample(sample):
    base = confirmed_sample(sample)
    client, db, project, _, req, membership = sample
    script = db.scalar(select(ScriptFile).where(ScriptFile.project_id == project.id))
    frozen = deepcopy(load_revision(db, project.id, req.id, 4).content_json)
    script.current_version_no += 1; db.flush()
    impacts = client.get(f"/projects/{project.id}/requirements/change-impacts").json()
    assert len(impacts["items"]) == 1
    impact = impacts["items"][0]
    payload = {"expected_content_version":4,"change_hash":impact["change_hash"]}
    opened = client.post(base + "/rechecks", json=payload)
    assert opened.status_code == 201, opened.text
    return base, script, frozen, opened.json(), payload


def test_impact_tasks_are_idempotent_and_never_modify_history(snapshot_api):
    client, db, project, _, req, _ = snapshot_api
    base, script, frozen, row, payload = changed_sample(snapshot_api)
    again = client.post(base + "/rechecks", json=payload)
    assert again.status_code == 201 and again.json()["id"] == row["id"]
    assert len(list(db.scalars(select(ReviewTask).where(ReviewTask.target_type=="requirement_recheck")))) == 1
    assert load_revision(db, project.id, req.id, 4).content_json == frozen
    assert req.content_version == 4
    assert client.post(base + "/rechecks", json={**payload,"change_hash":"0"*64}).status_code == 409
    reviewers = _reviewers(db, project.id); user = reviewers["technical_reviewer"]
    task = db.get(ReviewTask, row["tasks"][0]["id"])
    with pytest.raises(HTTPException) as error:
        decide_task(db, task, Principal(user.id,user.username,None), "approved", "不能未修订直接通过")
    assert error.value.status_code == 409


def test_explicit_new_revision_preserves_authored_content_and_requires_reconfirmation(snapshot_api):
    client, db, project, _, req, _ = snapshot_api
    base, script, frozen, row, _ = changed_sample(snapshot_api)
    revised = client.post(base + f"/rechecks/{row['id']}/revise", json={"expected_content_version":4,"reason":"脚本变化，重核加工规则"})
    assert revised.status_code == 201, revised.text
    current = load_revision(db, project.id, req.id, 5).content_json
    assert current["fields"][0]["business"] == frozen["fields"][0]["business"]
    assert "confirmed_path" not in current["fields"][0]
    assert "policy_comparisons" not in current
    assert current["recheck_origin"]["recheck_id"] == row["id"]
    assert load_revision(db, project.id, req.id, 4).content_json == frozen
    assert client.post(base + f"/rechecks/{row['id']}/resolution", json={"expected_content_version":5,"reason":"未核验"}).status_code == 409
    assert db.get(RequirementRecheck,row["id"]).replacement_revision_id is None


def test_resolution_requires_new_current_verified_revision_and_approval_is_not_requirement_approval(snapshot_api):
    from app.services.requirement_revisions import append_revision
    client, db, project, _, req, _ = snapshot_api
    base, script, frozen, row, _ = changed_sample(snapshot_api)
    # Controlled recovery of upstream state; explicit user revision still required.
    script.current_version_no -= 1; db.flush()
    assert client.post(base + f"/rechecks/{row['id']}/resolution", json={"expected_content_version":4,"reason":"仍为旧版本"}).status_code == 409
    newer = append_revision(db, req, deepcopy(frozen), 4, row.get("created_by"))
    resolved = client.post(base + f"/rechecks/{row['id']}/resolution", json={"expected_content_version":5,"reason":"新版本逐项核验依据恢复且路径一致"})
    assert resolved.status_code == 200, resolved.text
    user = _reviewers(db, project.id)["technical_reviewer"]
    decide_task(db, db.get(ReviewTask,row["tasks"][0]["id"]), Principal(user.id,user.username,None), "approved", "已核对修订及影响")
    assert db.get(RequirementRecheck,row["id"]).status == "reviewed"
    assert load_revision(db, project.id, req.id, 5).status == "draft"
    assert load_revision(db, project.id, req.id, 4).content_json == frozen
    from app.services.governance.workflow import start_workflow
    with pytest.raises(HTTPException) as error:
        start_workflow(db, project_id=project.id, workflow_key="requirement_change_review",
            target_type="requirement_recheck", target_id=row["id"], created_by=user.id)
    assert error.value.status_code == 409


def test_unresolved_parser_gaps_cannot_close_recheck(snapshot_api):
    from app.services.requirement_revisions import append_revision
    client, db, _, _, req, _ = snapshot_api
    base, script, frozen, row, _ = changed_sample(snapshot_api)
    script.current_version_no -= 1; db.flush()
    content = deepcopy(frozen)
    content["script_basis"]["gaps"].append("动态 SQL 无法静态展开")
    append_revision(db, req, content, 4, None)
    response = client.post(base + f"/rechecks/{row['id']}/resolution",
        json={"expected_content_version":5,"reason":"存在未解析语句"})
    assert response.status_code == 409
    assert "解析缺口" in response.json()["detail"]
    assert db.get(RequirementRecheck, row["id"]).replacement_revision_id is None


def test_recheck_access_isolation_and_in_review_protection(snapshot_api):
    client, db, project, _, req, membership = snapshot_api
    base, _, _, row, payload = changed_sample(snapshot_api)
    membership.project_role="viewer";db.flush()
    assert client.post(base + "/rechecks",json=payload).status_code == 403
    assert client.post(base+f"/rechecks/{row['id']}/revise",json={"expected_content_version":4,"reason":"越权"}).status_code==403
    other=Project(name="其他隔离机构");db.add(other);db.flush()
    assert client.get(f"/projects/{other.id}/requirements/change-impacts").status_code==404
    membership.project_role="project_manager";db.flush()
    load_revision(db,project.id,req.id,4).status="in_review";db.flush()
    assert client.post(base+f"/rechecks/{row['id']}/revise",json={"expected_content_version":4,"reason":"审核中"}).status_code==409


@pytest.mark.parametrize("change,code", [
    ("metadata", "script:metadata"),
    ("template", "script:template"),
    ("policy", "script:policy"),
])
def test_metadata_template_and_policy_drift_require_explicit_review(snapshot_api, change, code):
    client, db, project, _, req, _ = snapshot_api
    base = confirmed_sample(snapshot_api)
    frozen = deepcopy(load_revision(db, project.id, req.id, 4).content_json)
    if change == "metadata":
        column = db.scalar(select(CatalogColumn).where(CatalogColumn.project_id == project.id,
            CatalogColumn.table_name == "accounts", CatalogColumn.column_name == "amount"))
        column.data_type = "VARCHAR(100)"; db.flush()
    elif change == "template":
        template = db.get(TemplateVersion, frozen["script_basis"]["template"]["id"])
        template.status = "inactive"; db.flush()
    else:
        version = db.get(KnowledgeDocumentVersion,
            frozen["script_basis"]["policy_snapshot"]["evidence"][0]["document_version_id"])
        version.lifecycle_status = "expired"; db.flush()
    impacts = client.get(f"/projects/{project.id}/requirements/change-impacts")
    assert impacts.status_code == 200, impacts.text
    item = next(row for row in impacts.json()["items"] if row["requirement_id"] == req.id)
    assert any(change_row["code"] == code for change_row in item["changes"])
    assert load_revision(db, project.id, req.id, 4).content_json == frozen
