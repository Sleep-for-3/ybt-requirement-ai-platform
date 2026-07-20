from celery import Celery

from app.core.database import SessionLocal
from app.core.settings import get_settings
from app.models import BackgroundJob
from app.services.task_queue.inline import InlineTaskQueue


settings = get_settings()
celery_app = Celery("ybt_governance", broker=settings.celery_broker_url, backend=settings.celery_result_backend)


@celery_app.task(name="app.workers.execute_background_job")
def execute_background_job(job_id: int) -> None:
    # Queue payload contains only the durable job id. Worker reloads governed summaries from the DB.
    from app.api.jobs import _business_handler, _export_handler, _review_task_handler, _technical_handler
    from app.services.task_queue.domain_handlers import column_profile_handler, knowledge_ingestion_handler, knowledge_reindex_handler, metadata_sync_handler, project_backup_handler, rag_evaluation_handler
    from app.services.lineage.jobs import lineage_export_handler, script_archive_ingestion_handler, script_repository_sync_handler
    from app.api.deliverables import _deliverable_generate_handler
    handlers = {
        "batch_ai_generation_business": _business_handler,
        "batch_ai_generation_technical": _technical_handler,
        "batch_review_tasks": _review_task_handler,
        "excel_export": _export_handler,
        "knowledge_ingestion": knowledge_ingestion_handler,
        "knowledge_reindex": knowledge_reindex_handler,
        "metadata_sync": metadata_sync_handler,
        "column_profile": column_profile_handler,
        "rag_evaluation": rag_evaluation_handler,
        "project_backup": project_backup_handler,
        "script_upload_ingestion": script_archive_ingestion_handler,
        "script_repository_sync": script_repository_sync_handler,
        "lineage_export": lineage_export_handler,
        "deliverable_generate_field_items": _deliverable_generate_handler,
    }
    with SessionLocal() as db:
        job = db.get(BackgroundJob, job_id)
        if job is None or job.status == "cancelled":
            return
        InlineTaskQueue().execute_existing(db, job, handlers.get(job.job_type))
