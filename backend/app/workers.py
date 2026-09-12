from celery import Celery

from app.core.database import SessionLocal
from app.core.settings import get_settings
from app.models import BackgroundJob
from app.services.lineage.monitoring import run_due_repository_monitors
from app.services.task_queue.handlers import resolve_job_handler
from app.services.task_queue.inline import InlineTaskQueue


settings = get_settings()
celery_app = Celery("ybt_governance", broker=settings.celery_broker_url, backend=settings.celery_result_backend)
celery_app.conf.beat_schedule = {
    **(celery_app.conf.beat_schedule or {}),
    "lineage-repository-monitor": {
        "task": "app.workers.poll_lineage_repositories",
        "schedule": 60.0,
    },
}


@celery_app.task(name="app.workers.execute_background_job")
def execute_background_job(job_id: int) -> None:
    # Queue payload contains only the durable job id. Worker reloads governed summaries from the DB.
    with SessionLocal() as db:
        job = db.get(BackgroundJob, job_id)
        if job is None or job.status == "cancelled":
            return
        InlineTaskQueue().execute_existing(db, job, resolve_job_handler(job.job_type))


@celery_app.task(name="app.workers.poll_lineage_repositories")
def poll_lineage_repositories() -> dict:
    """Celery Beat entrypoint for due repository monitors."""

    with SessionLocal() as db:
        return run_due_repository_monitors(db).as_dict()
