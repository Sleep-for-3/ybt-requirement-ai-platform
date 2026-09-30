"""Real independent SQLite connections exercise repeat-event serialization."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import sqlite3
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session

from app.models import Requirement, ReviewTask, ScriptFile, WorkflowInstance
from app.models.requirement import RequirementRecheck
from app.services.requirement_recheck import create_recheck, impact_summary
from app.services.requirement_revisions import load_revision
from test_requirement_snapshot_api import snapshot_api, snapshot_db
from test_requirement_uat import confirmed_sample


@pytest.fixture
def concurrent_recheck_db(snapshot_api, tmp_path):
    confirmed_sample(snapshot_api)
    _, db, project, _, req, membership = snapshot_api
    script = db.scalar(select(ScriptFile).where(ScriptFile.project_id == project.id))
    script.current_version_no += 1
    db.flush()
    impact = impact_summary(db, req)
    ids = project.id, req.id, membership.user_id, impact["change_hash"]
    db.commit()
    database = tmp_path / "rechecks.sqlite"
    with sqlite3.connect(database) as destination:
        db.connection().connection.driver_connection.backup(destination)
    engine = create_engine(f"sqlite:///{database.as_posix()}", connect_args={"timeout": 15})
    try:
        yield engine, ids
    finally:
        engine.dispose()


def test_concurrent_same_event_creates_one_recheck_and_workflow(concurrent_recheck_db):
    engine, (project_id, requirement_id, actor_id, change_hash) = concurrent_recheck_db
    with Session(engine) as db:
        req = db.get(Requirement, requirement_id)
        original_timestamp = req.updated_at
        original = deepcopy(load_revision(db, project_id, requirement_id, 4).content_json)
    ready = Barrier(2)

    def trigger():
        with Session(engine) as db:
            req = db.get(Requirement, requirement_id)
            ready.wait(timeout=10)
            row = create_recheck(db, req, 4, change_hash, actor_id)
            identifier = row.id
            db.commit()
            return identifier

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: trigger(), range(2)))
    assert results[0] == results[1]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(RequirementRecheck)) == 1
        for model in (WorkflowInstance, ReviewTask):
            assert db.scalar(select(func.count()).select_from(model).where(
                model.target_type == "requirement_recheck", model.target_id == results[0])) == 1
        req = db.get(Requirement, requirement_id)
        assert req.content_version == 4 and req.updated_at == original_timestamp
        assert load_revision(db, project_id, requirement_id, 4).content_json == original


def test_stale_loaded_requirement_cannot_create_old_recheck(concurrent_recheck_db):
    engine, (_, requirement_id, actor_id, change_hash) = concurrent_recheck_db
    with Session(engine) as stale:
        req = stale.get(Requirement, requirement_id)
        with Session(engine) as writer:
            writer.execute(update(Requirement).where(Requirement.id == requirement_id).values(content_version=5))
            writer.commit()
        with pytest.raises(HTTPException) as error:
            create_recheck(stale, req, 4, change_hash, actor_id)
        assert error.value.status_code == 409
        stale.rollback()
        assert stale.scalar(select(func.count()).select_from(RequirementRecheck)) == 0


def test_recheck_and_workflow_rollback_together(concurrent_recheck_db, monkeypatch):
    engine, (_, requirement_id, actor_id, change_hash) = concurrent_recheck_db
    from app.services.governance import workflow
    original = workflow.start_workflow

    def fail_after_creation(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic transaction failure")

    monkeypatch.setattr(workflow, "start_workflow", fail_after_creation)
    with Session(engine) as db:
        with pytest.raises(RuntimeError, match="synthetic"):
            create_recheck(db, db.get(Requirement, requirement_id), 4, change_hash, actor_id)
        db.rollback()
        assert db.scalar(select(func.count()).select_from(RequirementRecheck)) == 0
        assert db.scalar(select(func.count()).select_from(ReviewTask).where(
            ReviewTask.target_type == "requirement_recheck")) == 0
