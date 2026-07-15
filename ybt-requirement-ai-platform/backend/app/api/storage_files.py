import hashlib
from pathlib import Path, PurePath
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.settings import get_settings
from app.models import StoredFile
from app.services.auth.dependencies import RealPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.governance.audit import record_audit
from app.services.storage import get_storage_service


router = APIRouter(tags=["secure storage"])
ALLOWED_EXTENSIONS = {".txt", ".csv", ".json", ".sql", ".xlsx", ".xls", ".docx", ".pdf"}
ALLOWED_MIME_PREFIXES = ("text/", "application/json", "application/pdf", "application/vnd.", "application/octet-stream")
CLASSIFICATIONS = {"public", "internal", "confidential", "restricted"}


@router.post("/projects/{project_id}/files", status_code=status.HTTP_201_CREATED)
async def upload_file(project_id: int, principal: RealPrincipal, file: UploadFile = File(...), classification: str = Form("internal"), db: Session = Depends(get_db)) -> dict:
    project = PermissionService(db, principal).require_project_permission(project_id, "knowledge.manage")
    file_name = file.filename or ""
    if not _safe_file_name(file_name):
        raise HTTPException(status_code=400, detail="Invalid file name")
    if Path(file_name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="File extension is not allowed")
    if not any((file.content_type or "application/octet-stream").startswith(prefix) for prefix in ALLOWED_MIME_PREFIXES):
        raise HTTPException(status_code=400, detail="File MIME type is not allowed")
    if classification not in CLASSIFICATIONS:
        raise HTTPException(status_code=400, detail="Invalid classification")
    data = await file.read(get_settings().max_upload_bytes + 1)
    if len(data) > get_settings().max_upload_bytes:
        raise HTTPException(status_code=413, detail="File is too large")
    digest = hashlib.sha256(data).hexdigest()
    duplicate = db.scalar(select(StoredFile).where(
        StoredFile.institution_id == project.institution_id,
        StoredFile.project_id == project_id,
        StoredFile.content_hash == digest,
        StoredFile.enabled.is_(True),
    ))
    if duplicate:
        _raise_classification(duplicate, classification)
        record_audit(db, action="duplicate_upload", resource_type="stored_file", resource_id=duplicate.id, actor_user_id=principal.user_id, institution_id=project.institution_id, project_id=project_id, after={"file_name": Path(file_name).name, "content_hash": digest})
        db.commit()
        return _public_file(duplicate)
    service = get_storage_service()
    try:
        saved = service.save(data, file_name=file_name, project_id=project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row = StoredFile(
        institution_id=project.institution_id,
        project_id=project_id,
        storage_key=saved.storage_key,
        original_file_name=Path(file_name).name,
        content_type=file.content_type or "application/octet-stream",
        byte_size=saved.byte_size,
        content_hash=saved.content_hash,
        classification=classification,
        created_by=principal.user_id,
        enabled=True,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        duplicate = db.scalar(select(StoredFile).where(
            StoredFile.institution_id == project.institution_id,
            StoredFile.project_id == project_id,
            StoredFile.content_hash == digest,
            StoredFile.enabled.is_(True),
        ))
        if duplicate is None:
            raise HTTPException(status_code=409, detail="A file with this storage key already exists")
        _raise_classification(duplicate, classification)
        record_audit(db, action="duplicate_upload", resource_type="stored_file", resource_id=duplicate.id, actor_user_id=principal.user_id, institution_id=project.institution_id, project_id=project_id, after={"file_name": Path(file_name).name, "content_hash": digest})
        db.commit()
        return _public_file(duplicate)
    record_audit(db, action="upload", resource_type="stored_file", resource_id=row.id, actor_user_id=principal.user_id, institution_id=project.institution_id, project_id=project_id, after={"file_name": row.original_file_name, "classification": classification, "byte_size": row.byte_size})
    db.commit();db.refresh(row)
    return _public_file(row)


@router.get("/files/{file_id}/download")
def download_file(file_id: int, principal: RealPrincipal, db: Session = Depends(get_db)) -> Response:
    row = db.get(StoredFile, file_id)
    if row is None or not row.enabled:
        raise HTTPException(status_code=404, detail="File not found")
    PermissionService(db, principal).require_project_permission(row.project_id, "project.view")
    try:
        content = get_storage_service().read(row.storage_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    record_audit(db, action="download", resource_type="stored_file", resource_id=row.id, actor_user_id=principal.user_id, institution_id=row.institution_id, project_id=row.project_id, after={"file_name": row.original_file_name, "classification": row.classification})
    db.commit()
    return Response(content=content, media_type=row.content_type, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(row.original_file_name)}", "Cache-Control": "no-store"})


def _safe_file_name(value: str) -> bool:
    return bool(value and value == Path(value).name and "/" not in value and "\\" not in value and ".." not in PurePath(value).parts)


def _public_file(row: StoredFile) -> dict:
    return {"id": row.id, "project_id": row.project_id, "file_name": row.original_file_name, "content_type": row.content_type, "byte_size": row.byte_size, "content_hash": row.content_hash, "classification": row.classification, "created_at": row.created_at}


def _raise_classification(row: StoredFile, requested: str) -> None:
    rank = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
    if rank[requested] > rank.get(row.classification, 0):
        row.classification = requested
