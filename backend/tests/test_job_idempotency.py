"""W05 / B07: a durable job must execute its handler exactly once per legitimate run.

The original defect: the worker entry skipped only missing/cancelled jobs and then set
``status='running'`` and called the handler, so re-delivering the same job (or delivering it to
two workers) executed the business handler twice. Enqueue idempotency prevents duplicate
submission, not duplicate consumption.

These tests cover the real risks: a duplicate consumer of a finished job, two concurrent
consumers of the same queued job, recovery of a crashed runner via an expired lease, a live
lease blocking a second consumer, and the retry path staying usable.
"""
from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import BackgroundJob, User
from app.services.task_queue.inline import JOB_LEASE_SECONDS, InlineTaskQueue, _claim_job


@pytest.fixture()
def env(tmp_path):
    url = "sqlite:///" + (tmp_path / "jobs.db").as_posix()
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        user = User(username="job_user", display_name="Job", status="active")
        db.add(user)
        db.commit()
        user_id = int(user.id)
    yield factory, user_id
    engine.dispose()


def _job(db, user_id: int, *, key: str = "job-key-1", status: str = "queued",
         lease_owner: str | None = None, lease_expires_at=None) -> BackgroundJob:
    job = BackgroundJob(idempotency_key=key, job_type="w05_probe", status=status,
                        created_by=user_id, payload_summary_json={},
                        lease_owner=lease_owner, lease_expires_at=lease_expires_at)
    db.add(job)
    db.commit()
    return job


def _handler(calls: list, *, fail: bool = False):
    def handler(db, job) -> dict:
        calls.append(job.id)
        if fail:
            raise RuntimeError("handler exploded")
        return {"success_count": 1, "failed_count": 0}

    return handler


def test_a_duplicate_consumer_of_a_finished_job_does_not_run_the_handler(env):
    factory, user_id = env
    calls: list = []
    with factory() as db:
        job = _job(db, user_id)
        queue = InlineTaskQueue()
        queue.execute_existing(db, job, _handler(calls))
        assert calls == [job.id]
        assert db.get(BackgroundJob, job.id).status == "completed"

        # Re-delivery of the same job (a second Celery message or a resumed worker).
        queue.execute_existing(db, job, _handler(calls))
        assert calls == [job.id], "a completed job must not run its handler again"
        stored = db.get(BackgroundJob, job.id)
        assert stored.status == "completed"
        assert stored.lease_owner is None and stored.lease_expires_at is None


def test_a_cancelled_job_is_not_executed(env):
    factory, user_id = env
    calls: list = []
    with factory() as db:
        job = _job(db, user_id, status="cancelled")
        InlineTaskQueue().execute_existing(db, job, _handler(calls))
    assert calls == []
    with factory() as db:
        assert db.get(BackgroundJob, job.id).status == "cancelled"


def test_a_live_lease_blocks_a_second_consumer(env):
    factory, user_id = env
    calls: list = []
    with factory() as db:
        job = _job(db, user_id, status="running", lease_owner="other-worker",
                   lease_expires_at=datetime.now(UTC) + timedelta(seconds=JOB_LEASE_SECONDS))
        InlineTaskQueue().execute_existing(db, job, _handler(calls))
        stored = db.get(BackgroundJob, job.id)
    assert calls == [], "a job leased by another worker must not be executed here"
    assert stored.status == "running" and stored.lease_owner == "other-worker"


def test_an_expired_lease_is_recovered_by_the_next_consumer(env):
    factory, user_id = env
    calls: list = []
    with factory() as db:
        job = _job(db, user_id, status="running", lease_owner="dead-worker",
                   lease_expires_at=datetime.now(UTC) - timedelta(seconds=5))
        InlineTaskQueue().execute_existing(db, job, _handler(calls))
    assert calls == [job.id], "a crashed runner's job must be recoverable"
    with factory() as db:
        assert db.get(BackgroundJob, job.id).status == "completed"


def test_two_concurrent_consumers_run_the_handler_once(env):
    factory, user_id = env
    calls: list = []
    with factory() as db:
        job = _job(db, user_id)
        job_id = job.id

    barrier = threading.Barrier(2)

    def consume() -> None:
        barrier.wait()
        with factory() as db:
            row = db.get(BackgroundJob, job_id)
            InlineTaskQueue().execute_existing(db, row, _handler(calls))

    threads = [threading.Thread(target=consume) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(calls) == 1, f"the handler must run exactly once, ran {len(calls)} times"


def test_the_atomic_claim_admits_exactly_one_winner(env):
    factory, user_id = env
    with factory() as db:
        job = _job(db, user_id)
        assert _claim_job(db, job, owner="worker-a") is True
        assert _claim_job(db, job, owner="worker-b") is False
        stored = db.get(BackgroundJob, job.id)
        assert stored.status == "running" and stored.lease_owner == "worker-a"
        assert stored.lease_expires_at is not None


def test_a_failed_job_can_be_retried_and_runs_again(env):
    factory, user_id = env
    calls: list = []
    with factory() as db:
        job = _job(db, user_id)
        InlineTaskQueue().execute_existing(db, job, _handler(calls, fail=True))
        stored = db.get(BackgroundJob, job.id)
        assert stored.status == "failed"
        assert stored.error_message and "handler exploded" in stored.error_message
        assert stored.lease_owner is None, "a failed run must release its lease"

        # Retry after the underlying fault is fixed: registering the healthy handler first.
        from app.services.task_queue.inline import register_job_handler

        register_job_handler("w05_probe", _handler(calls))
        retried = InlineTaskQueue().retry(db, stored)
        assert retried.status == "completed", retried.error_message
    assert calls == [job.id, job.id], "an explicit retry is a new legitimate run"
