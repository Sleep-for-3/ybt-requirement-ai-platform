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
    _resolve_handler,
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


def _job(db, user_id: int, *, key: str, created_at=None, job_type: str = "n02_probe") -> BackgroundJob:
    job = BackgroundJob(idempotency_key=key, job_type=job_type, status="queued",
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
        # C03: the sweep's grace period is measured from the **attempt's own** queue time
        # (``queued_at``, falling back to ``created_at``), not from the original row creation.
        # Backdate the attempt queue time so this really is an "old, never-published attempt".
        old = datetime.now(UTC) - timedelta(seconds=600)
        row.queued_at = old
        row.created_at = old
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


# --------------------------------------------------------------------------- C03


def test_c03_a_retry_whose_publish_fails_is_still_recoverable(env):
    """C03 reproduction: retry clears the previous attempt's delivery marker and gets its own
    attempt queue time, so the compensating sweep can still find and publish it."""

    factory, user_id = env
    with factory() as db:
        fake = _FakeCelery()
        queue = CeleryTaskQueue(fake)
        job = _job(db, user_id, key="c03-retry",
                   created_at=datetime.now(UTC) - timedelta(seconds=6000))
        # A previously *successful* delivery (its message already ran and failed).
        job.status = "failed"
        job.dispatched_at = datetime.now(UTC) - timedelta(seconds=6000)
        job.celery_task_id = "synthetic-old-task"
        job.queued_at = datetime.now(UTC) - timedelta(seconds=6000)
        db.commit()
        job_id = job.id

    with factory() as db:
        broker_down = CeleryTaskQueue(_FakeCelery(fail_times=1))
        with pytest.raises(RuntimeError):
            broker_down.retry(db, db.get(BackgroundJob, job_id))
        db.rollback()
        after = db.get(BackgroundJob, job_id)
        assert after.status == "queued", after.status
        assert after.dispatched_at is None, (
            "a retried attempt must not inherit the previous attempt's delivery marker")
        assert after.celery_task_id is None, after.celery_task_id
        assert after.queued_at is not None, "the attempt needs its own queue time"

    # Broker recovers: the sweep must find the never-published attempt and publish it.
    with factory() as db:
        row = db.get(BackgroundJob, job_id)
        row.queued_at = datetime.now(UTC) - timedelta(seconds=600)
        db.commit()
        recovered = _FakeCelery()
        report = CeleryTaskQueue(recovered).dispatch_undelivered(db)
        assert report["candidates"] == 1, report
        assert report["published"] == 1, report
        assert db.get(BackgroundJob, job_id).dispatched_at is not None
        assert recovered.calls == [("app.workers.execute_background_job", [job_id])]


def test_c03_repeated_sweeps_do_not_publish_twice(env):
    factory, user_id = env
    with factory() as db:
        job = _job(db, user_id, key="c03-idem",
                   created_at=datetime.now(UTC) - timedelta(seconds=600))
        job.queued_at = datetime.now(UTC) - timedelta(seconds=600)
        db.commit()
        fake = _FakeCelery()
        queue = CeleryTaskQueue(fake)
        first = queue.dispatch_undelivered(db)
        second = queue.dispatch_undelivered(db)
    assert first["published"] == 1, first
    assert second["candidates"] == 0, second
    assert len(fake.calls) == 1, fake.calls


# --------------------------------------------------------------------------- C04


def test_c04_re_delivering_a_completed_job_keeps_its_history(env):
    """C04 reproduction: a completed job's institution deactivates, then a duplicate delivery
    arrives. The successful result must survive."""

    from app.models import Institution

    factory, user_id = env
    with factory() as db:
        institution = Institution(institution_code="C04", institution_name="C04",
                                  institution_type="bank", status="active")
        db.add(institution)
        db.commit()
        job = _job(db, user_id, key="c04-completed")
        job.institution_id = institution.id
        db.commit()
        job_id = job.id
        institution_id = institution.id

    def handler(db, job) -> dict:
        return {"success_count": 1, "failed_count": 0}

    with factory() as db:
        InlineTaskQueue().execute_existing(db, db.get(BackgroundJob, job_id), handler)
        done = db.get(BackgroundJob, job_id)
        assert done.status == "completed", done.status
        original = {
            "status": done.status,
            "progress": done.progress,
            "result": dict(done.result_summary_json or {}),
            "error": done.error_message,
            "finished_at": done.finished_at,
        }

    # The institution is deactivated *after* the job already succeeded.
    with factory() as db:
        db.get(Institution, institution_id).status = "disabled"
        db.commit()

    with factory() as db:
        InlineTaskQueue().execute_existing(db, db.get(BackgroundJob, job_id), handler)
        redelivered = db.get(BackgroundJob, job_id)
        assert redelivered.status == original["status"], redelivered.status
        assert redelivered.progress == original["progress"]
        assert dict(redelivered.result_summary_json or {}) == original["result"]
        assert redelivered.error_message == original["error"]
        assert redelivered.finished_at == original["finished_at"]


def test_c04_re_delivering_a_completed_job_without_a_handler_keeps_its_history(env):
    factory, user_id = env
    with factory() as db:
        # 先以**已注册**类型跑成一次，再把 job_type 改成**从未注册过**的类型。
        # 注意：execute_existing(..., handler) 会把 handler 写进模块级 _handlers，
        # 所以同一个 job_type 二次调用会解析到旧 handler，“无 handler”分支根本进不去。
        job = _job(db, user_id, key="c04-nohandler", job_type="c04_with_handler")
        db.commit()
        job_id = job.id

    with factory() as db:
        InlineTaskQueue().execute_existing(db, db.get(BackgroundJob, job_id),
                                           lambda db, job: {"success_count": 1, "failed_count": 0})
        done = db.get(BackgroundJob, job_id)
        assert done.status == "completed"
        before = (done.status, dict(done.result_summary_json or {}), done.error_message)

    with factory() as db:
        row = db.get(BackgroundJob, job_id)
        row.job_type = "c04_never_registered"
        db.commit()

    with factory() as db:
        # Duplicate delivery with no resolvable handler: must be a pure no-op.
        InlineTaskQueue().execute_existing(db, db.get(BackgroundJob, job_id), None)
        after = db.get(BackgroundJob, job_id)
        assert (after.status, dict(after.result_summary_json or {}), after.error_message) == before, (
            after.status, after.error_message)


def test_c04_terminal_states_are_never_rewritten(env):
    factory, user_id = env
    for status in ("completed", "failed", "cancelled"):
        with factory() as db:
            job = _job(db, user_id, key=f"c04-{status}", job_type="c04_never_registered")
            # 该类型从未被注册，因此 execute_existing(..., None) 必然走“无 handler”分支。
            assert _resolve_handler(job.job_type) is None
            job.status = status
            job.progress = 100
            job.result_summary_json = {"success_count": 1, "marker": status}
            job.error_message = f"err-{status}"
            job.finished_at = datetime.now(UTC) - timedelta(seconds=30)
            db.commit()
            job_id = job.id
            # SQLite 会丢掉 tzinfo，因此时间戳用“归一化到 UTC 的瞬间”比较，而不是 tz 属性。
            def _moment(value):
                if value is None:
                    return None
                return (value.replace(tzinfo=UTC) if value.tzinfo is None
                        else value.astimezone(UTC)).isoformat()

            snapshot = (job.status, job.progress, dict(job.result_summary_json),
                        job.error_message, _moment(job.finished_at))

        with factory() as db:
            InlineTaskQueue().execute_existing(db, db.get(BackgroundJob, job_id), None)
            row = db.get(BackgroundJob, job_id)
            assert (row.status, row.progress, dict(row.result_summary_json),
                    row.error_message, _moment(row.finished_at)) == snapshot, status


def test_c04_inactive_institution_still_stops_a_queued_job(env):
    """The guard must keep working for a job that has *not* run yet."""

    from app.models import Institution

    factory, user_id = env
    with factory() as db:
        institution = Institution(institution_code="C04B", institution_name="C04B",
                                  institution_type="bank", status="disabled")
        db.add(institution)
        db.commit()
        job = _job(db, user_id, key="c04-queued-inactive")
        job.institution_id = institution.id
        db.commit()
        job_id = job.id

    with factory() as db:
        InlineTaskQueue().execute_existing(db, db.get(BackgroundJob, job_id),
                                           lambda db, job: {"success_count": 1, "failed_count": 0})
        row = db.get(BackgroundJob, job_id)
        assert row.status == "cancelled", row.status
        assert row.error_message and "停用" in row.error_message


# --------------------------------------------------------------------------- C05


def test_c05_a_transient_renewal_error_does_not_kill_the_heartbeat(env, monkeypatch):
    """C05 reproduction: one renewal raises, the beat must recover instead of exiting silently."""

    from app.services.task_queue import inline as inline_module

    factory, user_id = env
    with factory() as db:
        job = _job(db, user_id, key="c05-transient")
        job.status = "running"
        job.lease_owner = "owner-c05"
        db.commit()
        job_id = job.id

    calls = {"count": 0}
    real_renew = inline_module._renew_lease

    def flaky_renew(db, job_id_arg, *, owner, lease_seconds=inline_module.JOB_LEASE_SECONDS):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("synthetic transient db error")
        return real_renew(db, job_id_arg, owner=owner, lease_seconds=lease_seconds)

    monkeypatch.setattr(inline_module, "_renew_lease", flaky_renew)
    monkeypatch.setattr(inline_module, "JOB_LEASE_SECONDS", 1)

    lost = threading.Event()
    with factory() as db:
        stop = inline_module._start_lease_heartbeat(db, job_id, owner="owner-c05", lost=lost)
    try:
        # interval = max(lease//3, 1) = 1s; two beats prove recovery after the first failure.
        deadline = datetime.now(UTC) + timedelta(seconds=12)
        while calls["count"] < 2 and datetime.now(UTC) < deadline:
            threading.Event().wait(0.2)
        assert calls["count"] >= 2, f"heartbeat stopped after the transient error: {calls}"
        assert lost.is_set() is False, "a transient error must not signal lease loss"
    finally:
        stop.set()


def test_c05_sustained_renewal_failure_signals_lease_loss(env, monkeypatch):
    from app.services.task_queue import inline as inline_module

    factory, user_id = env
    with factory() as db:
        job = _job(db, user_id, key="c05-sustained")
        job.status = "running"
        job.lease_owner = "owner-c05b"
        db.commit()
        job_id = job.id

    def always_fails(db, job_id_arg, *, owner, lease_seconds=inline_module.JOB_LEASE_SECONDS):
        raise RuntimeError("synthetic persistent db error")

    monkeypatch.setattr(inline_module, "_renew_lease", always_fails)
    monkeypatch.setattr(inline_module, "JOB_LEASE_SECONDS", 1)

    lost = threading.Event()
    with factory() as db:
        stop = inline_module._start_lease_heartbeat(db, job_id, owner="owner-c05b", lost=lost)
    try:
        assert lost.wait(15) is True, "a sustained renewal failure must be visible as lease loss"
    finally:
        stop.set()


def test_c05_lease_loss_prevents_the_stale_attempt_from_writing(env, monkeypatch):
    """A heartbeat that lost the lease must stop this attempt from claiming success."""

    from app.services.task_queue import inline as inline_module

    factory, user_id = env
    started = threading.Event()
    release = threading.Event()
    with factory() as db:
        job = _job(db, user_id, key="c05-nowrite")
        db.commit()
        job_id = job.id

    def handler(db, job) -> dict:
        started.set()
        release.wait(30)
        return {"success_count": 1, "failed_count": 0, "marker": "stale"}

    def run() -> None:
        with factory() as db:
            InlineTaskQueue().execute_existing(db, db.get(BackgroundJob, job_id), handler)

    monkeypatch.setattr(inline_module, "JOB_LEASE_SECONDS", 1)
    thread = threading.Thread(target=run)
    thread.start()
    assert started.wait(30)

    # While the handler runs, a successor takes the job over (lease expired).
    with factory() as db:
        row = db.get(BackgroundJob, job_id)
        row.lease_owner = "successor-owner"
        row.status = "running"
        row.lease_expires_at = datetime.now(UTC) + timedelta(seconds=600)
        db.commit()

    # Wait for the heartbeat to notice it no longer owns the job.
    deadline = datetime.now(UTC) + timedelta(seconds=15)
    while datetime.now(UTC) < deadline:
        with factory() as db:
            if db.get(BackgroundJob, job_id).lease_owner == "successor-owner":
                break
        threading.Event().wait(0.2)

    release.set()
    thread.join(timeout=30)

    with factory() as db:
        final = db.get(BackgroundJob, job_id)
        assert final.lease_owner == "successor-owner", final.lease_owner
        assert dict(final.result_summary_json or {}).get("marker") != "stale", (
            "a stale attempt must not write its result", final.result_summary_json)
