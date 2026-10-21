"""Regression: anonymous legacy principals must not write an invalid actor id.

``AUTH_MODE=optional`` returns ``Principal(None, "legacy-system", ...)``.  Several API
paths used to persist ``int(principal.user_id or 0)`` into NOT NULL ``users.id`` foreign
keys (``background_jobs.created_by`` in particular), so the very first knowledge upload
in a demo deployment failed with ``ForeignKeyViolation``.  SQLite ignores foreign keys
unless asked, which is why the whole test suite stayed green; this module turns
``PRAGMA foreign_keys=ON`` on for the dedicated session.
"""

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import BackgroundJob, Project, User
from app.services.auth.actors import LEGACY_SYSTEM_USERNAME
from app.services.auth.dependencies import Principal
from app.services.task_queue.idempotency import create_or_get_job
from app.services.task_queue.submission import submit_project_job


def _legacy_principal() -> Principal:
    return Principal(None, LEGACY_SYSTEM_USERNAME, "Legacy development mode", True)


@pytest.fixture()
def fk_session() -> Session:
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record) -> None:  # pragma: no cover - setup only
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_legacy_job_actor_is_materialised_once(fk_session: Session) -> None:
    job, deduplicated = create_or_get_job(
        fk_session,
        job_type="knowledge_ingestion",
        institution_id=None,
        project_id=None,
        created_by=0,
        idempotency_key="legacy-actor-once",
        payload_summary={"file_name": "制度.md"},
    )
    assert deduplicated is False
    fk_session.commit()
    fk_session.refresh(job)

    assert job.created_by
    user = fk_session.get(User, job.created_by)
    assert user is not None and user.username == LEGACY_SYSTEM_USERNAME
    system_user_id = user.id

    repeated, deduplicated_again = create_or_get_job(
        fk_session,
        job_type="knowledge_ingestion",
        institution_id=None,
        project_id=None,
        created_by=0,
        idempotency_key="legacy-actor-once",
        payload_summary={"file_name": "制度.md"},
    )
    assert deduplicated_again is True and repeated.id == job.id
    assert fk_session.scalar(
        select(func.count()).select_from(User).where(User.username == LEGACY_SYSTEM_USERNAME)
    ) == 1
    assert system_user_id == fk_session.scalar(select(User.id).where(User.username == LEGACY_SYSTEM_USERNAME))


def test_submit_project_job_with_legacy_principal_completes(fk_session: Session) -> None:
    project = Project(name="legacy 演示项目")
    fk_session.add(project)
    fk_session.commit()

    executed: list[int] = []

    def handler(session: Session, job: BackgroundJob):
        executed.append(job.id)
        return {"ok": True}

    job = submit_project_job(
        fk_session,
        project,
        _legacy_principal(),
        job_type="metadata_sync",
        payload={"datasource_id": 1},
        handler=handler,
    )

    assert executed == [job.id]
    assert job.status == "completed"
    actor = fk_session.get(User, job.created_by)
    assert actor is not None and actor.username == LEGACY_SYSTEM_USERNAME
    assert job.created_by != 0
