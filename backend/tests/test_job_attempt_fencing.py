"""N02/BF02 + N11: unique per-attempt fencing, lease renewal and reliable re-delivery.

The review found two gaps beyond the original B07 fix:

* BF02/N02 - ``_lease_owner()`` returned ``hostname:pid``, which every attempt inside one process
  shares.  A stale attempt that outlived its lease therefore passed the terminal fence of its
  successor and overwrote the newer owner's state (and cleared its lease).
* N11 - the job row was committed *before* the broker publish.  When the publish failed the job
  stayed ``queued`` with no delivery marker, so nothing could tell "never sent" from "sent".

These tests exercise the real queue paths (``_execute`` / ``execute_existing``) rather than
re-implementing the SQL, plus the compensating dispatcher with a fake broker.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import BackgroundJob, User
from app.services.task_queue.celery import CeleryTaskQueue
from app.services.task_queue.inline import (
    JOB_LEASE_SECONDS,
    InlineTaskQueue,
    _claim_job,
    _lease_owner,
    _renew_lease,
)


@pytest.fixture()
def env(tmp_path):
    url = "sqlite:///" + (tmp_path / "fencing.db").as_posix()
    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=None)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        user = User(username="n02_user", display_name="N02", status="active")
        db.add(user)
        db.commit()
        user_id = int(user.id)
    yield factory, user_id
    engine.dispose()


def _job(db, user_id: int, *, key: str, created_at=None) -> BackgroundJob:
    job = BackgroundJob(idempotency_key=key, job_type="n02_probe", status="queued",
                        created_by=user_id, payload_summary_json={}, result_summary_json={})
    if created_at is not None:
        job.created_at = created_at
    db.add(job)
    db.commit()
    return job


# --------------------------------------------------------------------------- N02 / BF02

def test_every_claim_gets_a_unique_attempt_token() -> None:
    owners = {_lease_owner() for _ in range(50)}
    assert len(owners) == 50, "each attempt must be individually identifiable (BF02)"
    assert all(owner.count(":") >= 2 for owner in owners), owners.pop()


def test_a_stale_attempt_cannot_overwrite_its_successor(env):
    """BF02 reproduction: same process, old attempt's lease expires, successor takes over."""
    factory, user_id = env
    events: list[str] = []
    old_started = threading.Event()
    release_old = threading.Event()

    with factory() as db:
        job = _job(db, user_id, key="n02-stale")
        job_id = job.id

    def old_handler(db, job) -> dict:
        events.append("old-started")
        old_started.set()
        release_old.wait(30)
        events.append("old-finished")
        return {"success_count": 1, "failed_count": 0, "marker": "old"}

    def new_handler(db, job) -> dict:
        events.append("new-side-effect")
        return {"success_count": 1, "failed_count": 0, "marker": "new"}

    def run_old() -> None:
        with factory() as db:
            InlineTaskQueue().execute_existing(db, db.get(BackgroundJob, job_id), old_handler)

    thread = threading.Thread(target=run_old)
    thread.start()
    assert old_started.wait(30), "the old attempt never started"

    # The old attempt's lease expires while it is still running (no heartbeat in this window).
    with factory() as db:
        row = db.get(BackgroundJob, job_id)
        old_owner = row.lease_owner
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=5)
        db.commit()

    # A second consumer takes the job over in the same process and finishes it.
    with factory() as db:
        InlineTaskQueue().execute_existing(db, db.get(BackgroundJob, job_id), new_handler)
        successor = db.get(BackgroundJob, job_id)
        successor_owner = successor.lease_owner
        assert successor.status == "completed"

    release_old.set()
    thread.join(timeout=30)

    with factory() as db:
        final = db.get(BackgroundJob, job_id)
        assert old_owner != successor_owner, "each attempt must have its own owner token"
        assert final.status == "completed", "the stale attempt must not change the terminal state"
        assert final.result_summary_json.get("marker") == "new", "the old result must be rejected"
        assert events.index("new-side-effect") < events.index("old-finished")


def _lease_from_db(db, job_id: int):
    """Read the lease straight from the database (the session keeps stale attribute values
    because ``expire_on_commit=False``)."""
    return db.scalar(select(BackgroundJob.lease_expires_at).where(BackgroundJob.id == job_id))


def test_renew_lease_only_extends_for_the_current_owner(env):
    factory, user_id = env
    with factory() as db:
        job = _job(db, user_id, key="n02-renew")
        assert _claim_job(db, job, owner="attempt-1", lease_seconds=30) is True
        # Wrong owner may not extend the lease.
        assert _renew_lease(db, job.id, owner="attempt-2", lease_seconds=600) is False
        before = _lease_from_db(db, job.id)
        assert _renew_lease(db, job.id, owner="attempt-1", lease_seconds=600) is True
        after = _lease_from_db(db, job.id)
        assert after > before, "the current owner must be able to extend its lease"


def test_renew_lease_stops_once_the_attempt_lost_the_job(env):
    factory, user_id = env
    with factory() as db:
        job = _job(db, user_id, key="n02-lost")
        assert _claim_job(db, job, owner="attempt-1", lease_seconds=5) is True
        row = db.get(BackgroundJob, job.id)
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=5)
        db.commit()
        # Successor takes over.
        assert _claim_job(db, db.get(BackgroundJob, job.id), owner="attempt-2") is True
        # The old attempt can no longer renew, which is how it learns it lost ownership.
        assert _renew_lease(db, job.id, owner="attempt-1", lease_seconds=600) is False
        assert _renew_lease(db, job.id, owner="attempt-2", lease_seconds=600) is True


def test_a_finished_job_is_never_renewed(env):
    factory, user_id = env
    with factory() as db:
        job = _job(db, user_id, key="n02-done")
        InlineTaskQueue().execute_existing(db, job, lambda *_: {"success_count": 1, "failed_count": 0})
        assert db.get(BackgroundJob, job.id).status == "completed"
        assert _renew_lease(db, job.id, owner=_lease_owner()) is False


# --------------------------------------------------------------------------- N11

class _FakeCelery:
    class _Result:
        def __init__(self, task_id): self.id = task_id

    class _Control:
        def __init__(self): self.revocations = []
        def revoke(self, task_id, terminate=False): self.revocations.append((task_id, terminate))

    def __init__(self, *, fail_times: int = 0):
        self.calls: list = []
        self.control = self._Control()
        self.fail_times = fail_times

    def send_task(self, name, args):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("broker unavailable")
        self.calls.append((name, args))
        return self._Result(f"celery-{len(self.calls)}")


def test_a_failed_publish_leaves_the_job_undelivered_and_recoverable(env):
    factory, user_id = env
    # Enqueue explicitly so the publish failure is observable on the durable row.
    with factory() as db:
        fake = _FakeCelery(fail_times=1)
        queue = CeleryTaskQueue(fake)
        from app.services.task_queue.idempotency import create_or_get_job

        created, deduplicated = create_or_get_job(
            db, job_type="metadata_sync", institution_id=None, project_id=None,
            created_by=user_id, idempotency_key="n11-fail", payload_summary={},
        )
        assert deduplicated is False
        with pytest.raises(RuntimeError):
            queue._publish(db, created)
        db.rollback()
        stored = db.get(BackgroundJob, created.id)
        assert stored.status == "queued"
        assert stored.dispatched_at is None, "a failed publish must not look delivered"
        assert stored.celery_task_id is None
        job_id = stored.id

    # The compensating dispatcher finds it and publishes it.
    with factory() as db:
        row = db.get(BackgroundJob, job_id)
        row.created_at = datetime.now(UTC) - timedelta(seconds=600)
        db.commit()
        fake2 = _FakeCelery()
        report = CeleryTaskQueue(fake2).dispatch_undelivered(db)
        assert report["candidates"] == 1, report
        assert report["published"] == 1, report
        assert report["failed"] == []
        recovered = db.get(BackgroundJob, job_id)
        assert recovered.dispatched_at is not None
        assert recovered.celery_task_id == "celery-1"
        assert fake2.calls == [("app.workers.execute_background_job", [job_id])]


def test_dispatch_undelivered_ignores_delivered_and_running_jobs(env):
    factory, user_id = env
    with factory() as db:
        delivered = _job(db, user_id, key="n11-delivered", created_at=datetime.now(UTC) - timedelta(seconds=600))
        delivered.dispatched_at = datetime.now(UTC)
        running = _job(db, user_id, key="n11-running", created_at=datetime.now(UTC) - timedelta(seconds=600))
        running.status = "running"
        fresh = _job(db, user_id, key="n11-fresh")   # inside the grace window
        db.commit()

        fake = _FakeCelery()
        report = CeleryTaskQueue(fake).dispatch_undelivered(db)
    assert report["candidates"] == 0, report
    assert fake.calls == []


def test_dispatch_undelivered_reports_a_failing_publish_without_aborting(env):
    factory, user_id = env
    with factory() as db:
        for key in ("n11-a", "n11-b"):
            _job(db, user_id, key=key, created_at=datetime.now(UTC) - timedelta(seconds=600))
        fake = _FakeCelery(fail_times=99)
        report = CeleryTaskQueue(fake).dispatch_undelivered(db)
        assert report["candidates"] == 2
        assert report["published"] == 0
        assert len(report["failed"]) == 2, report
        assert all("broker unavailable" in item["error"] for item in report["failed"])
        assert all(db.get(BackgroundJob, item["job_id"]).dispatched_at is None for item in report["failed"])
