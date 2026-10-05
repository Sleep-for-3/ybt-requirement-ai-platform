from datetime import UTC, datetime, timedelta
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
        self._publish(db, job)
        return job

    def _publish(self, db: Session, job: BackgroundJob) -> bool:
        """N11: publish the durable job and record that delivery actually happened.

        The job row is committed before this call.  If the broker is unreachable the publish raises
        and ``dispatched_at`` stays NULL, so ``dispatch_undelivered`` can re-publish the job later
        instead of leaving it queued forever with no trace.  Re-publishing is safe: the worker
        claims the job atomically, so a duplicate message short-circuits in ``_execute``.
        """

        result = self.celery_app.send_task("app.workers.execute_background_job", args=[job.id])
        job.celery_task_id = getattr(result, "id", None)
        job.dispatched_at = datetime.now(UTC)
        db.commit()
        db.refresh(job)
        return True

    def dispatch_undelivered(self, db: Session, *, limit: int = 50) -> dict[str, Any]:
        """N11: compensating dispatcher for jobs committed but never published.

        Only ``queued`` jobs without a delivery marker are considered, so a running or finished job
        is never re-sent.  A publish failure is reported and counted instead of aborting the sweep.
        """

        from sqlalchemy import select

        stale_before = datetime.now(UTC) - timedelta(seconds=self.dispatch_grace_seconds)
        pending = list(db.scalars(
            select(BackgroundJob)
            .where(
                BackgroundJob.status == "queued",
                BackgroundJob.dispatched_at.is_(None),
                BackgroundJob.created_at < stale_before,
            )
            .order_by(BackgroundJob.id)
            .limit(limit)
        ))
        published = 0
        failed: list[dict[str, Any]] = []
        for job in pending:
            try:
                self._publish(db, job)
                published += 1
            except Exception as exc:  # noqa: BLE001 - one bad publish must not stop the sweep
                db.rollback()
                failed.append({"job_id": job.id, "error": type(exc).__name__ + ": " + str(exc)[:160]})
        return {"candidates": len(pending), "published": published, "failed": failed}

    def get_status(self, db: Session, job_id: int) -> BackgroundJob | None:
        return db.get(BackgroundJob, job_id)

    def cancel(self, db: Session, job: BackgroundJob) -> BackgroundJob:
        if job.status not in {"queued", "running"}: raise ValueError("Only queued or running jobs can be cancelled")
        if job.status == "queued" and job.celery_task_id:
            self.celery_app.control.revoke(job.celery_task_id, terminate=False)
        job.status="cancelled";job.finished_at=datetime.now(UTC);db.commit();db.refresh(job);return job
    # N11: a job committed but not yet published is only retried after this grace period, so a
    # publish that is merely slow does not race the compensating dispatcher.
    dispatch_grace_seconds = 60
    def retry(self, db: Session, job: BackgroundJob) -> BackgroundJob:
        if job.status not in {"failed", "partially_completed", "cancelled"}: raise ValueError("Only failed, partially completed or cancelled jobs can be retried")
        if job.retry_count >= job.max_retries: raise ValueError("Maximum retry count reached")
        job.retry_count+=1;job.status="queued";job.error_message=None;job.finished_at=None;db.commit()
        self._publish(db, job)
        return job
