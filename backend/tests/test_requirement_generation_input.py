from copy import deepcopy

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import RequirementGenerationInput, RequirementGenerationItem, KnowledgeDocumentVersion, KnowledgeUnit, SourceTable, TargetField, BackgroundJob
from app.services.mapping.requirement_input import validate_physical_references
from test_requirement_resources import add_document
from test_requirement_snapshot_api import snapshot_api, snapshot_db


def add_unit(db, project_id, document, text):
    version = KnowledgeDocumentVersion(project_id=project_id, document_id=document.id, version_no=1,
        file_name=document.file_name, storage_path="isolated-not-read", file_hash="synthetic")
    db.add(version)
    db.flush()
    unit = KnowledgeUnit(project_id=project_id, document_id=document.id, document_version_id=version.id,
        knowledge_type="regulatory", knowledge_scope="project", unit_type="paragraph", content=text,
        normalized_content=text, source_file_name=document.file_name, content_hash="synthetic")
    db.add(unit)
    db.flush()
    return unit


def test_generation_input_empty_means_no_retrieval_and_retries_are_fixed(snapshot_api):
    client, db, project, field, req, membership = snapshot_api
    doc = add_document(db, project.id, "未选择的测试资料")
    add_unit(db, project.id, doc, "EXCLUDED_SENTINEL")
    base = f"/projects/{project.id}/requirements/{req.id}"
    client.post(base + "/revisions", json={"expected_version":1})
    payload = {"expected_content_version":1,"field_ids":[field.id],"sections":["business"],"idempotency_key":"attempt-one"}
    response = client.post(base + "/generation-inputs", json=payload)
    assert response.status_code == 201, response.text
    row = db.get(RequirementGenerationInput, response.json()["id"])
    assert row.input_json["evidence"] == []
    assert row.input_json["physical_sources"] == []
    assert "EXCLUDED_SENTINEL" not in str(row.input_json)
    frozen = deepcopy(row.input_json)
    changed = client.put(base, json={**req.scope_json,"name":req.name,"background":"新背景" * 2000,
        "expected_version":1,"expected_content_version":1})
    assert changed.status_code == 200, changed.text
    retry = client.post(base + "/generation-inputs", json=payload)
    assert retry.json()["deduplicated"]
    assert db.get(RequirementGenerationInput, row.id).input_json == frozen
    assert client.post(base + "/generation-inputs", json={**payload,"expected_content_version":2}).status_code == 409
    new = client.post(base + "/generation-inputs", json={**payload,"expected_content_version":2,"idempotency_key":"attempt-two"})
    assert new.status_code == 201, new.text
    assert db.get(RequirementGenerationInput, new.json()["id"]).input_json["requirement"]["background"] == "新背景" * 2000
    membership.project_role = "viewer"
    db.commit()
    assert client.post(base + "/generation-inputs", json=payload).status_code == 403


def test_generation_input_selects_only_allowed_evidence_and_physical_sources(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    allowed = add_document(db, project.id, "已选择资料")
    forbidden = add_document(db, project.id, "未选择资料")
    add_unit(db, project.id, allowed, "ALLOWED_EVIDENCE")
    add_unit(db, project.id, forbidden, "FORBIDDEN_EVIDENCE")
    source = db.scalar(select(SourceTable).where(SourceTable.project_id == project.id))
    base = f"/projects/{project.id}/requirements/{req.id}"
    assert client.put(base, json={**req.scope_json,"name":req.name,"expected_version":1,
        "document_ids":[allowed.id],"source_table_ids":[source.id]}).status_code == 200
    client.post(base + "/revisions", json={"expected_version":2})
    payload = {"expected_content_version":1,"field_ids":[field.id],"sections":["lineage"],"idempotency_key":"selected-one"}
    result = client.post(base + "/generation-inputs", json=payload)
    assert result.status_code == 201, result.text
    frozen = db.get(RequirementGenerationInput, result.json()["id"]).input_json
    assert "ALLOWED_EVIDENCE" in str(frozen) and "FORBIDDEN_EVIDENCE" not in str(frozen)
    assert frozen["physical_sources"] and all(item["table_id"] == source.id and item["kind"] == "source" for item in frozen["physical_sources"])
    validate_physical_references(frozen, [frozen["physical_sources"][0]])
    with pytest.raises(HTTPException):
        validate_physical_references(frozen, [{"kind":"source","table_id":source.id,"field_id":99999}])
    allowed.document_status = "archived"
    db.commit()
    assert client.post(base + "/generation-inputs", json={**payload,"idempotency_key":"selected-two"}).status_code == 409


def test_generation_input_blocks_oversize_without_truncation(snapshot_api, monkeypatch):
    client, _, project, field, req, _ = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    client.post(base + "/revisions", json={"expected_version":1})
    monkeypatch.setattr("app.services.mapping.requirement_input.MAX_INPUT_BYTES", 20)
    response = client.post(base + "/generation-inputs", json={"expected_content_version":1,
        "field_ids":[field.id],"sections":["business"],"idempotency_key":"oversize-one"})
    assert response.status_code == 422
    assert "未被截断" in response.text


def test_scoped_queue_eight_fields_retries_only_failed_and_never_writes_content(snapshot_api, monkeypatch):
    from app.services.task_queue.inline import InlineTaskQueue
    from app.services.requirement_generation_worker import requirement_generation_handler
    client, db, project, field, req, _ = snapshot_api
    ids = [field.id]
    for index in range(7):
        added = TargetField(project_id=project.id, target_table_id=field.target_table_id,
            field_code=f"ISOLATED_{index}", field_name=f"合成字段{index}")
        db.add(added)
        db.flush()
        ids.append(added.id)
    req.scope_json = {**req.scope_json, "field_ids":ids}
    db.commit()
    base = f"/projects/{project.id}/requirements/{req.id}"
    assert client.post(base + "/revisions", json={"expected_version":1}).status_code == 201
    before = client.get(base + "/document").json()
    queue = InlineTaskQueue()
    monkeypatch.setattr("app.services.task_queue.factory.get_task_queue", lambda: queue)
    calls = []
    def generate(db, row, item, project):
        calls.append(item.field_id)
        if item.field_id == ids[-1] and calls.count(item.field_id) == 1:
            raise RuntimeError("isolated failure")
        return {"final_content":"合成候选，不是真实模型质量验收", "gaps":["待验证"]}
    monkeypatch.setattr("app.services.requirement_generation_worker.generate_candidate", generate)
    payload = {"expected_content_version":1,"field_ids":ids,"sections":["business"],"idempotency_key":"eight-fields"}
    result = client.post(base + "/generation-runs", json=payload)
    assert result.status_code == 201, result.text
    job = db.get(BackgroundJob, result.json()["job_id"])
    assert job.status == "partially_completed"
    assert job.payload_summary_json == {"input_id":result.json()["input_id"]}
    assert len(calls) == 8
    repeat = client.post(base + "/generation-runs", json=payload)
    assert repeat.json()["job_id"] == job.id and len(calls) == 8
    retry = client.post(base + f"/generation-runs/{result.json()['input_id']}/retry", json={"job_id": job.id})
    assert retry.status_code == 200, retry.text
    assert len(calls) == 9 and job.status == "completed"
    assert client.get(base + "/document").json() == before
    summary = client.get(base + "/generation-runs").json()[0]
    assert len(summary["items"]) == 8
    assert summary["status"] == "completed" and summary["counts"]["completed"] == 8
    assert all(item.status == "completed" for item in db.scalars(select(RequirementGenerationItem)))
    requirement_generation_handler(db, job)
    assert len(calls) == 9


def test_permission_revoked_during_generation_discards_candidate(snapshot_api, monkeypatch):
    from app.services.task_queue.inline import InlineTaskQueue
    client, db, project, field, req, membership = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    client.post(base + "/revisions", json={"expected_version":1})
    monkeypatch.setattr("app.services.task_queue.factory.get_task_queue", lambda: InlineTaskQueue())
    def generate(db, row, item, project):
        membership.project_role = "viewer"
        db.commit()
        return {"final_content":"不得落库的候选"}
    monkeypatch.setattr("app.services.requirement_generation_worker.generate_candidate", generate)
    response = client.post(base + "/generation-runs", json={"expected_content_version":1,
        "field_ids":[field.id],"sections":["business"],"idempotency_key":"revoke-during"})
    assert response.status_code == 201, response.text
    item = db.scalar(select(RequirementGenerationItem))
    assert item.status == "blocked" and item.candidate_json is None


def test_isolated_mock_provider_returns_candidate_without_writing_requirement(snapshot_api, monkeypatch):
    from app.services.task_queue.inline import InlineTaskQueue
    client, db, project, field, req, _ = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    client.post(base + "/revisions", json={"expected_version": 1})
    before = client.get(base + "/document").json()
    monkeypatch.setattr("app.services.task_queue.factory.get_task_queue", lambda: InlineTaskQueue())
    response = client.post(base + "/generation-runs", json={"expected_content_version": 1,
        "field_ids": [field.id], "sections": ["business"], "idempotency_key": "mock-protocol"})
    assert response.status_code == 201, response.text
    item = db.scalar(select(RequirementGenerationItem))
    assert item.status == "completed" and item.decision == "pending"
    assert item.candidate_json["runtime"]["test_provider"] is True
    assert "Fake Provider" not in str(item.candidate_json)
    assert client.get(base + "/document").json() == before
