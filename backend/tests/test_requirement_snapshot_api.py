"""Exercise actual HTTP authorization and frozen content, without external services."""
from io import BytesIO

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.requirements import router
from app.core.database import Base, get_db
from app.models import Project, ProjectMembership, RequirementDelivery, User
from app.services.auth.dependencies import Principal, get_current_principal
from app.services.auth.resource_guard import guard_project_resource
from test_requirement_draft_snapshots import fixture


@pytest.fixture
def snapshot_db():
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def snapshot_api(snapshot_db):
    db_session = snapshot_db
    project, field, requirement, content = fixture(db_session)
    user = db_session.scalar(select(User))
    membership = ProjectMembership(project_id=project.id, user_id=user.id,
                                   project_role="project_manager", status="active")
    db_session.add(membership)
    db_session.flush()
    app = FastAPI()
    app.include_router(router, dependencies=[Depends(guard_project_resource)])
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_principal] = lambda: Principal(user.id, user.username, None)
    with TestClient(app) as client:
        yield client, db_session, project, field, requirement, membership


def test_http_snapshot_permissions_and_project_isolation(snapshot_api):
    client, db, project, _, req, membership = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    preview = client.get(base + "/document").json()
    payload = {"expected_version": 1, "expected_hash": preview["content_hash"]}
    membership.project_role = "viewer"
    db.flush()
    assert client.get(base + "/snapshots").status_code == 200
    assert client.post(base + "/snapshots", json=payload).status_code == 403
    assert db.scalar(select(func.count()).select_from(RequirementDelivery)) == 0
    membership.project_role = "project_manager"
    db.flush()
    response = client.post(base + "/snapshots", json=payload)
    assert response.status_code == 201
    snapshot_id = response.json()["id"]
    membership.project_role = "viewer"
    db.flush()
    assert client.get(base + f"/snapshots/{snapshot_id}/export").status_code == 403
    other = Project(name="隔离合成无权限项目")
    db.add(other)
    db.flush()
    hidden = f"/projects/{other.id}/requirements/{req.id}/snapshots"
    assert client.get(hidden).status_code == 404
    assert client.post(hidden, json=payload).status_code == 404
    assert client.get(hidden + f"/{snapshot_id}/export").status_code == 404
    membership.status = "inactive"
    db.flush()
    assert client.get(base + "/snapshots").status_code == 404


def test_http_snapshot_stale_preview_deduplication_and_frozen_download(snapshot_api):
    client, db, project, field, req, _ = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    preview = client.get(base + "/document").json()
    payload = {"expected_version": 1, "expected_hash": preview["content_hash"]}
    first = client.post(base + "/snapshots", json=payload).json()
    again = client.post(base + "/snapshots", json=payload).json()
    assert first["id"] == again["id"] and again["deduplicated"]
    assert first["status"] == "frozen_draft"
    field.field_name = "后续修改不得改变历史"
    db.flush()
    assert client.post(base + "/snapshots", json=payload).status_code == 409
    req.version += 1
    db.flush()
    assert client.post(base + "/snapshots", json=payload).status_code == 409
    response = client.get(base + f"/snapshots/{first['id']}/export")
    assert response.status_code == 200
    book = load_workbook(BytesIO(response.content))
    assert book["字段口径"]["B2"].value == preview["fields"][0]["field"]["field_name"]
    assert "草稿" in book["需求范围"]["B2"].value
    assert client.get(base + f"/snapshots/{first['id'] + 999}/export").status_code == 404


def test_auditor_frozen_export_does_not_require_legacy_export_permission(snapshot_api):
    client, db, project, _, req, membership = snapshot_api
    base = f"/projects/{project.id}/requirements/{req.id}"
    preview = client.get(base + "/document").json()
    snapshot = client.post(base + "/snapshots", json={"expected_version": 1,
        "expected_hash": preview["content_hash"]}).json()
    membership.project_role = "auditor"
    db.flush()
    assert client.get(base + f"/snapshots/{snapshot['id']}/export").status_code == 200
    assert client.get(base + "/export").status_code == 403
    assert client.post(base + "/snapshots", json={"expected_version": 1,
        "expected_hash": preview["content_hash"]}).status_code == 403
