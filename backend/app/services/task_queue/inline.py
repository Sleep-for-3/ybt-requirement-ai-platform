import os
import socket
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session

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
    return f"{socket.gethostname()}:{os.getpid()}"


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
        # B07: claim the job atomically before running anything. Only a queued, retried or
        # expired-lease job can be claimed, so a duplicate consumer (re-delivery, second worker,
        # or a run that already finished) short-circuits without executing the handler again.
        owner = _lease_owner()
        if not _claim_job(db, job, owner=owner):
            db.refresh(job)
            return job
        try:
            result = handler(db, job)
            db.refresh(job)
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
        job.finished_at = datetime.now(UTC)
        # The run is over: drop the lease so a legitimate retry can claim it again while a
        # finished job can never be claimed a second time.
        job.lease_owner = None
        job.lease_expires_at = None
        db.commit()
        db.refresh(job)
        return job
