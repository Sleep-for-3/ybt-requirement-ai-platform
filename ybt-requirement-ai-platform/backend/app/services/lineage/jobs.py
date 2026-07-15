from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import os
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models import BackgroundJobItem, CodeRepository, Project, ScriptFile, ScriptFileVersion, StoredFile
from app.services.lineage.archive_ingestion import read_safe_script_archive
from app.services.lineage.git_repository import read_git_repository_scripts, validate_repository_location
from app.services.lineage.ingestion import ScriptIngestionService
from app.services.lineage.impact_analyzer import persist_change_impact
from app.services.lineage.exporter import export_lineage_workbook
from app.services.lineage.version_diff import ChangeItemSpec, VersionDiffResult
from app.services.governance.audit import record_audit
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
    credential = None
    if repository.credential_env_name:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", repository.credential_env_name):
            raise ValueError("Code repository credential configuration is invalid")
        credential = os.environ.get(repository.credential_env_name)
        if not credential:
            raise ValueError("Code repository credential environment variable is not configured")
    settings = get_settings()
    validate_repository_location(
        repository.repository_url or "",
        allowed_hosts=settings.lineage_git_allowed_host_list,
        allowed_local_roots=settings.lineage_git_allowed_local_root_list,
    )
    snapshot = read_git_repository_scripts(
        repository.repository_url or "", branch=repository.default_branch,
        credential=credential,
        max_repository_bytes=settings.lineage_repository_max_bytes,
        max_file_count=settings.lineage_repository_max_file_count,
        max_file_bytes=settings.lineage_script_max_bytes,
    )
    renamed_count = _detect_repository_renames(db, repository, snapshot.files, job.created_by)
    result = _ingest_files(db, job, project, snapshot.files, repository=repository, commit_sha=snapshot.commit_sha)
    seen = {item.relative_path for item in snapshot.files}
    deleted_count = 0
    for missing in db.scalars(select(ScriptFile).where(ScriptFile.code_repository_id == repository.id, ScriptFile.enabled.is_(True))).all():
        if missing.relative_path not in seen:
            current = _current_version(db, missing)
            if current is not None:
                diff = VersionDiffResult(
                    semantic_changed=True,
                    severity="critical",
                    items=(ChangeItemSpec(
                        "source_column_removed", "script",
                        {"relative_path": missing.relative_path}, {}, "critical",
                    ),),
                    summary={"semantic_changed": True, "categories": ["source_column_removed"]},
                )
                persist_change_impact(
                    db, script_file=missing, from_version=current, to_version=None,
                    diff=diff, created_by=job.created_by, change_type="deleted",
                )
            missing.enabled = False
            deleted_count += 1
    repository.last_sync_commit = snapshot.commit_sha
    repository.last_synced_at = datetime.now(UTC)
    db.commit()
    return {**result, "commit_sha": snapshot.commit_sha, "renamed_count": renamed_count, "deleted_count": deleted_count}


def lineage_export_handler(db: Session, job) -> dict:
    project = db.get(Project, job.project_id)
    if project is None:
        raise ValueError("Project not found")
    payload = job.payload_summary_json
    content = export_lineage_workbook(
        db,
        project.id,
        script_file_id=payload.get("script_file_id"),
        target_field_id=payload.get("target_field_id"),
    )
    storage = get_storage_service()
    file_name = str(payload.get("file_name") or f"project-{project.id}-lineage.xlsx")
    digest = hashlib.sha256(content).hexdigest()
    stored = db.scalar(select(StoredFile).where(
        StoredFile.institution_id == project.institution_id,
        StoredFile.project_id == project.id,
        StoredFile.content_hash == digest,
        StoredFile.enabled.is_(True),
    ))
    if stored is None:
        saved = storage.save(content, file_name=file_name, project_id=project.id)
        stored = StoredFile(
            institution_id=project.institution_id,
            project_id=project.id,
            storage_key=saved.storage_key,
            original_file_name=file_name,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            byte_size=saved.byte_size,
            content_hash=saved.content_hash,
            classification=project.confidentiality_level,
            created_by=job.created_by,
            enabled=True,
        )
        db.add(stored)
        db.flush()
    record_audit(
        db, action="export", resource_type="lineage_workbook", resource_id=stored.id,
        actor_user_id=job.created_by, institution_id=project.institution_id, project_id=project.id,
        after={"background_job_id": job.id, "file_id": stored.id, "byte_size": stored.byte_size},
    )
    db.commit()
    return {"success_count": 1, "failed_count": 0, "file_id": stored.id, "byte_size": stored.byte_size}


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


def _detect_repository_renames(db: Session, repository: CodeRepository, files, created_by: int | None) -> int:
    active = list(db.scalars(select(ScriptFile).where(
        ScriptFile.code_repository_id == repository.id,
        ScriptFile.enabled.is_(True),
    )).all())
    existing_paths = {item.relative_path for item in active}
    incoming_paths = {item.relative_path for item in files}
    missing = [item for item in active if item.relative_path not in incoming_paths]
    added = [item for item in files if item.relative_path not in existing_paths]
    missing_by_hash: dict[str, list[tuple[ScriptFile, ScriptFileVersion]]] = {}
    for script in missing:
        version = _current_version(db, script)
        if version is not None:
            missing_by_hash.setdefault(version.file_hash, []).append((script, version))
    added_by_hash: dict[str, list] = {}
    for item in added:
        added_by_hash.setdefault(hashlib.sha256(item.content).hexdigest(), []).append(item)
    renamed = 0
    for digest in missing_by_hash.keys() & added_by_hash.keys():
        if len(missing_by_hash[digest]) != 1 or len(added_by_hash[digest]) != 1:
            continue
        (script, version), incoming = missing_by_hash[digest][0], added_by_hash[digest][0]
        old_path = script.relative_path
        script.relative_path = incoming.relative_path
        script.file_name = incoming.file_name
        diff = VersionDiffResult(
            semantic_changed=False,
            severity="low",
            items=(ChangeItemSpec(
                "non_semantic", "script_path",
                {"relative_path": old_path}, {"relative_path": incoming.relative_path}, "low",
            ),),
            summary={"semantic_changed": False, "categories": ["non_semantic"], "renamed_from": old_path, "renamed_to": incoming.relative_path},
        )
        persist_change_impact(
            db, script_file=script, from_version=version, to_version=version,
            diff=diff, created_by=created_by, change_type="renamed",
        )
        renamed += 1
    db.flush()
    return renamed


def _current_version(db: Session, script: ScriptFile) -> ScriptFileVersion | None:
    return db.scalar(select(ScriptFileVersion).where(
        ScriptFileVersion.script_file_id == script.id,
        ScriptFileVersion.version_no == script.current_version_no,
    ))
