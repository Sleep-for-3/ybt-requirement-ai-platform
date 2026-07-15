from datetime import UTC, datetime
import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BackgroundJob
from app.services.governance.audit import redact_summary


class CeleryTaskQueue:
    def __init__(self, celery_app=None):
        if celery_app is None:
            from celery import Celery
            from app.core.settings import get_settings
            settings = get_settings()
            celery_app = Celery("ybt_governance", broker=settings.celery_broker_url, backend=settings.celery_result_backend)
        self.celery_app = celery_app

    def enqueue(self, db: Session, *, job_type: str, institution_id: int | None, project_id: int | None, created_by: int, idempotency_key: str, payload_summary: dict[str, Any], handler=None) -> BackgroundJob:
        scoped_key = hashlib.sha256(f"{institution_id or 0}:{project_id or 0}:{job_type}:{idempotency_key}".encode()).hexdigest()
        existing = db.scalar(select(BackgroundJob).where(BackgroundJob.idempotency_key == scoped_key))
        if existing:
            return existing
        job = BackgroundJob(institution_id=institution_id, project_id=project_id, idempotency_key=scoped_key, job_type=job_type, status="queued", progress=0, payload_summary_json=redact_summary(payload_summary), result_summary_json={}, created_by=created_by)
        db.add(job); db.commit(); db.refresh(job)
        self.celery_app.send_task("app.workers.execute_background_job", args=[job.id])
        return job

    def get_status(self, db: Session, job_id: int) -> BackgroundJob | None:
        return db.get(BackgroundJob, job_id)

    def cancel(self, db: Session, job: BackgroundJob) -> BackgroundJob:
        if job.status not in {"queued", "running"}: raise ValueError("Only queued or running jobs can be cancelled")
        job.status="cancelled";job.finished_at=datetime.now(UTC);db.commit();db.refresh(job);return job

    def retry(self, db: Session, job: BackgroundJob) -> BackgroundJob:
        if job.retry_count >= job.max_retries: raise ValueError("Maximum retry count reached")
        job.retry_count+=1;job.status="queued";job.error_message=None;job.finished_at=None;db.commit();self.celery_app.send_task("app.workers.execute_background_job",args=[job.id]);db.refresh(job);return job
