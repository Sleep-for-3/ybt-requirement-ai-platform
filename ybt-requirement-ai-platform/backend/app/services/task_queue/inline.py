from datetime import UTC, datetime
import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BackgroundJob
from app.services.governance.audit import redact_summary
from app.services.task_queue.base import JobHandler


_handlers: dict[str, JobHandler] = {}


def register_job_handler(job_type: str, handler: JobHandler) -> None:
    _handlers[job_type] = handler


class InlineTaskQueue:
    def enqueue(self, db: Session, *, job_type: str, institution_id: int | None, project_id: int | None, created_by: int, idempotency_key: str, payload_summary: dict[str, Any], handler: JobHandler | None = None) -> BackgroundJob:
        scoped_key = hashlib.sha256(f"{institution_id or 0}:{project_id or 0}:{job_type}:{idempotency_key}".encode()).hexdigest()
        existing = db.scalar(select(BackgroundJob).where(BackgroundJob.idempotency_key == scoped_key))
        if existing:
            return existing
        job = BackgroundJob(
            institution_id=institution_id,
            project_id=project_id,
            idempotency_key=scoped_key,
            job_type=job_type,
            status="queued",
            progress=0,
            payload_summary_json=redact_summary(payload_summary),
            result_summary_json={},
            created_by=created_by,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        if handler:
            register_job_handler(job_type, handler)
        return self._execute(db, job, handler or _handlers.get(job_type))

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
        return self._execute(db, job, _handlers.get(job.job_type))

    def execute_existing(self, db: Session, job: BackgroundJob, handler: JobHandler | None = None) -> BackgroundJob:
        return self._execute(db, job, handler or _handlers.get(job.job_type))

    def _execute(self, db: Session, job: BackgroundJob, handler: JobHandler | None) -> BackgroundJob:
        if handler is None:
            job.status = "failed"
            job.error_message = "No worker handler is registered for this job type"
            job.finished_at = datetime.now(UTC)
            db.commit()
            db.refresh(job)
            return job
        job.status = "running"
        job.progress = 1
        job.started_at = datetime.now(UTC)
        db.commit()
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
        db.commit()
        db.refresh(job)
        return job
