import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models import CatalogColumn, DataSource, KnowledgeDocument, Project, RagEvaluationRun, StoredFile
from app.schemas import ColumnProfileRequest
from app.services.evaluation import run_evaluation
from app.services.governance.audit import record_audit
from app.services.governance.notifications import notify_user
from app.services.knowledge_ingestion import ingest_knowledge_document
from app.services.metadata import synchronize_metadata
from app.services.metadata.profile_service import run_column_profile
from app.services.storage import get_storage_service


def knowledge_ingestion_handler(db: Session, job) -> dict:
    payload = job.payload_summary_json
    data = get_storage_service().read(payload["storage_key"])
    upload = UploadFile(file=BytesIO(data), filename=payload["file_name"])
    document = _run_async(ingest_knowledge_document(
        db,
        job.project_id,
        upload,
        payload["knowledge_type"],
        payload.get("knowledge_scope", "project"),
        payload.get("institution_name"),
        payload.get("confidentiality_level", "internal"),
        created_by=job.created_by,
        change_note=payload.get("change_note"),
    ))
    _complete(db, job, "upload", "knowledge_document", document.id, "knowledge_parsed", "知识解析完成")
    return {"success_count": 1, "failed_count": 0, "document_id": document.id}


def knowledge_reindex_handler(db: Session, job, vector_store=None) -> dict:
    from app.services.knowledge_reindex import reindex_knowledge_document
    document = db.get(KnowledgeDocument, int(job.payload_summary_json["document_id"]))
    if document is None or document.project_id != job.project_id:
        raise ValueError("Knowledge document not found")
    reindex_knowledge_document(db, document, vector_store=vector_store)
    _complete(db, job, "update", "knowledge_document", document.id, "knowledge_parsed", "知识索引重建完成")
    return {"success_count": 1, "failed_count": 0, "document_id": document.id}


def metadata_sync_handler(db: Session, job) -> dict:
    payload = job.payload_summary_json
    datasource = db.get(DataSource, int(payload["datasource_id"]))
    if datasource is None or datasource.project_id != job.project_id:
        raise ValueError("Data source not found")
    task = synchronize_metadata(
        db, datasource, payload.get("sync_mode", "full"), payload.get("schema_names"),
        bool(payload.get("include_views", True)), created_by=str(job.created_by),
    )
    notification_type = "metadata_sync_failed" if task.status == "failed" else "metadata_sync_completed"
    _complete(db, job, "metadata_sync", "metadata_sync_task", task.id, notification_type, "元数据同步完成" if task.status != "failed" else "元数据同步失败")
    failed = 1 if task.status == "failed" else 0
    return {"success_count": 0 if failed else 1, "failed_count": failed, "metadata_sync_task_id": task.id, "status": task.status}


def column_profile_handler(db: Session, job) -> dict:
    payload = job.payload_summary_json
    column = db.get(CatalogColumn, int(payload["column_id"]))
    if column is None or column.project_id != job.project_id:
        raise ValueError("Catalog column not found")
    task = run_column_profile(db, column, ColumnProfileRequest(**payload["request"]), created_by=str(job.created_by))
    _complete(db, job, "profile", "column_profile_task", task.id, "profile_completed", "字段安全探查完成")
    failed = 1 if task.status == "failed" else 0
    return {"success_count": 0 if failed else 1, "failed_count": failed, "profile_task_id": task.id, "status": task.status}


def rag_evaluation_handler(db: Session, job) -> dict:
    run = db.get(RagEvaluationRun, int(job.payload_summary_json["evaluation_run_id"]))
    if run is None or run.project_id != job.project_id:
        raise ValueError("Evaluation run not found")
    _run_async(run_evaluation(db, run))
    _complete(db, job, "model_call", "rag_evaluation_run", run.id, "evaluation_completed", "RAG 评测完成")
    return {"success_count": 1, "failed_count": 0, "evaluation_run_id": run.id}


def project_backup_handler(db: Session, job) -> dict:
    import json
    project = db.get(Project, job.project_id)
    if project is None:
        raise ValueError("Project not found")
    content = json.dumps({"project_id": project.id, "project_name": project.name, "backup_scope": "metadata"}, ensure_ascii=False).encode("utf-8")
    saved = get_storage_service().save(content, file_name=f"project-{project.id}-backup.json", project_id=project.id)
    row = StoredFile(
        institution_id=project.institution_id, project_id=project.id, storage_key=saved.storage_key,
        original_file_name=f"project-{project.id}-backup.json", content_type="application/json",
        byte_size=saved.byte_size, content_hash=saved.content_hash, classification=project.confidentiality_level,
        created_by=job.created_by, enabled=True,
    )
    db.add(row);db.flush()
    _complete(db, job, "export", "project_backup", row.id, "export_completed", "项目备份完成")
    return {"success_count": 1, "failed_count": 0, "file_id": row.id, "byte_size": saved.byte_size}


def _complete(db: Session, job, action: str, resource_type: str, resource_id: int, notification_type: str, title: str) -> None:
    record_audit(
        db, action=action, resource_type=resource_type, resource_id=resource_id,
        actor_user_id=job.created_by, institution_id=job.institution_id, project_id=job.project_id,
        after={"background_job_id": job.id},
    )
    notify_user(
        db, job.created_by, notification_type, title, f"后台任务 {job.id} 已完成",
        project_id=job.project_id, resource_type=resource_type, resource_id=resource_id,
    )
    db.commit()


def _run_async(coroutine):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()
