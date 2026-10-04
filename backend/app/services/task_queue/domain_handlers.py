import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models import CatalogColumn, DataSource, KnowledgeDocument, Project, RagEvaluationRun, StoredFile
from app.core.settings import get_settings
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
    def report_progress(completed: int, total: int) -> None:
        job.progress = 95 if total == 0 else min(95, 5 + int((completed / total) * 90))
        job.current_step = f"知识索引 {completed}/{total}"
        db.commit()

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
        document_id=payload.get("document_id"),
        source_category=payload.get("source_category"),
        logical_code=payload.get("logical_code"),
        regulatory_document_no=payload.get("regulatory_document_no"),
        regulatory_version=payload.get("regulatory_version"),
        internal_revision=payload.get("internal_revision"),
        publisher=payload.get("publisher"),
        published_at=_payload_datetime(payload.get("published_at")),
        effective_at=_payload_datetime(payload.get("effective_at")),
        expires_at=_payload_datetime(payload.get("expires_at")),
        applicable_project_ids=payload.get("applicable_project_ids"),
        applicable_institution_names=payload.get("applicable_institution_names"),
        applicable_field_codes=payload.get("applicable_field_codes"),
        applicable_scenario_ids=payload.get("applicable_scenario_ids"),
        batch_size=get_settings().knowledge_ingestion_batch_size,
        progress=report_progress,
    ))
    _complete(db, job, "upload", "knowledge_document", document.id, "knowledge_parsed", "知识解析完成")
    return {"success_count": 1, "failed_count": 0, "document_id": document.id}


def _payload_datetime(value):
    if not value or not isinstance(value, str):
        return value
    from datetime import datetime
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def knowledge_reindex_handler(db: Session, job, vector_store=None) -> dict:
    from app.services.knowledge_reindex import reindex_knowledge_document
    document = db.get(KnowledgeDocument, int(job.payload_summary_json["document_id"]))
    if document is None or document.project_id != job.project_id:
        raise ValueError("Knowledge document not found")
    reindex_knowledge_document(db, document, vector_store=vector_store)
    _complete(db, job, "update", "knowledge_document", document.id, "knowledge_parsed", "知识索引重建完成")
    return {"success_count": 1, "failed_count": 0, "document_id": document.id}


def knowledge_embedding_reindex_handler(db: Session, job) -> dict:
    from app.services.semantic_index.reindex import reindex_project_knowledge

    result = reindex_project_knowledge(db, job)
    if not result.get("cancelled"):
        _complete(
            db,
            job,
            "activate",
            "embedding_index_version",
            int(result["index_version_id"]),
            "knowledge_index_completed",
            "正式语义索引重建完成",
        )
    return result


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


def project_manifest_export_handler(db: Session, job) -> dict:
    """W09: export a project metadata manifest - explicitly NOT a backup.

    The previous name ('project backup') described a file that only carried the project id, name
    and a scope marker, which invites treating it as a restorable backup. It now declares what it
    is, what it does not contain, and what a real backup still requires, so nobody can mistake the
    manifest for disaster recovery.
    """
    import json
    from datetime import UTC, datetime
    project = db.get(Project, job.project_id)
    if project is None:
        raise ValueError("Project not found")
    manifest = {
        "project_id": project.id,
        "project_name": project.name,
        "artifact_kind": "project_metadata_manifest",
        "is_full_backup": False,
        "backup_scope": "metadata",
        "notice": "本文件仅为项目元数据清单，不含业务数据、附件、向量索引或数据库转储，不能用于恢复。",
        "full_backup_requires": [
            "PostgreSQL 转储（业务数据与审核记录，含一致性点）",
            "附件与正式交付对象存储",
            "配置安全引用（不含明文密钥）",
            "向量索引快照或可靠重建依据",
            "依赖清单与版本（应用 commit / 迁移 head / Skill 与模型版本）",
        ],
        "generated_at": datetime.now(UTC).isoformat(),
    }
    content = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
    file_name = f"project-{project.id}-manifest.json"
    saved = get_storage_service().save(content, file_name=file_name, project_id=project.id)
    row = StoredFile(
        institution_id=project.institution_id, project_id=project.id, storage_key=saved.storage_key,
        original_file_name=file_name, content_type="application/json",
        byte_size=saved.byte_size, content_hash=saved.content_hash, classification=project.confidentiality_level,
        created_by=job.created_by, enabled=True,
    )
    db.add(row);db.flush()
    _complete(db, job, "export", "project_manifest_export", row.id, "export_completed", "项目元数据清单导出完成（非完整备份）")
    return {"success_count": 1, "failed_count": 0, "file_id": row.id, "byte_size": saved.byte_size}


# Retired alias: historical jobs and API clients still reference the old job key, so it keeps
# resolving to the manifest export instead of silently disappearing.
project_backup_handler = project_manifest_export_handler


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
