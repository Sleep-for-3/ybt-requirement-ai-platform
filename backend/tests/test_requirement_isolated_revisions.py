from copy import deepcopy
from io import BytesIO

from openpyxl import load_workbook
from sqlalchemy import select

from app.models import Requirement, RequirementRevision, ScenarioBusinessMapping, SourceToMartMapping
from test_requirement_snapshot_api import snapshot_api, snapshot_db


def test_scope_graph_removes_excluded_roots_without_mutating_history():
    from app.services.requirement_revisions import scope_graph, reset_imported_status
    graph = {"nodes": [{"id": "asset:target_field:1"}, {"id": "asset:target_field:2"}],
        "edges": [], "tables": [{"id": "target:1", "fields": ["asset:target_field:1", "asset:target_field:2"]}],
        "root_ids": ["asset:target_field:1", "asset:target_field:2"], "truncated": False}
    before = deepcopy(graph)
    scoped = scope_graph(graph, [1])
    assert scoped["root_ids"] == ["asset:target_field:1"]
    assert scoped["tables"][0]["fields"] == ["asset:target_field:1"]
    assert graph == before
    record = {"business": {"business_confirm_status": "confirmed"}, "lineage": {"tech_confirm_status": "approved"}}
    reset_imported_status(record)
    assert record["business"]["business_confirm_status"] == "draft"
    assert record["lineage"]["tech_confirm_status"] == "draft"
    assert record["imported_status"] == {"business": "confirmed", "technical": "approved"}


def test_requirements_are_independent_and_history_and_export_stay_fixed(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    other = Requirement(project_id=project.id, name="第二份合成需求", scope_json=deepcopy(req.scope_json), version=1)
    db.add(other)
    db.commit()
    base = f"/projects/{project.id}/requirements/{req.id}"
    other_base = f"/projects/{project.id}/requirements/{other.id}"
    for path in (base, other_base):
        response = client.post(path + "/revisions", json={"expected_version": 1})
        assert response.status_code == 201, response.text
    before = client.get(base + "/revisions/1").json()
    assert client.post(base + "/revisions", json={"expected_version": 1}).json()["revision"]["content_version"] == 1
    response = client.put(base + f"/fields/{field.id}", json={"expected_content_version": 1,
        "section": "business", "changes": {"business_definition": "需求A人工结构化定义"}})
    assert response.status_code == 200, response.text
    edited = response.json()
    assert edited["revision"]["content_version"] == 2
    assert edited["manual_ownership"][str(field.id)]["business.business_definition"]["content_version"] == 2
    assert f"{field.id}:definition" not in {gap["id"] for gap in edited["gaps"]}
    assert any(gap["id"] == f"{field.id}:definition" and gap["resolution_basis"]["content_version"] == 2
        for gap in edited["gap_history"])
    assert client.get(base + "/revisions/1").json() == before
    assert "需求A人工结构化定义" not in client.get(other_base + "/document").text
    assert db.scalar(select(ScenarioBusinessMapping).where(ScenarioBusinessMapping.target_field_id == field.id)) is None
    field.field_name = "共享字段后续改名"
    db.commit()
    current = client.get(base + "/document").json()
    assert current["fields"][0]["field"]["field_name"] == before["fields"][0]["field"]["field_name"]
    book = load_workbook(BytesIO(client.get(base + "/export").content))
    assert book["字段口径"]["C2"].value == "需求A人工结构化定义"
    cleared = client.put(base + f"/fields/{field.id}", json={"expected_content_version":2,
        "section":"business", "changes":{"business_definition":"  ", "final_content":""}}).json()
    assert sum(gap["id"] == f"{field.id}:definition" for gap in cleared["gaps"]) == 1


def test_revisions_reject_stale_scope_content_permission_and_locked_state(snapshot_api):
    client, db, project, field, req, membership = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    assert client.post(base + "/revisions", json={"expected_version": 9}).status_code == 409
    client.post(base + "/revisions", json={"expected_version": 1})
    payload = {"expected_content_version": 1,"section":"business","changes":{"final_content":"人工正文"}}
    assert client.put(base + f"/fields/{field.id+999}", json=payload).status_code == 404
    assert client.put(base + f"/fields/{field.id}", json={**payload,"changes":{"business_confirm_status":"confirmed"}}).status_code == 422
    membership.project_role = "viewer"
    db.commit()
    assert client.put(base + f"/fields/{field.id}", json=payload).status_code == 403
    membership.project_role = "business_analyst"
    db.commit()
    assert client.put(base + f"/fields/{field.id}", json={**payload,"section":"lineage"}).status_code == 403
    assert client.put(base + f"/fields/{field.id}", json=payload).status_code == 200
    assert client.put(base + f"/fields/{field.id}", json=payload).status_code == 409
    assert client.get(f"/projects/{project.id+999}/requirements/{req.id}/revisions/1").status_code == 404
    current = db.scalar(select(RequirementRevision).where(RequirementRevision.requirement_id == req.id,
        RequirementRevision.content_version == 2))
    current.status = "confirmed"  # Simulate the future governed approval service, never an API bypass.
    db.commit()
    assert client.put(base + f"/fields/{field.id}", json={**payload,"expected_content_version":2}).status_code == 409
    revision_response = client.post(base + "/revisions/2/revise", json={"expected_content_version":2,"reason":"调整报送口径"})
    assert revision_response.status_code == 201, revision_response.text
    assert revision_response.json()["revision"]["content_version"] == 3
    assert client.get(base + "/revisions/2").json()["revision"]["status"] == "confirmed"
    assert client.put(base + f"/fields/{field.id}", json={**payload,"expected_content_version":3}).status_code == 200


def test_scope_revision_preserves_requirement_edits(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    client.post(base + "/revisions", json={"expected_version":1})
    client.put(base + f"/fields/{field.id}", json={"expected_content_version":1,"section":"business",
        "changes":{"business_definition":"必须保留的本需求定义"}})
    payload = {**req.scope_json,"name":req.name,"background":"修订背景", "expected_version":1}
    assert client.put(base,json=payload).status_code == 409
    response = client.put(base,json={**payload,"expected_content_version":2})
    assert response.status_code == 200, response.text
    content = client.get(base + "/document").json()
    assert content["requirement"]["background"] == "修订背景"
    assert content["revision"]["content_version"] == 3
    assert content["fields"][0]["business"]["business_definition"] == "必须保留的本需求定义"


def test_lineage_snapshot_is_permission_checked_and_never_rebuilt_from_live_facts(snapshot_api):
    client, db, project, field, req, membership = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    assert client.post(base + "/revisions", json={"expected_version":1}).status_code == 201
    path = base + "/revisions/1/lineage"
    original = client.get(path).json()
    assert len(original["graph"]["tables"]) == 3
    mapping = db.scalar(select(SourceToMartMapping).where(SourceToMartMapping.project_id == project.id))
    mapping.filter_condition = "SHARED_CHANGED = 1"
    db.commit()
    assert client.get(path).json() == original
    assert "lineage_graph" not in client.get(base + "/document").json()
    membership.project_role = "business_analyst"
    db.commit()
    assert client.get(path).status_code == 403
    membership.project_role = "project_manager"
    db.commit()
    changed = client.put(base + f"/fields/{field.id}", json={"expected_content_version":1,
        "section":"lineage", "changes":{"processing_logic":"人工修改，待核验"}})
    assert changed.status_code == 200
    assert client.get(base + "/revisions/2/lineage").json()["graph"] is None
    assert client.get(path).json() == original
