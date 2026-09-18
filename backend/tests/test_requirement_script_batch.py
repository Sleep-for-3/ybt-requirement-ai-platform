from copy import deepcopy

from sqlalchemy import select, func

from app.models import Requirement, TargetTable, TargetField, TemplateVersion, Project
from app.models.requirement import RequirementScriptBatch
from app.services.requirement_revisions import load_revision
from test_requirement_snapshot_api import snapshot_api, snapshot_db
from test_requirement_script_basis import seed


def batch_payload(sample):
    client, db, project, field, req, membership = sample
    _, service, script, confirmation, _ = seed(client, db, project, req, field,
        "INSERT INTO bank.reg.report (amount) SELECT amount FROM bank.ods.accounts; "
        "INSERT INTO bank.reg.other (balance) SELECT amount FROM bank.ods.accounts;")
    table = TargetTable(project_id=project.id, table_code="OTHER", table_name="另一张监管表")
    db.add(table); db.flush()
    second = TargetField(project_id=project.id, target_table_id=table.id, field_code="balance", field_name="余额")
    db.add(second); db.flush()
    template = db.get(TemplateVersion, confirmation["template_version_id"])
    template.parsed_snapshot_json = [*template.parsed_snapshot_json, {"table_code": "OTHER"}]
    db.flush()
    preview = client.post(f"/projects/{project.id}/requirements/script-preview",
        json={"script_version_ids": [script.version.id]}).json()
    targets = []
    for physical, target_id, column, field_id in [("report", req.scope_json["target_table_id"], "amount", field.id),
                                                ("other", table.id, "balance", second.id)]:
        targets.append({"scope": {"name": f"脚本反向需求-{physical}", "target_table_id": target_id,
            "field_ids": [field_id], "scenario_id": req.scope_json["scenario_id"]},
            "template_version_id": template.id,
            "target_key": next(t["key"] for t in preview["targets"] if t["table_name"] == physical),
            "field_bindings": {column: field_id}})
    return {"idempotency_key": "two-regulatory-targets", "script_version_ids": [script.version.id],
        "preview_hash": preview["preview_hash"], "targets": targets}, preview


def test_multi_target_atomic_versioned_and_idempotent(snapshot_api):
    client, db, project, _, _, _ = snapshot_api
    payload, preview = batch_payload(snapshot_api)
    assert any(s["matches"] for s in preview["regulatory_targets"]["suggestions"])
    url = f"/projects/{project.id}/requirements/from-scripts"
    first = client.post(url, json=payload)
    assert first.status_code == 201, first.text
    result = first.json()
    assert len(result["requirements"]) == 2
    for created in result["requirements"]:
        revision = load_revision(db, project.id, created["requirement_id"], 2)
        assert revision.content_json["requirement"]["script_requirement_batch_id"] == result["batch_id"]
        assert revision.content_json["script_basis"]["confirmation"]["target_table_id"] == created["target_table_id"]
        assert [v["id"] for v in revision.content_json["script_basis"]["versions"]] == payload["script_version_ids"]
        assert revision.status == "draft"
    assert client.post(url, json=payload).json() == {**result, "deduplicated": True}
    changed = deepcopy(payload); changed["targets"][0]["scope"]["name"] = "不同请求"
    assert client.post(url, json=changed).status_code == 409
    assert db.scalar(select(func.count()).select_from(RequirementScriptBatch)) == 1
    created = result["requirements"][0]
    requirement = db.get(Requirement, created["requirement_id"])
    updated = client.put(f"/projects/{project.id}/requirements/{requirement.id}", json={
        **payload["targets"][0]["scope"], "expected_version": 1, "expected_content_version": 2,
        "background": "业务补充背景"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["script_requirement_batch_id"] == result["batch_id"]
    assert load_revision(db, project.id, requirement.id, 3).content_json["requirement"]["script_requirement_batch_id"] == result["batch_id"]


def test_failed_second_target_rolls_back_first_and_retry_is_possible(snapshot_api):
    client, db, project, _, _, _ = snapshot_api
    payload, _ = batch_payload(snapshot_api)
    before = db.scalar(select(func.count()).select_from(Requirement))
    broken = deepcopy(payload); broken["targets"][1]["field_bindings"] = {"missing": 99999}
    url = f"/projects/{project.id}/requirements/from-scripts"
    response = client.post(url, json=broken)
    assert response.status_code == 422, response.text
    assert db.scalar(select(func.count()).select_from(Requirement)) == before
    assert db.scalar(select(func.count()).select_from(RequirementScriptBatch)) == 0
    assert client.post(url, json=payload).status_code == 201


def test_only_successful_imported_versions_can_enter_batch(snapshot_api):
    from app.models.batch_import import ResourceImportBatch, ResourceImportItem
    from app.models import StoredFile
    client, db, project, _, _, membership = snapshot_api
    payload, _ = batch_payload(snapshot_api)
    batch = ResourceImportBatch(project_id=project.id, created_by=membership.user_id,
        idempotency_key="synthetic-import", request_hash="0" * 64, status="partial")
    db.add(batch); db.flush()
    stored_id = db.scalar(select(StoredFile.id))
    item = ResourceImportItem(batch_id=batch.id, relative_path="batch.sql", file_kind="sql",
        stored_file_id=stored_id, status="failed", result_json={"script_version_id":payload["script_version_ids"][0]})
    db.add(item); db.flush()
    payload["import_batch_id"] = batch.id
    url = f"/projects/{project.id}/requirements"
    excluded = client.get(f"{url}/import-batch/{batch.id}/scripts").json()
    assert excluded["script_version_ids"] == [] and len(excluded["excluded_items"]) == 1
    assert client.post(url + "/from-scripts", json=payload).status_code == 422
    item.status = "completed"; db.flush()
    assert client.get(f"{url}/import-batch/{batch.id}/scripts").json()["script_version_ids"] == payload["script_version_ids"]
    result = client.post(url + "/from-scripts", json=payload)
    assert result.status_code == 201, result.text
    assert result.json()["import_batch_id"] == batch.id


def test_batch_permissions_cross_project_and_stale_preview(snapshot_api):
    client, db, project, _, _, membership = snapshot_api
    payload, _ = batch_payload(snapshot_api)
    url = f"/projects/{project.id}/requirements/from-scripts"
    membership.project_role = "viewer"; db.flush()
    assert client.post(url, json=payload).status_code == 403
    membership.project_role = "project_manager"; db.flush()
    other = Project(name="隔离其他项目"); db.add(other); db.flush()
    assert client.post(f"/projects/{other.id}/requirements/from-scripts", json=payload).status_code == 404
    assert client.post(url, json={**payload, "preview_hash": "0" * 64}).status_code == 409
    assert client.post(url, json={**payload, "import_batch_id": 99999}).status_code == 404
    assert db.scalar(select(func.count()).select_from(RequirementScriptBatch)) == 0
