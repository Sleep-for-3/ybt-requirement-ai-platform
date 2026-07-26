from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import TemplateDocument, TemplateParseResult
from app.schemas import TemplateApplyResponse, TemplateDocumentRead, TemplateParseResultRead, TemplateUploadResponse
from app.services.template_service import apply_template, ingest_template

router = APIRouter(prefix="/templates", tags=["templates"])


@router.post("/upload", response_model=TemplateUploadResponse)
async def upload_template(
    project_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> TemplateUploadResponse:
    try:
        return await ingest_template(db, project_id, file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{template_id}", response_model=TemplateDocumentRead)
def get_template(template_id: int, db: Session = Depends(get_db)) -> TemplateDocument:
    template = db.get(TemplateDocument, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.get("/{template_id}/parse-results", response_model=list[TemplateParseResultRead])
def get_template_parse_results(template_id: int, db: Session = Depends(get_db)) -> list[TemplateParseResult]:
    return list(
        db.scalars(
            select(TemplateParseResult)
            .where(TemplateParseResult.template_document_id == template_id)
            .order_by(TemplateParseResult.id)
        ).all()
    )


@router.post("/{template_id}/apply", response_model=TemplateApplyResponse)
def apply_template_api(template_id: int, db: Session = Depends(get_db)) -> TemplateApplyResponse:
    try:
        summary = apply_template(db, template_id)
        return TemplateApplyResponse(**summary.__dict__)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
