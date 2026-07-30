from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import BackgroundJob
from app.services.task_queue.idempotency import create_or_get_job


class CeleryTaskQueue:
    def __init__(self, celery_app=None):
        if celery_app is None:
            from celery import Celery
            from app.core.settings import get_settings
            settings = get_settings()
            celery_app = Celery("ybt_governance", broker=settings.celery_broker_url, backend=settings.celery_result_backend)
        self.celery_app = celery_app

    def enqueue(self, db: Session, *, job_type: str, institution_id: int | None, project_id: int | None, created_by: int, idempotency_key: str, payload_summary: dict[str, Any], handler=None) -> BackgroundJob:
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
        result = self.celery_app.send_task("app.workers.execute_background_job", args=[job.id])
        job.celery_task_id = getattr(result, "id", None)
        db.commit()
        db.refresh(job)
        return job

    def get_status(self, db: Session, job_id: int) -> BackgroundJob | None:
        return db.get(BackgroundJob, job_id)

    def cancel(self, db: Session, job: BackgroundJob) -> BackgroundJob:
        if job.status not in {"queued", "running"}: raise ValueError("Only queued or running jobs can be cancelled")
        if job.status == "queued" and job.celery_task_id:
            self.celery_app.control.revoke(job.celery_task_id, terminate=False)
        job.status="cancelled";job.finished_at=datetime.now(UTC);db.commit();db.refresh(job);return job

    def retry(self, db: Session, job: BackgroundJob) -> BackgroundJob:
        if job.status not in {"failed", "partially_completed", "cancelled"}: raise ValueError("Only failed, partially completed or cancelled jobs can be retried")
        if job.retry_count >= job.max_retries: raise ValueError("Maximum retry count reached")
        job.retry_count+=1;job.status="queued";job.error_message=None;job.finished_at=None;db.commit()
        result=self.celery_app.send_task("app.workers.execute_background_job",args=[job.id])
        job.celery_task_id=getattr(result,"id",None);db.commit();db.refresh(job);return job
