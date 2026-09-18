from copy import deepcopy
from io import BytesIO

import pytest
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from openpyxl import load_workbook

from app.models import Requirement
from app.services import requirement_delivery as service
from app.services.requirement_scope import content_digest, document_content, export_document
from test_requirement_scope import scope_fixture


def fixture(db):
    project, field, payload = scope_fixture(db)
    requirement = Requirement(project_id=project.id, name=payload.name, version=1,
        scope_json=payload.model_dump(mode="json", exclude={"expected_version", "name"}))
    db.add(requirement)
    db.flush()
    content = jsonable_encoder(document_content(db, requirement))
    return project, field, requirement, content


def test_frozen_export_does_not_read_later_live_facts(db_session, monkeypatch):
    project, field, req, content = fixture(db_session)
    snapshot, created = service.freeze_draft(db_session, project.id, req.id, req.version,
                                            content_digest(content), None)
    assert created
    frozen = deepcopy(snapshot.content_json)
    req.name = "后续改名"
    req.version += 1
    field.field_name = "后续字段名"
    db_session.flush()
    monkeypatch.setattr(service, "document_content", lambda *args: pytest.fail("历史导出不能查询当前事实"))
    loaded = service.load_frozen_draft(db_session, project.id, req.id, snapshot.id)
    assert loaded.content_json == frozen
    book = load_workbook(BytesIO(export_document(loaded.content_json)))
    assert book["需求范围"]["B1"].value == content["requirement"]["name"]
    assert book["字段口径"]["B2"].value == content["fields"][0]["field"]["field_name"]
    assert "草稿" in book["需求范围"]["B2"].value
    assert service.snapshot_summary(loaded)["status"] == "frozen_draft"


def test_same_preview_reuses_snapshot_and_changed_content_requires_new_preview(db_session):
    project, field, req, content = fixture(db_session)
    digest = content_digest(content)
    first, created = service.freeze_draft(db_session, project.id, req.id, 1, digest, None)
    again, created_again = service.freeze_draft(db_session, project.id, req.id, 1, digest, None)
    assert created and not created_again and first.id == again.id
    field.field_name = "事实发生变化"
    db_session.flush()
    with pytest.raises(HTTPException) as error:
        service.freeze_draft(db_session, project.id, req.id, 1, digest, None)
    assert error.value.status_code == 409


def test_snapshot_rejects_stale_scope_cross_scope_and_integrity_failure(db_session):
    project, _, req, content = fixture(db_session)
    digest = content_digest(content)
    with pytest.raises(HTTPException) as error:
        service.freeze_draft(db_session, project.id, req.id, 2, digest, None)
    assert error.value.status_code == 409
    snapshot, _ = service.freeze_draft(db_session, project.id, req.id, 1, digest, None)
    for project_id, requirement_id in [(project.id + 999, req.id), (project.id, req.id + 999)]:
        with pytest.raises(HTTPException) as error:
            service.load_frozen_draft(db_session, project_id, requirement_id, snapshot.id)
        assert error.value.status_code == 404
    snapshot.content_json = {**snapshot.content_json, "status": "tampered"}
    db_session.flush()
    with pytest.raises(HTTPException) as error:
        service.load_frozen_draft(db_session, project.id, req.id, snapshot.id)
    assert error.value.status_code == 409
