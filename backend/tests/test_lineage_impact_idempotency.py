"""Repeated script events include NULL version pairs and concurrent workers."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (ImpactAnalysis, Institution, Project, ReviewTask, ScriptChangeSet,
                        ScriptFile, ScriptFileVersion, StoredFile, User, WorkflowInstance)
from app.services.lineage.impact_analyzer import persist_change_impact
from app.services.lineage.version_diff import compare_sql_versions


DIFF = compare_sql_versions("insert into M(A,B) select A,B from S",
                            "insert into M(A) select A from S", dialect="sqlite")


@pytest.fixture
def event_db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'events.sqlite').as_posix()}",
                           connect_args={"timeout": 15})
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        institution = Institution(institution_code="synthetic", institution_name="Synthetic")
        db.add(institution); db.flush()
        project = Project(name="synthetic impact project", institution_id=institution.id)
        user = User(username="impact-author", display_name="Synthetic", password_hash="not-a-real-password")
        db.add_all([project, user]); db.flush()
        script = ScriptFile(project_id=project.id, relative_path="synthetic.sql",
                            file_name="synthetic.sql", file_type="sql", current_version_no=2)
        db.add(script); db.flush()
        for n in (1, 2):
            stored = StoredFile(institution_id=institution.id, project_id=project.id,
                storage_key=f"synthetic-{n}.sql", original_file_name=f"synthetic-{n}.sql",
                content_type="text/plain", byte_size=1, content_hash=str(n)*64, created_by=user.id)
            db.add(stored); db.flush()
            db.add(ScriptFileVersion(project_id=project.id, script_file_id=script.id, version_no=n,
                file_hash=str(n)*64, normalized_hash=str(n)*64, created_by=user.id,
                raw_content_storage_file_id=stored.id))
        db.commit()
        ids = script.id, user.id
    try:
        yield engine, ids
    finally:
        engine.dispose()


def inputs(db, script_id, event):
    script = db.get(ScriptFile, script_id)
    versions = list(db.scalars(select(ScriptFileVersion).where(
        ScriptFileVersion.script_file_id == script_id).order_by(ScriptFileVersion.version_no)))
    return dict(script_file=script, from_version=None if event == "added" else versions[0],
                to_version=None if event == "deleted" else versions[1], change_type=event)


@pytest.mark.parametrize("event", ["modified", "added", "deleted"])
def test_concurrent_replay_returns_original_event_without_duplicate_tasks(event_db, event):
    engine, (script_id, user_id) = event_db
    ready = Barrier(2)
    with Session(engine) as db:
        timestamp = db.get(ScriptFile, script_id).updated_at

    def trigger():
        with Session(engine) as db:
            args = inputs(db, script_id, event)
            ready.wait(timeout=10)
            change, impact = persist_change_impact(db, **args, diff=DIFF, created_by=user_id)
            result = change.id, impact.id
            db.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: trigger(), range(2)))
    assert results[0] == results[1]
    with Session(engine) as db:
        for model in (ScriptChangeSet, ImpactAnalysis, WorkflowInstance):
            assert db.scalar(select(func.count()).select_from(model)) == 1
        assert db.scalar(select(func.count()).select_from(ReviewTask)) == 3
        assert db.get(ScriptFile, script_id).updated_at == timestamp


def test_changed_replay_is_conflict_and_foreign_versions_are_rejected(event_db):
    engine, (script_id, user_id) = event_db
    with Session(engine) as db:
        args = inputs(db, script_id, "modified")
        persist_change_impact(db, **args, diff=DIFF, created_by=user_id)
        db.commit()
        with pytest.raises(HTTPException) as error:
            persist_change_impact(db, **args, diff=replace(DIFF, summary={"changed": True}), created_by=user_id)
        assert error.value.status_code == 409
        db.rollback()
        foreign = ScriptFileVersion(project_id=999, script_file_id=999, version_no=1)
        with pytest.raises(HTTPException) as error:
            persist_change_impact(db, **{**args, "to_version": foreign}, diff=DIFF, created_by=user_id)
        assert error.value.status_code == 404
        assert db.scalar(select(func.count()).select_from(ScriptChangeSet)) == 1


def test_event_workflow_failure_rolls_back_everything(event_db, monkeypatch):
    from app.services.governance import workflow
    engine, (script_id, user_id) = event_db
    original = workflow.start_workflow

    def fail_after_creation(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(workflow, "start_workflow", fail_after_creation)
    with Session(engine) as db:
        with pytest.raises(RuntimeError, match="synthetic"):
            persist_change_impact(db, **inputs(db, script_id, "modified"), diff=DIFF, created_by=user_id)
        db.rollback()
        for model in (ScriptChangeSet, ImpactAnalysis, WorkflowInstance, ReviewTask):
            assert db.scalar(select(func.count()).select_from(model)) == 0
