from datetime import datetime

from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import TemplateApplication, TemplateDocument, TemplateParseResult, TemplateVersion
from app.schemas import (TemplateApplyResponse, TemplateDocumentRead, TemplateParseResultRead,
                         TemplateUploadResponse, TemplateVersionRead)
from app.services.template_service import (activate_template_version, apply_template, ingest_template,
                                            review_template_version, template_version_diff)
from app.services.storage import get_storage_service

router = APIRouter(prefix="/templates", tags=["templates"])


@router.post("/upload", response_model=TemplateUploadResponse)
async def upload_template(
    project_id: int = Form(...),
    file: UploadFile = File(...),
    template_code: str | None = Form(None),
    display_name: str | None = Form(None),
    regulatory_version: str | None = Form(None),
    release_batch: str | None = Form(None),
    publisher: str | None = Form(None),
    published_at: datetime | None = Form(None),
    effective_at: datetime | None = Form(None),
    expires_at: datetime | None = Form(None),
    change_note: str | None = Form(None),
    db: Session = Depends(get_db),
) -> TemplateUploadResponse:
    try:
        return await ingest_template(db, project_id, file, template_code=template_code,
            display_name=display_name, regulatory_version=regulatory_version,
            release_batch=release_batch, publisher=publisher, published_at=published_at,
            effective_at=effective_at, expires_at=expires_at, change_note=change_note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{template_id}", response_model=TemplateDocumentRead)
def get_template(template_id: int, db: Session = Depends(get_db)) -> TemplateDocument:
    template = db.get(TemplateDocument, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.get("/{template_id}/parse-results", response_model=list[TemplateParseResultRead])
def get_template_parse_results(template_id: int, version_id: int | None = None, db: Session = Depends(get_db)) -> list[TemplateParseResult]:
    predicates = [TemplateParseResult.template_document_id == template_id]
    if version_id is not None:
        predicates.append(TemplateParseResult.template_version_id == version_id)
    return list(
        db.scalars(
            select(TemplateParseResult)
            .where(*predicates)
            .order_by(TemplateParseResult.id)
        ).all()
    )


@router.post("/{template_id}/apply", response_model=TemplateApplyResponse)
def apply_template_api(template_id: int, db: Session = Depends(get_db)) -> TemplateApplyResponse:
    try:
        summary = apply_template(db, template_id)
        return TemplateApplyResponse(**summary.__dict__)
    except ValueError as exc:
        raise HTTPException(status_code=409 if "激活" in str(exc) else 404, detail=str(exc)) from exc


@router.get("/{template_id}/detail")
def template_detail(template_id: int, db: Session = Depends(get_db)) -> dict:
    template = db.get(TemplateDocument, template_id)
    if not template:
        raise HTTPException(404, "Template not found")
    versions = list(db.scalars(select(TemplateVersion).where(
        TemplateVersion.template_document_id == template_id).order_by(TemplateVersion.version_no.desc())).all())
    applications = list(db.scalars(select(TemplateApplication).where(
        TemplateApplication.template_document_id == template_id).order_by(TemplateApplication.id.desc())).all())
    return {"template": TemplateDocumentRead.model_validate(template).model_dump(),
        "versions": [TemplateVersionRead.model_validate(item).model_dump() for item in versions],
        "applications": [{"id": item.id, "template_version_id": item.template_version_id,
            "change_set_json": item.change_set_json, "impact_json": item.impact_json,
            "applied_by": item.applied_by, "applied_at": item.applied_at} for item in applications]}


@router.get("/versions/{version_id}", response_model=TemplateVersionRead)
def get_template_version(version_id: int, db: Session = Depends(get_db)) -> TemplateVersion:
    version = db.get(TemplateVersion, version_id)
    if not version:
        raise HTTPException(404, "Template version not found")
    return version


@router.get("/versions/{version_id}/diff")
def get_template_version_diff(version_id: int, compare_to_id: int | None = None, db: Session = Depends(get_db)) -> dict:
    try:
        return template_version_diff(db, version_id, compare_to_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/versions/{version_id}/content")
def template_version_content(version_id: int, db: Session = Depends(get_db)) -> Response:
    version = db.get(TemplateVersion, version_id)
    if not version:
        raise HTTPException(404, "Template version not found")
    try:
        data = get_storage_service().read(version.storage_path)
    except Exception:
        raise HTTPException(404, "Template version not found") from None
    name = PurePosixPath(version.file_name.replace("\\", "/")).name[:255] or "template.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":f"attachment; filename=template.xlsx; filename*=UTF-8''{quote(name, safe='')}",
                 "Cache-Control":"no-store", "X-Content-Type-Options":"nosniff"})


@router.post("/versions/{version_id}/review", response_model=TemplateVersionRead)
def review_version(version_id: int, db: Session = Depends(get_db)) -> TemplateVersion:
    try:
        return review_template_version(db, version_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/versions/{version_id}/activate", response_model=TemplateVersionRead)
def activate_version(version_id: int, db: Session = Depends(get_db)) -> TemplateVersion:
    try:
        return activate_template_version(db, version_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


projects_router = APIRouter(prefix="/projects", tags=["templates"])


@projects_router.get("/{project_id}/templates", response_model=list[TemplateDocumentRead])
def list_project_templates(project_id: int, db: Session = Depends(get_db)) -> list[TemplateDocument]:
    return list(
        db.scalars(
            select(TemplateDocument)
            .where(TemplateDocument.project_id == project_id)
            .order_by(TemplateDocument.id.desc())
        ).all()
    )
