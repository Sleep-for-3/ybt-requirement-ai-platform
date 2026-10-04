"""W09: the "project backup" artifact must be named for what it is.

It only ever carried the project id, name and a scope marker, yet it was surfaced as "项目备份"
and notified as "项目备份完成", which invites treating it as a restorable backup. The export now
declares itself a metadata manifest, states what it does not contain, and lists what a real backup
still requires.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Institution, Project, StoredFile, User
from app.services.storage.factory import get_storage_service
from app.services.task_queue import domain_handlers
from app.services.task_queue.handlers import resolve_job_handler
from app.services.task_queue import inline as inline_queue


@pytest.fixture()
def manifest_env(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    get_storage_service.cache_clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        institution = Institution(institution_code="M9", institution_name="M9", institution_type="bank", status="active")
        db.add(institution); db.flush()
        user = User(username="w09_user", display_name="W09", status="active")
        db.add(user); db.flush()
        project = Project(name="W09 项目", institution_id=institution.id, confidentiality_level="internal")
        db.add(project); db.commit()
        project_id, user_id = project.id, user.id
    yield factory, project_id, user_id
    get_storage_service.cache_clear()
    engine.dispose()


def test_the_manifest_declares_that_it_is_not_a_backup(manifest_env):
    factory, project_id, user_id = manifest_env
    with factory() as db:
        job = SimpleNamespace(project_id=project_id, created_by=user_id, institution_id=None, id=1)
        result = domain_handlers.project_manifest_export_handler(db, job)
        row = db.get(StoredFile, result["file_id"])
        payload = json.loads(get_storage_service().read(row.storage_key).decode("utf-8"))

    assert payload["artifact_kind"] == "project_metadata_manifest"
    assert payload["is_full_backup"] is False
    assert payload["backup_scope"] == "metadata"
    assert "不能用于恢复" in payload["notice"]
    # a real backup's requirements are stated rather than implied
    requires = payload["full_backup_requires"]
    assert any("PostgreSQL" in item for item in requires)
    assert any("附件" in item for item in requires)
    assert any("向量索引" in item for item in requires)
    assert payload["generated_at"]


def test_the_artifact_is_not_named_like_a_backup(manifest_env):
    factory, project_id, user_id = manifest_env
    with factory() as db:
        job = SimpleNamespace(project_id=project_id, created_by=user_id, institution_id=None, id=1)
        result = domain_handlers.project_manifest_export_handler(db, job)
        row = db.get(StoredFile, result["file_id"])
    assert row.original_file_name.endswith("-manifest.json")
    assert "backup" not in row.original_file_name


def test_the_retired_job_key_still_resolves_to_the_manifest_export():
    assert resolve_job_handler("project_manifest_export") is domain_handlers.project_manifest_export_handler
    # historical rows and clients keep working, but they get the honest export
    assert resolve_job_handler("project_backup") is domain_handlers.project_manifest_export_handler
    assert domain_handlers.project_backup_handler is domain_handlers.project_manifest_export_handler


def test_the_inline_queue_runs_the_manifest_for_the_new_key(manifest_env):
    factory, project_id, user_id = manifest_env
    with factory() as db:
        job = inline_queue.InlineTaskQueue().enqueue(
            db, job_type="project_manifest_export", institution_id=None, project_id=project_id,
            created_by=user_id, idempotency_key="w09-manifest", payload_summary={},
        )
        db.refresh(job)
        assert job.status == "completed", job.error_message
