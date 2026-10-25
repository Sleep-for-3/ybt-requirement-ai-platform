import copy
import json

from fastapi.encoders import jsonable_encoder

from app.models import RequirementGenerationInput, RequirementGenerationItem
from app.services.requirement_scope import content_digest, document_content as real_document_content

from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401


def _content_with_basis(db, requirement, *, script_file_id=7, bindings=None):
    content = copy.deepcopy(jsonable_encoder(real_document_content(db, requirement)))
    content["script_basis"] = {
        "versions": [{
            "script_file_id": script_file_id,
            "version_id": 5,
            "version_no": 1,
            "parse_status": "parsed",
            "file_name": "YBT_T_1_5.sql",
        }],
        "confirmation": {"target_key": "[null, \"SAFE_INSTANCE_GB\", \"T_1_5\"]", "field_bindings": bindings or {}},
        "rules": [],
        "template": {"tables": [], "versions": []},
        "metadata": {"target_table_code": "T_1_5"},
        "policy_snapshot": [],
    }
    return content


def _prepare(snapshot_api, db, requirement, content):
    client, _, _, _, _, _ = snapshot_api
    hash_value = content_digest(content)
    # 让接口拿到的是"带冻结脚本依据"的内容，而修订本身仍是真实投影。
    import app.api.requirements as api

    original = api.document_content
    api.document_content = lambda database, row: content
    try:
        response = client.post(
            f"/projects/{requirement.project_id}/requirements/{requirement.id}/script-basis-regenerate",
            data={
                "script_file_id": str(content["script_basis"]["versions"][0]["script_file_id"]),
                "expected_version": str(requirement.version),
                "expected_hash": hash_value,
                "sections": "business",
            },
        )
    finally:
        api.document_content = original
    return response


def test_regenerate_rejects_script_outside_frozen_basis(snapshot_api, snapshot_db):
    client, db, project, field, requirement, _ = snapshot_api
    client.post(f"/projects/{project.id}/requirements/{requirement.id}/revisions", json={"expected_version": requirement.version})
    db.refresh(requirement)
    content = _content_with_basis(db, requirement, script_file_id=7)

    import app.api.requirements as api

    original = api.document_content
    api.document_content = lambda database, row: content
    try:
        response = client.post(
            f"/projects/{project.id}/requirements/{requirement.id}/script-basis-regenerate",
            data={
                "script_file_id": "9",
                "expected_version": str(requirement.version),
                "expected_hash": content_digest(content),
                "sections": "business",
            },
        )
    finally:
        api.document_content = original

    assert response.status_code == 409, response.text
    assert "冻结依据" in response.json()["detail"]
    assert db.query(RequirementGenerationInput).count() == 0


def test_regenerate_rejects_when_no_bound_field_available(snapshot_api, snapshot_db):
    client, db, project, field, requirement, _ = snapshot_api
    client.post(f"/projects/{project.id}/requirements/{requirement.id}/revisions", json={"expected_version": requirement.version})
    db.refresh(requirement)
    content = _content_with_basis(db, requirement, bindings={})
    response = _prepare(snapshot_api, db, requirement, content)

    assert response.status_code == 409, response.text
    assert "绑定字段" in response.json()["detail"]
    assert db.query(RequirementGenerationItem).count() == 0


def test_regenerate_creates_input_and_items_for_bound_fields(snapshot_api, snapshot_db):
    client, db, project, field, requirement, _ = snapshot_api
    client.post(f"/projects/{project.id}/requirements/{requirement.id}/revisions", json={"expected_version": requirement.version})
    db.refresh(requirement)
    content = _content_with_basis(db, requirement, bindings={field.field_code: field.id})
    response = _prepare(snapshot_api, db, requirement, content)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["field_count"] == 1
    assert body["sections"] == ["business"]

    row = db.get(RequirementGenerationInput, body["input_id"])
    assert row is not None
    assert row.input_json["field_ids"] == [field.id]
    items = db.query(RequirementGenerationItem).filter_by(input_id=row.id).all()
    assert [(item.field_id, item.section) for item in items] == [(field.id, "business")]

    # 同一内容重复调用：同一输入（幂等），不会重复建条目。
    again = _prepare(snapshot_api, db, requirement, content)
    assert again.status_code == 201, again.text
    assert again.json()["input_id"] == body["input_id"]
    assert db.query(RequirementGenerationItem).filter_by(input_id=body["input_id"]).count() == 1


def test_regenerate_rejects_unknown_section(snapshot_api, snapshot_db):
    client, db, project, field, requirement, _ = snapshot_api
    client.post(f"/projects/{project.id}/requirements/{requirement.id}/revisions", json={"expected_version": requirement.version})
    db.refresh(requirement)
    content = _content_with_basis(db, requirement, bindings={field.field_code: field.id})

    import app.api.requirements as api

    original = api.document_content
    api.document_content = lambda database, row: content
    try:
        response = client.post(
            f"/projects/{project.id}/requirements/{requirement.id}/script-basis-regenerate",
            data={
                "script_file_id": "7",
                "expected_version": str(requirement.version),
                "expected_hash": content_digest(content),
                "sections": "policy",
            },
        )
    finally:
        api.document_content = original

    assert response.status_code == 422, response.text
    assert "business" in response.json()["detail"]
