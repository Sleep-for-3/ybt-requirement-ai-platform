"""W03 / B03: approved double-layer content is immutable, and approval binds to content.

BA01: a technical analyst could PUT ``final_content`` on an approved mapping and the row kept
``mapping_status='approved'`` with no new revision, so the business saw "reviewed" content that
had changed after approval. Delivery readiness then trusted the ``approved`` string alone.

These tests exercise the real API: the ordinary PUT must be refused, an explicit re-open must
create a new revision while preserving the previously approved snapshot, and readiness must not
report approval when the approved content no longer matches its snapshot.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models import (
    MappingEvidenceReference,
    MappingVersion,
    MartField,
    MartTable,
    MartToYbtMapping,
    Project,
    ProjectMembership,
    SourceToMartMapping,
    TargetField,
    TargetTable,
    User,
    WorkflowInstance,
)
from app.services.auth.dependencies import Principal
from app.services.governance.double_layer_review import (
    APPROVED_CONTENT_IMMUTABLE,
    DOUBLE_LAYER_REVIEW_WORKFLOW,
    approved_mapping_is_current,
)

API = "/api"


@contextmanager
def _client() -> Iterator[tuple[TestClient, sessionmaker]]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[None] = None
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _seed(factory: sessionmaker) -> dict[str, int]:
    """A minimal double-layer project with draft mappings and evidence for both layers."""
    with factory() as db:
        project = Project(name="B03 复核项目")
        db.add(project)
        db.flush()
        table = TargetTable(project_id=project.id, table_code="YBT_B03", table_name="B03 表")
        db.add(table)
        db.flush()
        field = TargetField(project_id=project.id, target_table_id=table.id,
                            field_code="B03_F", field_name="B03 字段")
        mart_table = MartTable(project_id=project.id, table_code="MART_B03", table_name="B03 集市表")
        db.add_all([field, mart_table])
        db.flush()
        mart_field = MartField(project_id=project.id, mart_table_id=mart_table.id,
                               field_code="MART_B03_F", field_name="B03 集市字段")
        db.add(mart_field)
        db.flush()
        source = SourceToMartMapping(project_id=project.id, mart_field_id=mart_field.id,
                                     final_content="原始来源口径", mapping_status="draft")
        ybt = MartToYbtMapping(project_id=project.id, target_field_id=field.id,
                               mart_field_id=mart_field.id,
                               final_content="原始目标口径", mapping_status="draft")
        db.add_all([source, ybt])
        db.flush()
        for mapping_type, mapping_id in (("source_to_mart", source.id), ("mart_to_ybt", ybt.id)):
            db.add(MappingEvidenceReference(project_id=project.id, mapping_type=mapping_type,
                                            mapping_id=mapping_id, evidence_type="manual_note",
                                            source_name="脱敏人工确认"))
        db.commit()
        return {"project_id": int(project.id), "source_id": int(source.id), "ybt_id": int(ybt.id)}


def _approve(client: TestClient, mapping_type: str, mapping_id: int) -> dict:
    segment = "source-to-mart-mappings" if mapping_type == "source_to_mart" else "mart-to-ybt-mappings"
    response = client.post(f"{API}/{segment}/{mapping_id}/approve",
                           json={"reviewed_by": "复核人", "change_note": "首次批准"})
    assert response.status_code == 200, response.text
    return response.json()


def _put(client: TestClient, mapping_type: str, mapping_id: int, body: dict):
    segment = "source-to-mart-mappings" if mapping_type == "source_to_mart" else "mart-to-ybt-mappings"
    return client.put(f"{API}/{segment}/{mapping_id}", json=body)


def test_approval_records_the_approved_content_snapshot():
    with _client() as (client, factory):
        ids = _seed(factory)
        approved = _approve(client, "source_to_mart", ids["source_id"])
        assert approved["mapping_status"] == "approved"
        assert approved["reviewed_by"] == "复核人"

        with factory() as db:
            row = db.get(SourceToMartMapping, ids["source_id"])
            versions = db.scalars(select(MappingVersion).where(
                MappingVersion.mapping_type == "source_to_mart",
                MappingVersion.mapping_id == row.id)).all()
            assert [v.content_snapshot for v in versions] == ["原始来源口径"]
            assert approved_mapping_is_current(db, "source_to_mart", row) is True


@pytest.mark.parametrize("mapping_type,key", [("source_to_mart", "source_id"),
                                             ("mart_to_ybt", "ybt_id")])
def test_a_content_edit_on_approved_content_is_refused(mapping_type, key):
    with _client() as (client, factory):
        ids = _seed(factory)
        mapping_id = ids[key]
        _approve(client, mapping_type, mapping_id)

        response = _put(client, mapping_type, mapping_id, {"business_rule": "批准后被偷改的规则"})
        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert detail["reason_code"] == APPROVED_CONTENT_IMMUTABLE

        model = SourceToMartMapping if mapping_type == "source_to_mart" else MartToYbtMapping
        with factory() as db:
            row = db.get(model, mapping_id)
            assert row.mapping_status == "approved"
            assert row.business_rule != "批准后被偷改的规则"
            assert approved_mapping_is_current(db, mapping_type, row) is True


def test_a_status_only_change_still_works():
    """Approving/rejecting is a lifecycle action, not a content edit."""
    with _client() as (client, factory):
        ids = _seed(factory)
        response = _put(client, "source_to_mart", ids["source_id"],
                        {"mapping_status": "reviewed"})
        assert response.status_code == 200, response.text
        assert response.json()["mapping_status"] == "reviewed"


@pytest.mark.parametrize("mapping_type,key", [("source_to_mart", "source_id"),
                                             ("mart_to_ybt", "ybt_id")])
def test_an_explicit_reopen_creates_a_new_revision_and_keeps_the_old_snapshot(mapping_type, key):
    with _client() as (client, factory):
        ids = _seed(factory)
        mapping_id = ids[key]
        _approve(client, mapping_type, mapping_id)
        model = SourceToMartMapping if mapping_type == "source_to_mart" else MartToYbtMapping

        response = _put(client, mapping_type, mapping_id,
                        {"mapping_status": "draft", "business_rule": "新修订的规则"})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["mapping_status"] == "draft"
        assert payload["reviewed_by"] is None and payload["reviewed_at"] is None
        assert payload["business_rule"] == "新修订的规则"

        with factory() as db:
            row = db.get(model, mapping_id)
            # the previously approved content is preserved and no longer considered current
            snapshots = [v.content_snapshot for v in db.scalars(select(MappingVersion).where(
                MappingVersion.mapping_type == mapping_type, MappingVersion.mapping_id == row.id)).all()]
            assert snapshots == [("原始来源口径" if mapping_type == "source_to_mart" else "原始目标口径")]
            assert approved_mapping_is_current(db, mapping_type, row) is False


def test_an_in_progress_review_freezes_content_writes_and_deletes():
    with _client() as (client, factory):
        ids = _seed(factory)
        with factory() as db:
            user = User(username='b03_reviewer', display_name='B03 审核', status='active')
            db.add(user)
            db.flush()
            db.add(WorkflowInstance(project_id=ids["project_id"],
                                    workflow_key=DOUBLE_LAYER_REVIEW_WORKFLOW,
                                    target_type="source_to_mart", target_id=ids["source_id"],
                                    status="in_progress", created_by=user.id))
            db.commit()

        refused = _put(client, "source_to_mart", ids["source_id"], {"business_rule": "送审期间改内容"})
        assert refused.status_code == 409
        assert refused.json()["detail"]["reason_code"] == "DOUBLE_LAYER_REVIEW_IN_PROGRESS"

        deleted = client.delete(f"{API}/source-to-mart-mappings/{ids['source_id']}")
        assert deleted.status_code == 409


def test_an_approved_mapping_cannot_be_deleted_until_it_is_reopened():
    with _client() as (client, factory):
        ids = _seed(factory)
        _approve(client, "source_to_mart", ids["source_id"])

        blocked = client.delete(f"{API}/source-to-mart-mappings/{ids['source_id']}")
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["reason_code"] == APPROVED_CONTENT_IMMUTABLE

        with factory() as db:
            assert db.get(SourceToMartMapping, ids["source_id"]) is not None

        reopened = _put(client, "source_to_mart", ids["source_id"], {"mapping_status": "draft"})
        assert reopened.status_code == 200
        allowed = client.delete(f"{API}/source-to-mart-mappings/{ids['source_id']}")
        assert allowed.status_code == 200, allowed.text
