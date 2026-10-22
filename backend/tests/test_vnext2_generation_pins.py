"""C10 在生成链路：冻结版本必须约束送入模型的证据版本。

需求快照固定了制度 v1，而知识库已启用 v2 时，生成输入不得用 v2 的条文冒充依据；
若该版本已不可用，必须以 limitation 显式阻断式说明，而不是静默替换。
"""

from copy import deepcopy

from app.models import (
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeUnit,
    Requirement,
    RequirementGenerationInput,
)
from app.services.mapping.requirement_input import _apply_version_pins
from app.services.requirement_revisions import append_revision, load_revision
from test_requirement_snapshot_api import snapshot_api, snapshot_db  # noqa: F401


def _add_active_document(db, project_id: int, title: str, regulatory_version: str, body: str) -> KnowledgeDocument:
    """Provision an active knowledge version the way the ingestion pipeline would."""

    document = KnowledgeDocument(
        project_id=project_id,
        file_name=f"{title}.docx",
        file_type="docx",
        source_type="upload",
        storage_path=f"tests/{title}.docx",
        knowledge_type="regulatory_formal",
        knowledge_scope="project",
        document_status="indexed",
        source_category="regulatory",
        confidentiality_level="internal",
        current_version_no=1,
    )
    db.add(document)
    db.flush()
    version = KnowledgeDocumentVersion(
        project_id=project_id,
        document_id=document.id,
        version_no=1,
        file_name=document.file_name,
        storage_path=document.storage_path,
        file_hash="a" * 64,
        parse_status="parsed",
        lifecycle_status="active",
        regulatory_version=regulatory_version,
    )
    db.add(version)
    db.flush()
    document.current_version_id = version.id
    db.add(KnowledgeUnit(
        project_id=project_id,
        document_id=document.id,
        document_version_id=version.id,
        knowledge_type="regulatory_formal",
        knowledge_scope="project",
        unit_type="clause",
        title=title,
        content=body,
        normalized_content=body,
        source_file_name=document.file_name,
        confidentiality_level="internal",
        enabled=True,
        content_hash="b" * 64,
    ))
    db.commit()
    return document


def test_evidence_without_pins_is_untouched():
    evidence = [{"unit_id": 1, "title": "某办法", "regulatory_version": "2026-v2", "content": "x"}]
    kept, pins, limitations = _apply_version_pins(evidence, {})
    assert kept == evidence
    assert pins == {}
    assert limitations == []


def test_pinned_version_keeps_matching_evidence_and_records_the_pin():
    evidence = [{"unit_id": 1, "title": "产品期限组合键管理办法", "regulatory_version": "2026-v1", "content": "v1 条文"}]
    content = {"fields": [{"evidence": [{"title": "产品期限组合键管理办法", "regulatory_version": "2026-v1"}]}]}
    kept, pins, limitations = _apply_version_pins(evidence, content)
    assert [item["unit_id"] for item in kept] == [1]
    assert pins == {"产品期限组合键管理办法": "2026-v1"}
    assert limitations == []


def test_other_version_is_excluded_instead_of_silently_replacing_the_pin():
    evidence = [
        {"unit_id": 2, "title": "产品期限组合键管理办法", "regulatory_version": "2026-v2", "content": "v2 条文"},
        {"unit_id": 3, "title": "其他管理办法", "regulatory_version": "2026-v9", "content": "无关资料"},
    ]
    content = {"fields": [{"evidence": [{"title": "产品期限组合键管理办法", "regulatory_version": "2026-v1"}]}]}
    kept, pins, limitations = _apply_version_pins(evidence, content)
    # 未被钉扎的资料保留；被钉扎但版本不符的必须排除。
    assert [item["unit_id"] for item in kept] == [3]
    assert any("已排除 2026-v2" in line for line in limitations)
    assert any("没有该版本的可用证据" in line for line in limitations)
    assert all("其他管理办法" not in line for line in limitations)


def test_conflicting_versions_in_one_snapshot_are_not_pinned():
    evidence = [{"unit_id": 1, "title": "某办法", "regulatory_version": "2026-v1", "content": "x"}]
    content = {"fields": [{"evidence": [{"title": "某办法", "regulatory_version": "2026-v1"},
                                        {"title": "某办法", "regulatory_version": "2026-v2"}]}]}
    kept, pins, limitations = _apply_version_pins(evidence, content)
    assert kept == evidence
    assert pins == {}
    assert any("多个版本" in line for line in limitations)


def test_generation_input_reports_pin_and_blocks_a_newer_active_version(snapshot_api):  # noqa: F811
    client, db, project, field, req, _ = snapshot_api
    doc = _add_active_document(db, project.id, "产品期限组合键管理办法", "2026-v2", "PIN_SENTINEL_V2")
    assert client.put(f"/projects/{project.id}/requirements/{req.id}", json={
        **req.scope_json, "name": req.name, "expected_version": 1, "document_ids": [doc.id],
    }).status_code == 200
    base = f"/projects/{project.id}/requirements/{req.id}"
    assert client.post(base + "/revisions", json={"expected_version": 2}).status_code == 201

    requirement = db.get(Requirement, req.id)
    revision = load_revision(db, project.id, req.id, requirement.content_version)
    content = deepcopy(revision.content_json)
    content["fields"][0].setdefault("evidence", []).append(
        {"title": "产品期限组合键管理办法", "regulatory_version": "2026-v1", "content": "冻结时的 v1 依据"}
    )
    append_revision(db, requirement, content, revision.content_version, revision.created_by)
    db.commit()

    response = client.post(base + "/generation-inputs", json={
        "expected_content_version": requirement.content_version,
        "field_ids": [field.id], "sections": ["business"], "idempotency_key": "pinned-input",
    })
    assert response.status_code == 201, response.text
    frozen = db.get(RequirementGenerationInput, response.json()["id"]).input_json
    # 现行 v2 不能被当作 v1 的依据送入模型。
    assert "PIN_SENTINEL_V2" not in str(frozen)
    assert frozen["evidence"] == []
    assert frozen["pinned_versions"] == {"产品期限组合键管理办法": "2026-v1"}
    assert any("2026-v1" in line and "没有该版本的可用证据" in line for line in frozen["limitations"])


def test_generation_input_without_pins_still_uses_the_active_version(snapshot_api):  # noqa: F811
    client, db, project, field, req, _ = snapshot_api
    doc = _add_active_document(db, project.id, "产品期限组合键管理办法", "2026-v2", "ACTIVE_SENTINEL_V2")
    assert client.put(f"/projects/{project.id}/requirements/{req.id}", json={
        **req.scope_json, "name": req.name, "expected_version": 1, "document_ids": [doc.id],
    }).status_code == 200
    base = f"/projects/{project.id}/requirements/{req.id}"
    assert client.post(base + "/revisions", json={"expected_version": 2}).status_code == 201
    response = client.post(base + "/generation-inputs", json={
        "expected_content_version": 1, "field_ids": [field.id], "sections": ["business"],
        "idempotency_key": "unpinned-input",
    })
    assert response.status_code == 201, response.text
    frozen = db.get(RequirementGenerationInput, response.json()["id"]).input_json
    assert "ACTIVE_SENTINEL_V2" in str(frozen)
    assert "pinned_versions" not in frozen
    assert not any("没有该版本的可用证据" in line for line in frozen["limitations"])
from fastapi import HTTPException


def test_pin_limitation_reaches_the_candidate_as_a_gap(snapshot_api, monkeypatch):  # noqa: F811
    from app.models import BackgroundJob, RequirementGenerationItem
    from app.services.task_queue.inline import InlineTaskQueue

    client, db, project, field, req, _ = snapshot_api
    doc = _add_active_document(db, project.id, "产品期限组合键管理办法", "2026-v2", "PIN_SENTINEL_V2")
    assert client.put(f"/projects/{project.id}/requirements/{req.id}", json={
        **req.scope_json, "name": req.name, "expected_version": 1, "document_ids": [doc.id],
    }).status_code == 200
    base = f"/projects/{project.id}/requirements/{req.id}"
    assert client.post(base + "/revisions", json={"expected_version": 2}).status_code == 201
    requirement = db.get(Requirement, req.id)
    revision = load_revision(db, project.id, req.id, requirement.content_version)
    content = deepcopy(revision.content_json)
    content["fields"][0].setdefault("evidence", []).append(
        {"title": "产品期限组合键管理办法", "regulatory_version": "2026-v1", "content": "冻结时的 v1 依据"}
    )
    append_revision(db, requirement, content, revision.content_version, revision.created_by)
    db.commit()

    monkeypatch.setattr("app.services.task_queue.factory.get_task_queue", lambda: InlineTaskQueue())
    monkeypatch.setattr(
        "app.services.requirement_generation_worker.generate_candidate",
        lambda db, row, item, project: {"final_content": "合成中文候选正文，仅用于版本钉扎缺口回归", "gaps": []},
    )
    response = client.post(base + "/generation-runs", json={
        "expected_content_version": requirement.content_version, "field_ids": [field.id],
        "sections": ["business"], "idempotency_key": "pinned-run",
    })
    assert response.status_code == 201, response.text
    job = db.get(BackgroundJob, response.json()["job_id"])
    assert job is not None
    item = db.query(RequirementGenerationItem).order_by(RequirementGenerationItem.id.desc()).first()
    assert item.status == "completed"
    gaps = item.candidate_json["gaps"]
    assert any("2026-v1" in gap and "没有该版本的可用证据" in gap for gap in gaps)
    assert "PIN_SENTINEL_V2" not in str(item.candidate_json)
