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

    def stage(self, db: Session, *, job_type: str, institution_id: int | None, project_id: int | None, created_by: int, idempotency_key: str, payload_summary: dict[str, Any]) -> tuple[BackgroundJob, bool]:
        """Insert the job row into the caller's transaction without publishing it.

        Outbox semantics: the row is flushed but not committed, so a caller can make
        "this job exists" and its own state change atomic. The caller commits and then
        calls :meth:`dispatch_staged`; a crash in between leaves ``dispatched_at`` NULL and
        :meth:`dispatch_undelivered` re-publishes it later.
        """
        return create_or_get_job(
            db,
            job_type=job_type,
            institution_id=institution_id,
            project_id=project_id,
            created_by=created_by,
            idempotency_key=idempotency_key,
            payload_summary=payload_summary,
            commit=False,
        )

    def dispatch_staged(self, db: Session, job: BackgroundJob, handler=None) -> BackgroundJob:
        self._publish(db, job)
        return job

    def _publish(self, db: Session, job: BackgroundJob) -> bool:
        """N11: publish the durable job and record that delivery actually happened.
        The job row is committed before this call.  If the broker is unreachable the publish raises
        and ``dispatched_at`` stays NULL, so ``dispatch_undelivered`` can re-publish the job later
        instead of leaving it queued forever with no trace.  Re-publishing is safe: the worker
        claims the job atomically, so a duplicate message short-circuits in ``_execute``.

        A deduplicated job is never re-published: another caller already owns delivering the row
        it won, and dispatching here would either double-send it or, if the *other* publisher is
        still in flight, mark an undelivered row as delivered.
        """
        if getattr(job, "submission_deduplicated", False):
            return False
        result = self.celery_app.send_task("app.workers.execute_background_job", args=[job.id])
        job.celery_task_id = getattr(result, "id", None)
        job.dispatched_at = datetime.now(UTC)
        db.commit()
        db.refresh(job)
        return True

    def dispatch_undelivered(self, db: Session, *, limit: int = 50) -> dict[str, Any]:
        """N11: compensating dispatcher for jobs committed but never published.

        Two classes of job are recovered:

        * ``queued`` jobs without a delivery marker (the outbox case: the process died between
          committing the row and publishing it);
        * ``running`` jobs whose lease already expired — a worker (or its host) died mid-handler.
          Nothing re-publishes those, so without this sweep such a job stays ``running`` forever.
          Re-publishing is safe: ``_claim_job`` only takes over a running job whose lease expired,
          and the handler is expected to be idempotent per job row.

        A running job is re-published at most once per grace period (``dispatched_at`` is refreshed
        by :meth:`_publish`), so a permanently dead worker does not create a publish storm. A
        publish failure is reported and counted instead of aborting the sweep.
        """

        from sqlalchemy import and_, or_, select

        # C03: the grace period must belong to **this** dispatch attempt. For a fresh enqueue that is
        # ``created_at``; for a retry the job row is old, so ``queued_at`` is the attempt's own queue
        # time. Using only ``created_at`` (plus a stale ``dispatched_at``) is exactly what let a
        # retried, never-published job stay invisible to the sweep forever.
        now = datetime.now(UTC)
        stale_before = now - timedelta(seconds=self.dispatch_grace_seconds)
        attempt_queued_before = now - timedelta(seconds=self.retry_dispatch_grace_seconds)
        pending = list(db.scalars(
            select(BackgroundJob)
            .where(
                BackgroundJob.status == "queued",
                BackgroundJob.dispatched_at.is_(None),
                or_(
                    and_(BackgroundJob.queued_at.is_(None),
                         BackgroundJob.created_at < stale_before),
                    BackgroundJob.queued_at < attempt_queued_before,
                ),
            )
            .order_by(BackgroundJob.id)
            .limit(limit)
        ))
        # A running job only becomes a takeover candidate once its lease expired. Requiring a
        # recorded lease and start time keeps legacy/manually-inserted rows out of the sweep.
        stale_running = list(db.scalars(
            select(BackgroundJob)
            .where(
                BackgroundJob.status == "running",
                BackgroundJob.started_at.is_not(None),
                BackgroundJob.lease_expires_at.is_not(None),
                BackgroundJob.lease_expires_at < now,
                or_(
                    BackgroundJob.dispatched_at.is_(None),
                    BackgroundJob.dispatched_at < stale_before,
                ),
            )
            .order_by(BackgroundJob.id)
            .limit(limit)
        ))
        published = 0
        failed: list[dict[str, Any]] = []
        for job in [*pending, *stale_running]:
            try:
                self._publish(db, job)
                published += 1
            except Exception as exc:  # noqa: BLE001 - one bad publish must not stop the sweep
                db.rollback()
                failed.append({"job_id": job.id, "error": type(exc).__name__ + ": " + str(exc)[:160]})
        return {
            "candidates": len(pending),
            "published": published,
            "stale_running_candidates": len(stale_running),
            "stale_running_published": [
                job.id for job in stale_running if job.id not in
                {entry["job_id"] for entry in failed}
            ],
            "failed": failed,
        }

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
    # C03: how long a *freshly queued* attempt may wait before the compensating dispatcher may
    # re-publish it. The grace period is measured from the attempt's own queue time, not from
    # ``created_at`` (which for a retry is the original job's creation).
    retry_dispatch_grace_seconds = 60

    def retry(self, db: Session, job: BackgroundJob) -> BackgroundJob:
        if job.status not in {"failed", "partially_completed", "cancelled"}: raise ValueError("Only failed, partially completed or cancelled jobs can be retried")
        if job.retry_count >= job.max_retries: raise ValueError("Maximum retry count reached")
        # C03: a retry is a **new delivery attempt**. The previous attempt's ``dispatched_at`` and
        # ``celery_task_id`` describe a message that already ran (and failed), so keeping them would
        # let the compensating sweep treat the new attempt as already delivered. Clearing them in the
        # same transaction as the status change makes "this attempt still needs publishing" durable.
        job.retry_count += 1
        job.status = "queued"
        job.error_message = None
        job.finished_at = None
        job.dispatched_at = None
        job.celery_task_id = None
        job.queued_at = datetime.now(UTC)
        # The deduplication marker belongs to the *submission* that lost the race, and it lives on
        # the ORM instance. A retry is this caller's own delivery attempt, so keeping the marker
        # from a previous deduplicated submission would silently skip the publish below.
        job.submission_deduplicated = False
        db.commit()
        self._publish(db, job)
        return job
