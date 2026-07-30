from celery import Celery

from app.core.database import SessionLocal
from app.core.settings import get_settings
from app.models import BackgroundJob
from app.services.task_queue.handlers import resolve_job_handler
from app.services.task_queue.inline import InlineTaskQueue


settings = get_settings()
celery_app = Celery("ybt_governance", broker=settings.celery_broker_url, backend=settings.celery_result_backend)


@celery_app.task(name="app.workers.execute_background_job")
def execute_background_job(job_id: int) -> None:
    # Queue payload contains only the durable job id. Worker reloads governed summaries from the DB.
    with SessionLocal() as db:
        job = db.get(BackgroundJob, job_id)
        if job is None or job.status == "cancelled":
            return
        InlineTaskQueue().execute_existing(db, job, resolve_job_handler(job.job_type))
