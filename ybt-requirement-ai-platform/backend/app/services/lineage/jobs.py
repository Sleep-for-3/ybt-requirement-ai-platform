from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models import BackgroundJobItem, CodeRepository, Project, ScriptFile, StoredFile
from app.services.lineage.archive_ingestion import read_safe_script_archive
from app.services.lineage.git_repository import read_git_repository_scripts
from app.services.lineage.ingestion import ScriptIngestionService
from app.services.storage import get_storage_service


def script_archive_ingestion_handler(db: Session, job) -> dict:
    stored = db.get(StoredFile, int(job.payload_summary_json["stored_file_id"]))
    project = db.get(Project, job.project_id)
    if stored is None or project is None or stored.project_id != project.id:
        raise ValueError("Stored script archive not found")
    settings = get_settings()
    files = read_safe_script_archive(
        get_storage_service().read(stored.storage_key), max_archive_bytes=settings.max_upload_bytes,
        max_total_bytes=settings.lineage_zip_max_total_bytes, max_file_count=settings.lineage_zip_max_file_count,
        max_file_bytes=settings.lineage_script_max_bytes,
    )
    return _ingest_files(db, job, project, files, dialect=job.payload_summary_json.get("dialect"))


def script_repository_sync_handler(db: Session, job) -> dict:
    repository = db.get(CodeRepository, int(job.payload_summary_json["repository_id"]))
    project = db.get(Project, job.project_id)
    if repository is None or project is None or repository.project_id != project.id or not repository.enabled:
        raise ValueError("Code repository not found")
    settings = get_settings()
    snapshot = read_git_repository_scripts(
        repository.repository_url or "", branch=repository.default_branch,
        max_repository_bytes=settings.lineage_repository_max_bytes,
        max_file_count=settings.lineage_repository_max_file_count,
        max_file_bytes=settings.lineage_script_max_bytes,
    )
    result = _ingest_files(db, job, project, snapshot.files, repository=repository, commit_sha=snapshot.commit_sha)
    seen = {item.relative_path for item in snapshot.files}
    for missing in db.scalars(select(ScriptFile).where(ScriptFile.code_repository_id == repository.id, ScriptFile.enabled.is_(True))).all():
        if missing.relative_path not in seen:
            missing.enabled = False
    repository.last_sync_commit = snapshot.commit_sha
    repository.last_synced_at = datetime.now(UTC)
    db.commit()
    return {**result, "commit_sha": snapshot.commit_sha}


def _ingest_files(db: Session, job, project: Project, files, *, dialect: str | None = None, repository: CodeRepository | None = None, commit_sha: str | None = None) -> dict:
    service = ScriptIngestionService(db, get_storage_service())
    successful = failed = skipped = 0
    for index, item in enumerate(files, start=1):
        db.refresh(job)
        if job.status == "cancelled":
            break
        existing = db.scalar(select(BackgroundJobItem).where(BackgroundJobItem.background_job_id == job.id, BackgroundJobItem.item_key == item.relative_path))
        if existing is not None and existing.status == "completed":
            successful += 1; skipped += 1
            continue
        try:
            result = service.ingest(
                project=project, data=item.content, file_name=item.file_name, relative_path=item.relative_path,
                dialect=dialect, actor_user_id=job.created_by,
                code_repository_id=repository.id if repository else None, git_commit_sha=commit_sha,
            )
            row = existing or BackgroundJobItem(background_job_id=job.id, item_key=item.relative_path)
            row.status = "completed"; row.result_summary_json = {"script_file_id": result.script_file.id, "version_id": result.version.id}; row.error_message = None
            if existing is None: db.add(row)
            successful += 1
        except Exception as exc:
            db.rollback(); job = db.get(type(job), job.id)
            row = db.scalar(select(BackgroundJobItem).where(BackgroundJobItem.background_job_id == job.id, BackgroundJobItem.item_key == item.relative_path))
            if row is None:
                row = BackgroundJobItem(background_job_id=job.id, item_key=item.relative_path); db.add(row)
            row.status = "failed"; row.result_summary_json = {}; row.error_message = str(exc)[:2000]
            failed += 1
        job.progress = int(index * 99 / max(len(files), 1)); job.current_step = item.relative_path
        db.commit()
    return {"success_count": successful, "failed_count": failed, "skipped_completed_count": skipped, "total_count": len(files)}
