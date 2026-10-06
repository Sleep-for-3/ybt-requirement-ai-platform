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
from app.services.task_queue.attempt import (
    AttemptLeaseLost,
    bind_attempt,
    current_attempt,
    release_attempt,
)


def _require_attempt(db: Session) -> None:
    """R02: 领域提交前的执行权预检。

    用于那些**在领域服务内部自行 commit** 的 handler。队列层已经用 ``_complete`` 的栅栏保护了
    审计/通知/清单导出；这里在调用领域服务**之前**再做一次显式预检，使一个已经失租的尝试至少
    不会在新的领域写入上再前进一步。

    诚实边界：这些领域服务（知识摄取/重建、元数据同步、字段探查、评测）在各自内部提交，
    本轮**未**把执行权传入它们内部（那需要修改每个服务的提交边界），因此它们的中途提交
    仍可能落在失租之后 —— 见交付记录的“未验证项”。
    """

    authority = current_attempt(db)
    if authority is not None and not authority.still_owns(db):
        raise AttemptLeaseLost("attempt lost the job before its domain write")


def knowledge_ingestion_handler(db: Session, job) -> dict:
    _require_attempt(db)
    payload = job.payload_summary_json
    data = get_storage_service().read(payload["storage_key"])
    upload = UploadFile(file=BytesIO(data), filename=payload["file_name"])
    def report_progress(completed: int, total: int) -> None:
        _require_attempt(db)
        job.progress = 95 if total == 0 else min(95, 5 + int((completed / total) * 90))
        job.current_step = f"知识索引 {completed}/{total}"
        db.commit()

    _require_attempt(db)
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
    # R02: 领域服务内部会自行 commit；在进入前做执行权预检。
    _require_attempt(db)
    reindex_knowledge_document(db, document, vector_store=vector_store)
    _complete(db, job, "update", "knowledge_document", document.id, "knowledge_parsed", "知识索引重建完成")
    return {"success_count": 1, "failed_count": 0, "document_id": document.id}


def knowledge_embedding_reindex_handler(db: Session, job) -> dict:
    from app.services.semantic_index.reindex import reindex_project_knowledge

    _require_attempt(db)
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
    _require_attempt(db)
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
    _require_attempt(db)
    task = run_column_profile(db, column, ColumnProfileRequest(**payload["request"]), created_by=str(job.created_by))
    _complete(db, job, "profile", "column_profile_task", task.id, "profile_completed", "字段安全探查完成")
    failed = 1 if task.status == "failed" else 0
    return {"success_count": 0 if failed else 1, "failed_count": failed, "profile_task_id": task.id, "status": task.status}


def rag_evaluation_handler(db: Session, job) -> dict:
    run = db.get(RagEvaluationRun, int(job.payload_summary_json["evaluation_run_id"]))
    if run is None or run.project_id != job.project_id:
        raise ValueError("Evaluation run not found")
    _require_attempt(db)
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

    # R02: 外部对象（存储）不是事务性的。先做执行权预检，避免一个已经失租的尝试还往外写对象；
    # 写出的对象在发布栅栏失败时会被删除，因此旧尝试不会留下任何“已发布”的产物。
    authority = current_attempt(db)
    if authority is not None and not authority.still_owns(db):
        raise AttemptLeaseLost("attempt lost the job before staging its export")

    saved = get_storage_service().save(content, file_name=file_name, project_id=project.id)
    row = StoredFile(
        institution_id=project.institution_id, project_id=project.id, storage_key=saved.storage_key,
        original_file_name=file_name, content_type="application/json",
        byte_size=saved.byte_size, content_hash=saved.content_hash, classification=project.confidentiality_level,
        created_by=job.created_by, enabled=True,
    )
    db.add(row);db.flush()
    published = _complete(db, job, "export", "project_manifest_export", row.id, "export_completed", "项目元数据清单导出完成（非完整备份）")
    if not published:
        # R02: 本尝试已失租 —— 审计/通知/StoredFile 已在同一事务内回滚，
        # 因此刚写入的对象从未被任何已提交行引用，必须删除，旧尝试不得留下“成功产物”。
        _discard_staged_object(saved.storage_key)
        raise AttemptLeaseLost("attempt lost the job before publishing its export")
    return {"success_count": 1, "failed_count": 0, "file_id": row.id, "byte_size": saved.byte_size}

# Retired alias: historical jobs and API clients still reference the old job key, so it keeps
# resolving to the manifest export instead of silently disappearing.
project_backup_handler = project_manifest_export_handler


def _complete(db: Session, job, action: str, resource_type: str, resource_id: int, notification_type: str, title: str) -> bool:
    """R02: 在**本尝试的执行权**之下发布领域成功效果（审计 + 通知）。

    复核 R02：旧实现无条件 ``db.commit()``，而队列层只在 handler 返回后才看 ``lease_lost``，
    所以已经失租的旧尝试仍会提交审计与通知，接管之后再提交一份 —— 各 2 条。

    现在：先做只读预检（廉价早退），再在**同一事务**内用 ``fence_commit`` 对 job 行加锁并校验
    owner，只有仍持有该 job 时才提交挂起的审计/通知/领域对象；否则整体回滚。

    返回 True 表示效果已由仍持有 job 的尝试提交；False 表示本尝试已失租，**没有任何**
    审计/通知/领域行被发布（调用方据此清理外部对象并抛出 ``AttemptLeaseLost``）。
    当调用方未绑定执行权（历史直接调用路径）时保持原有 ``commit`` 行为。
    """

    authority = current_attempt(db)
    if authority is not None and not authority.still_owns(db):
        db.rollback()
        return False

    record_audit(
        db, action=action, resource_type=resource_type, resource_id=resource_id,
        actor_user_id=job.created_by, institution_id=job.institution_id, project_id=job.project_id,
        after={"background_job_id": job.id},
    )
    notify_user(
        db, job.created_by, notification_type, title, f"后台任务 {job.id} 已完成",
        project_id=job.project_id, resource_type=resource_type, resource_id=resource_id,
    )
    if authority is not None:
        return authority.fence_commit(db)
    db.commit()
    return True


def _discard_staged_object(storage_key: str) -> None:
    """R02: 发布栅栏失败时回收已写入的外部对象（它从未被任何已提交行引用）。"""

    try:
        get_storage_service().delete(storage_key)
    except Exception:  # noqa: BLE001 - 清理失败不能遮蔽“本尝试已失租”这个事实
        pass


def _run_async(coroutine):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()
