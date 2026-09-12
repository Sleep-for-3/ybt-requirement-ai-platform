from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Iterator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models import AuditLog, BackgroundJob, CodeRepository, Institution, Project, User
from app.services.lineage.monitoring import (
    configure_repository_monitor,
    repository_monitor_status,
    run_due_repository_monitors,
)


class CapturingQueue:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def enqueue(self, db: Session, **kwargs) -> BackgroundJob:
        self.calls.append(kwargs)
        job = BackgroundJob(
            institution_id=kwargs["institution_id"],
            project_id=kwargs["project_id"],
            idempotency_key=kwargs["idempotency_key"],
            job_type=kwargs["job_type"],
            status="queued",
            progress=0,
            payload_summary_json=kwargs["payload_summary"],
            result_summary_json={},
            created_by=kwargs["created_by"],
        )
        db.add(job)
        db.flush()
        return job


def test_due_monitor_enqueues_existing_sync_pipeline_once(db_session: Session) -> None:
    repository, user = _repository(db_session)
    start = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)
    configure_repository_monitor(
        repository,
        enabled=True,
        poll_interval_minutes=30,
        now=start,
    )
    db_session.commit()
    queue = CapturingQueue()

    result = run_due_repository_monitors(
        db_session,
        now=start + timedelta(minutes=30),
        actor_user_id=user.id,
        queue=queue,
    )

    db_session.refresh(repository)
    assert result.checked_count == 1
    assert result.enqueued_count == 1
    assert result.failed_count == 0
    assert len(queue.calls) == 1
    assert queue.calls[0]["job_type"] == "script_repository_sync"
    assert queue.calls[0]["handler"].__name__ == "script_repository_sync_handler"
    assert queue.calls[0]["payload_summary"]["trigger_type"] == "scheduled_poll"
    assert repository.last_monitor_job_id == result.job_ids[0]
    assert _as_utc(repository.next_poll_at) == start + timedelta(minutes=60)
    assert db_session.scalar(select(AuditLog).where(
        AuditLog.action == "lineage_monitor_poll",
        AuditLog.resource_id == str(repository.id),
    )) is not None

    second = run_due_repository_monitors(
        db_session,
        now=start + timedelta(minutes=30),
        actor_user_id=user.id,
        queue=queue,
    )
    assert second.checked_count == 0
    assert len(queue.calls) == 1


def test_monitor_skips_an_active_scoped_job(db_session: Session) -> None:
    repository, user = _repository(db_session)
    now = datetime(2026, 9, 10, 2, 0, tzinfo=UTC)
    configure_repository_monitor(
        repository,
        enabled=True,
        poll_interval_minutes=15,
        run_immediately=True,
        now=now,
    )
    job = BackgroundJob(
        institution_id=repository.institution_id,
        project_id=repository.project_id,
        idempotency_key="active-monitor-job",
        job_type="script_repository_sync",
        status="running",
        progress=10,
        payload_summary_json={"repository_id": repository.id, "trigger_type": "scheduled_poll"},
        result_summary_json={},
        created_by=user.id,
    )
    db_session.add(job)
    db_session.flush()
    repository.last_monitor_job_id = job.id
    db_session.commit()
    queue = CapturingQueue()

    result = run_due_repository_monitors(db_session, now=now, queue=queue)

    assert result.checked_count == 1
    assert result.enqueued_count == 0
    assert result.skipped_active_count == 1
    assert not queue.calls
    db_session.refresh(repository)
    assert _as_utc(repository.next_poll_at) == now + timedelta(minutes=1)


def test_monitor_status_hides_a_cross_project_job_reference(db_session: Session) -> None:
    repository, user = _repository(db_session)
    other_project = Project(name="other monitor project", institution_id=repository.institution_id)
    db_session.add(other_project)
    db_session.flush()
    foreign_job = BackgroundJob(
        institution_id=repository.institution_id,
        project_id=other_project.id,
        idempotency_key="foreign-monitor-job",
        job_type="script_repository_sync",
        status="failed",
        progress=100,
        payload_summary_json={"repository_id": repository.id},
        result_summary_json={},
        error_message="must stay hidden",
        created_by=user.id,
    )
    db_session.add(foreign_job)
    db_session.flush()
    repository.last_monitor_job_id = foreign_job.id

    status = repository_monitor_status(db_session, repository)

    assert status["last_job_id"] is None
    assert status["last_job_status"] is None
    assert status["last_error"] is None


def test_monitor_configuration_api_is_project_scoped() -> None:
    with _api_client() as (client, factory):
        with factory() as db:
            repository, _ = _repository(db)
            repository_id = repository.id
            project_id = repository.project_id
            db.commit()

        response = client.patch(
            f"/api/code-repositories/{repository_id}/monitor",
            json={"enabled": True, "poll_interval_minutes": 45},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["project_id"] == project_id
        assert payload["monitor"]["enabled"] is True
        assert payload["monitor"]["poll_interval_minutes"] == 45
        assert payload["monitor"]["next_poll_at"]
        assert payload["submitted_job"] is None

        invalid = client.patch(
            f"/api/code-repositories/{repository_id}/monitor",
            json={"enabled": True, "poll_interval_minutes": 1},
        )
        assert invalid.status_code == 422
        missing = client.patch(
            "/api/code-repositories/999999/monitor",
            json={"enabled": True, "poll_interval_minutes": 45},
        )
        assert missing.status_code == 404


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _repository(db: Session) -> tuple[CodeRepository, User]:
    institution = Institution(
        institution_code=f"monitor-bank-{len(db.identity_map)}",
        institution_name="血缘监控测试机构",
    )
    user = User(username=f"monitor-user-{len(db.identity_map)}", status="active")
    db.add_all([institution, user])
    db.flush()
    project = Project(name="血缘监控项目", institution_id=institution.id)
    db.add(project)
    db.flush()
    repository = CodeRepository(
        institution_id=institution.id,
        project_id=project.id,
        repository_name="受控脚本仓库",
        repository_type="git_repository",
        repository_url="https://github.com/example/lineage-scripts.git",
        default_branch="main",
        enabled=True,
        created_by=user.id,
    )
    db.add(repository)
    db.flush()
    return repository, user


@contextmanager
def _api_client() -> Iterator[tuple[TestClient, sessionmaker]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)

    def override() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
