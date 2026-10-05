import os
import socket
import threading
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.models import BackgroundJob
from app.services.governance.audit import redact_summary
from app.services.task_queue.base import JobHandler
from app.services.task_queue.idempotency import create_or_get_job


_handlers: dict[str, JobHandler] = {}


def register_job_handler(job_type: str, handler: JobHandler) -> None:
    _handlers[job_type] = handler


def _resolve_handler(job_type: str, handler: JobHandler | None = None) -> JobHandler | None:
    if handler is not None:
        register_job_handler(job_type, handler)
        return handler
    registered = _handlers.get(job_type)
    if registered is not None:
        return registered
    from app.services.task_queue.handlers import resolve_job_handler

    resolved = resolve_job_handler(job_type)
    if resolved is not None:
        register_job_handler(job_type, resolved)
    return resolved


# How long one worker may hold a job before another may take it over (B07).
JOB_LEASE_SECONDS = 900

# A job in one of these states may still be claimed; anything else is a duplicate consumer.
CLAIMABLE_STATUSES = ("queued", "partially_completed")


def _lease_owner() -> str:
    # BF02/N02: ``hostname:pid`` alone is shared by every attempt inside one process, so a stale
    # attempt that outlived its lease could pass the terminal fence of its successor (a retry or a
    # same-process takeover).  A per-claim token makes every attempt distinct; the fence compares
    # this exact string, so only the current owner may write.
    return f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:12]}"


def _renew_lease(db: Session, job_id: int, *, owner: str, lease_seconds: int = JOB_LEASE_SECONDS) -> bool:
    """BF02/N02: actively extend the lease while a handler is still running.

    Only the current owner may renew.  Once another runner has taken over (an expired lease was
    reclaimed) or the job reached a terminal state, the update matches nothing and the caller
    must treat this attempt as lost instead of pretending it still owns the job.
    """

    now = datetime.now(UTC)
    renewed = db.execute(
        update(BackgroundJob)
        .where(
            BackgroundJob.id == job_id,
            BackgroundJob.lease_owner == owner,
            BackgroundJob.status == "running",
        )
        .values(lease_expires_at=now + timedelta(seconds=lease_seconds))
        .execution_options(synchronize_session=False)
    ).rowcount
    db.commit()
    return renewed == 1


def _start_lease_heartbeat(db: Session, job, *, owner: str, lost: threading.Event) -> threading.Event:
    """BF02/N02: keep the lease alive on a background thread while the handler runs.

    Returns a stop event.  When the renewal fails the attempt no longer owns the job, so the
    ``lost`` event is set and the caller skips its success write (the successor owns the
    outcome).  The heartbeat is best-effort: a failing beat must never kill the run itself.
    """

    stop = threading.Event()
    interval = max(JOB_LEASE_SECONDS // 3, 1)
    try:
        factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    except Exception:  # noqa: BLE001 - a session without a usable bind keeps the old behaviour
        return stop

    def loop() -> None:
        while not stop.wait(interval):
            try:
                with factory() as beat_db:
                    if not _renew_lease(beat_db, job.id, owner=owner):
                        lost.set()
                        return
            except Exception:  # noqa: BLE001 - a failed heartbeat is not a handler failure
                return

    threading.Thread(target=loop, daemon=True).start()
    return stop


def _institution_can_run(db: Session, institution_id: int | None) -> bool:
    """B02: background execution must respect the institution-state guard.

    Mirrors ``PermissionService._institution_is_active`` (a job without an institution keeps its
    previous behaviour) without needing a principal, since workers have none.
    """

    if institution_id is None:
        return True
    from app.models import Institution

    return db.scalar(select(Institution.status).where(Institution.id == institution_id)) == "active"


def _claim_job(db: Session, job: BackgroundJob, *, owner: str, lease_seconds: int = JOB_LEASE_SECONDS) -> bool:
    """Transition the job to running with a single conditional UPDATE.

    Exactly one consumer can win: the update only matches a queued/partially-completed job or a
    running job whose lease already expired (a crashed runner). A completed, cancelled or
    actively-leased job is never matched, so the handler is not executed twice.
    """

    now = datetime.now(UTC)
    claimed = db.execute(
        update(BackgroundJob)
        .where(
            BackgroundJob.id == job.id,
            or_(
                BackgroundJob.status.in_(CLAIMABLE_STATUSES),
                and_(
                    BackgroundJob.status == "running",
                    or_(BackgroundJob.lease_expires_at.is_(None),
                        BackgroundJob.lease_expires_at < now),
                ),
            ),
        )
        .values(status="running", progress=1, started_at=now,
                lease_owner=owner, lease_expires_at=now + timedelta(seconds=lease_seconds))
        .execution_options(synchronize_session=False)
    ).rowcount
    db.commit()
    if claimed != 1:
        return False
    db.refresh(job)
    return True


class InlineTaskQueue:
    def enqueue(self, db: Session, *, job_type: str, institution_id: int | None, project_id: int | None, created_by: int, idempotency_key: str, payload_summary: dict[str, Any], handler: JobHandler | None = None) -> BackgroundJob:
        job, deduplicated = create_or_get_job(
            db,
            job_type=job_type,
            institution_id=institution_id,
            project_id=project_id,
            created_by=created_by,
            idempotency_key=idempotency_key,
            payload_summary=payload_summary,
        )
        if deduplicated:
            return job
        return self._execute(db, job, _resolve_handler(job_type, handler))

    def get_status(self, db: Session, job_id: int) -> BackgroundJob | None:
        return db.get(BackgroundJob, job_id)

    def cancel(self, db: Session, job: BackgroundJob) -> BackgroundJob:
        if job.status not in {"queued", "running"}:
            raise ValueError("Only queued or running jobs can be cancelled")
        job.status = "cancelled"
        job.finished_at = datetime.now(UTC)
        db.commit()
        db.refresh(job)
        return job

    def retry(self, db: Session, job: BackgroundJob) -> BackgroundJob:
        if job.status not in {"failed", "partially_completed", "cancelled"}:
            raise ValueError("Only failed, partially completed or cancelled jobs can be retried")
        if job.retry_count >= job.max_retries:
            raise ValueError("Maximum retry count reached")
        job.retry_count += 1
        job.status = "queued"
        job.error_message = None
        job.finished_at = None
        db.commit()
        return self._execute(db, job, _resolve_handler(job.job_type))

    def execute_existing(self, db: Session, job: BackgroundJob, handler: JobHandler | None = None) -> BackgroundJob:
        return self._execute(db, job, _resolve_handler(job.job_type, handler))

    def _execute(self, db: Session, job: BackgroundJob, handler: JobHandler | None) -> BackgroundJob:
        if handler is None:
            job.status = "failed"
            job.error_message = "No worker handler is registered for this job type"
            job.finished_at = datetime.now(UTC)
            db.commit()
            db.refresh(job)
            return job
        # B02: a deactivated institution must also stop *background execution*, not just list and
        # direct-ID access. A job enqueued while the institution was active is refused here instead
        # of writing results for an institution that is no longer active. Jobs without an
        # institution keep their previous behaviour, matching the permission guard's semantics.
        if not _institution_can_run(db, job.institution_id):
            job.status = "cancelled"
            job.progress = 100
            job.error_message = "机构已停用，作业不予执行"[:2000]
            job.finished_at = datetime.now(UTC)
            db.commit()
            db.refresh(job)
            return job
        # B07: claim the job atomically before running anything. Only a queued, retried or
        # expired-lease job can be claimed, so a duplicate consumer (re-delivery, second worker,
        # or a run that already finished) short-circuits without executing the handler again.
        owner = _lease_owner()
        if not _claim_job(db, job, owner=owner):
            db.refresh(job)
            return job
        # BF02/N02: keep the lease alive while the handler runs.  If renewal ever fails another
        # attempt has taken over, so this one must not write state or claim success afterwards.
        lease_lost = threading.Event()
        stop_heartbeat = _start_lease_heartbeat(db, job, owner=owner, lost=lease_lost)
        try:
            result = handler(db, job)
            db.refresh(job)
            if lease_lost.is_set():
                # A newer owner took over; report its state instead of pretending this attempt ran.
                db.rollback()
                db.refresh(job)
                return job
            if job.status == "cancelled":
                job.result_summary_json = redact_summary(result)
                job.progress = min(job.progress, 99)
                db.commit()
                db.refresh(job)
                return job
            failed = int(result.get("failed_count", 0))
            succeeded = int(result.get("success_count", 0))
            job.status = "partially_completed" if failed and succeeded else "failed" if failed else "completed"
            job.progress = 100
            job.result_summary_json = redact_summary(result)
            job.error_message = None if job.status != "failed" else str(result.get("error", "All items failed"))[:2000]
        except Exception as exc:  # worker boundary records failure instead of leaking it through HTTP
            db.rollback()
            job = db.get(BackgroundJob, job.id)
            job.status = "failed"
            job.error_message = str(exc)[:2000]
            job.progress = 100
        finally:
            stop_heartbeat.set()
        # Fencing (B07/W10): only the runner that still holds the lease may record the terminal
        # state. A long run whose lease expired can already have been taken over by another worker;
        # that newer owner's state must not be overwritten by this stale runner, and the stale
        # runner must not clear the new owner's lease. The guarded UPDATE keeps the normal path
        # byte-for-byte identical while making the takeover safe.
        fenced = db.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == job.id, BackgroundJob.lease_owner == owner)
            .values(
                status=job.status,
                progress=job.progress,
                result_summary_json=job.result_summary_json,
                error_message=job.error_message,
                finished_at=datetime.now(UTC),
                lease_owner=None,
                lease_expires_at=None,
            )
        ).rowcount == 1
        if not fenced:
            # Lost the lease to a newer owner: report its state instead of overwriting it.
            db.rollback()
        db.commit()
        db.refresh(job)
        return job
