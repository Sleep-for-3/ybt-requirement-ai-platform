from app.services.task_queue.base import JobHandler


def resolve_job_handler(job_type: str) -> JobHandler | None:
    """Resolve a durable job type after an API or worker process restart."""
    from app.api.deliverables import _deliverable_generate_handler, _deliverable_render_handler
    from app.api.jobs import _business_handler, _export_handler, _review_task_handler, _technical_handler
    from app.services.lineage.jobs import (
        lineage_export_handler,
        script_archive_ingestion_handler,
        script_repository_sync_handler,
    )
    from app.services.task_queue.domain_handlers import (
        column_profile_handler,
        knowledge_ingestion_handler,
        knowledge_embedding_reindex_handler,
        knowledge_reindex_handler,
        metadata_sync_handler,
        project_backup_handler,
        rag_evaluation_handler,
    )
    from app.services.uat.execution import uat_run_job_handler

    handlers: dict[str, JobHandler] = {
        "batch_ai_generation_business": _business_handler,
        "batch_ai_generation_technical": _technical_handler,
        "batch_review_tasks": _review_task_handler,
        "excel_export": _export_handler,
        "knowledge_ingestion": knowledge_ingestion_handler,
        "knowledge_reindex": knowledge_reindex_handler,
        "knowledge_embedding_reindex": knowledge_embedding_reindex_handler,
        "metadata_sync": metadata_sync_handler,
        "column_profile": column_profile_handler,
        "rag_evaluation": rag_evaluation_handler,
        "project_backup": project_backup_handler,
        "script_upload_ingestion": script_archive_ingestion_handler,
        "script_repository_sync": script_repository_sync_handler,
        "lineage_export": lineage_export_handler,
        "deliverable_generate_field_items": _deliverable_generate_handler,
        "deliverable_render_excel": _deliverable_render_handler,
        "uat_run_execute": uat_run_job_handler,
    }
    return handlers.get(job_type)
