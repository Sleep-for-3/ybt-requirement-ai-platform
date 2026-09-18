from copy import deepcopy

from sqlalchemy import select

from app.models import Requirement, RequirementGenerationInput, RequirementGenerationItem, ScenarioBusinessMapping
from app.services.requirement_scope import content_digest
from test_requirement_snapshot_api import snapshot_api, snapshot_db


def candidate_item(client, db, base, version, field_id, section, key, candidate):
    response = client.post(base + "/generation-inputs", json={"expected_content_version": version,
        "field_ids": [field_id], "sections": [section], "idempotency_key": key})
    assert response.status_code == 201, response.text
    item = RequirementGenerationItem(input_id=response.json()["id"], field_id=field_id, section=section,
        status="completed", candidate_json=candidate, candidate_hash=content_digest(candidate))
    db.add(item)
    db.commit()
    return item


def test_candidate_diff_requires_explicit_manual_replacement_and_appends_revision(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    other = Requirement(project_id=project.id, name="另一需求", version=1, scope_json=deepcopy(req.scope_json))
    db.add(other)
    db.commit()
    base = f"/projects/{project.id}/requirements/{req.id}"
    other_base = f"/projects/{project.id}/requirements/{other.id}"
    client.post(base + "/revisions", json={"expected_version": 1})
    client.post(other_base + "/revisions", json={"expected_version": 1})
    edited = client.put(base + f"/fields/{field.id}", json={"expected_content_version": 1,
        "section": "business", "changes": {"business_definition": "人工定义"}})
    assert edited.status_code == 200
    candidate = {"business_definition": "模型候选定义", "processing_logic": "", "final_content": "模型候选正文",
        "physical_references": [], "evidence_unit_ids": [], "gaps": ["候选依据仍需确认"]}
    item = candidate_item(client, db, base, 2, field.id, "business", "candidate-manual", candidate)
    detail = client.get(base + f"/generation-items/{item.id}")
    assert detail.status_code == 200, detail.text
    changes = {row["field"]: row for row in detail.json()["changes"]}
    assert changes["business_definition"] == {"field": "business_definition", "current": "人工定义",
        "proposed": "模型候选定义", "changed": True, "manual": True}
    payload = {"expected_content_version": 2, "candidate_hash": item.candidate_hash,
        "selected_fields": ["business_definition", "final_content"], "replace_manual_fields": []}
    blocked = client.post(base + f"/generation-items/{item.id}/adopt", json=payload)
    assert blocked.status_code == 409 and "business_definition" in blocked.text
    adopted = client.post(base + f"/generation-items/{item.id}/adopt",
        json={**payload, "replace_manual_fields": ["business_definition"]})
    assert adopted.status_code == 200, adopted.text
    document = adopted.json()["document"]
    assert document["revision"]["content_version"] == 3
    assert document["fields"][0]["business"]["business_definition"] == "模型候选定义"
    assert document["fields"][0]["business"]["final_content"] == "模型候选正文"
    assert any(gap["message"] == "候选依据仍需确认" for gap in document["gaps"])
    assert document["manual_ownership"][str(field.id)]["business.business_definition"]["kind"] == "ai_adopted"
    assert client.get(base + "/revisions/2").json()["fields"][0]["business"]["business_definition"] == "人工定义"
    assert "模型候选" not in client.get(other_base + "/document").text
    assert db.scalar(select(ScenarioBusinessMapping).where(ScenarioBusinessMapping.target_field_id == field.id)) is None
    repeated = client.post(base + f"/generation-items/{item.id}/adopt",
        json={**payload, "replace_manual_fields": ["business_definition"]})
    assert repeated.status_code == 200 and repeated.json()["idempotent"] is True


def test_rejected_and_stale_candidates_cannot_change_content(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    client.post(base + "/revisions", json={"expected_version": 1})
    candidate = {"business_definition": "候选", "processing_logic": "", "final_content": "候选正文",
        "physical_references": [], "evidence_unit_ids": [], "gaps": []}
    rejected = candidate_item(client, db, base, 1, field.id, "business", "candidate-reject", candidate)
    response = client.post(base + f"/generation-items/{rejected.id}/reject",
        json={"candidate_hash": rejected.candidate_hash, "reason": "证据不足"})
    assert response.status_code == 200 and response.json()["decision"] == "rejected"
    assert client.post(base + f"/generation-items/{rejected.id}/reject",
        json={"candidate_hash": rejected.candidate_hash, "reason": "证据不足"}).json()["idempotent"] is True
    assert client.post(base + f"/generation-items/{rejected.id}/adopt", json={"expected_content_version": 1,
        "candidate_hash": rejected.candidate_hash, "selected_fields": ["final_content"],
        "replace_manual_fields": []}).status_code == 409
    stale = candidate_item(client, db, base, 1, field.id, "business", "candidate-stale", candidate)
    client.put(base + f"/fields/{field.id}", json={"expected_content_version": 1,
        "section": "business", "changes": {"remarks": "后续人工修改"}})
    result = client.post(base + f"/generation-items/{stale.id}/adopt", json={"expected_content_version": 1,
        "candidate_hash": stale.candidate_hash, "selected_fields": ["final_content"],
        "replace_manual_fields": []})
    assert result.status_code == 409
    assert client.get(base + f"/generation-items/{stale.id}").json()["stale"] is True


def test_tampered_candidate_and_cross_project_access_are_rejected(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    client.post(base + "/revisions", json={"expected_version": 1})
    candidate = {"business_definition": "候选", "processing_logic": "", "final_content": "正文",
        "physical_references": [], "evidence_unit_ids": [], "gaps": []}
    item = candidate_item(client, db, base, 1, field.id, "business", "candidate-tamper", candidate)
    item.candidate_json = {**candidate, "final_content": "被篡改"}
    db.commit()
    assert client.get(base + f"/generation-items/{item.id}").status_code == 409
    assert client.get(f"/projects/{project.id + 999}/requirements/{req.id}/generation-items/{item.id}").status_code == 404


def test_batch_adoption_keeps_sibling_candidates_current_until_one_revision_is_created(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    client.post(base + "/revisions", json={"expected_version": 1})
    prepared = client.post(base + "/generation-inputs", json={"expected_content_version": 1,
        "field_ids": [field.id], "sections": ["business", "lineage"], "idempotency_key": "batch-shared"})
    assert prepared.status_code == 201, prepared.text
    first_content = {"business_definition": "批量业务定义", "processing_logic": "", "final_content": "批量业务正文",
        "physical_references": [], "evidence_unit_ids": [], "gaps": []}
    second_content = {"business_definition": "", "processing_logic": "批量技术规则", "final_content": "批量技术正文",
        "physical_references": [], "evidence_unit_ids": [], "gaps": ["关联条件仍待确认"]}
    first = RequirementGenerationItem(input_id=prepared.json()["id"], field_id=field.id, section="business",
        status="completed", candidate_json=first_content, candidate_hash=content_digest(first_content))
    second = RequirementGenerationItem(input_id=prepared.json()["id"], field_id=field.id, section="lineage",
        status="completed", candidate_json=second_content, candidate_hash=content_digest(second_content))
    db.add_all([first, second])
    db.commit()
    response = client.post(base + "/generation-candidates/adopt", json={"expected_content_version": 1,
        "selections": [
            {"item_id": first.id, "candidate_hash": first.candidate_hash,
             "selected_fields": ["business_definition", "final_content"], "replace_manual_fields": []},
            {"item_id": second.id, "candidate_hash": second.candidate_hash,
             "selected_fields": ["processing_logic", "final_content"], "replace_manual_fields": []},
        ]})
    assert response.status_code == 200, response.text
    document = response.json()["document"]
    assert document["revision"]["content_version"] == 2
    assert document["fields"][0]["business"]["business_definition"] == "批量业务定义"
    assert document["fields"][0]["lineage"]["processing_logic"] == "批量技术规则"
    db.refresh(first); db.refresh(second)
    assert first.decision == second.decision == "adopted"
    assert first.adopted_content_version == second.adopted_content_version == 2
