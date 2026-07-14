from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import TraceabilityTemplateDocument, TraceabilityTemplateParseResult
from app.schemas import (
    TraceabilityTemplateApplyResponse,
    TraceabilityTemplateDocumentRead,
    TraceabilityTemplateParseResultRead,
    TraceabilityTemplatePreviewResponse,
    TraceabilityTemplateUploadResponse,
)
from app.services.traceability_template_service import apply_traceability_template, ingest_traceability_template, summary_dict

router = APIRouter(tags=["traceability templates"])


@router.post("/traceability-templates/upload", response_model=TraceabilityTemplateUploadResponse)
async def upload_traceability_template(project_id: int = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)) -> TraceabilityTemplateUploadResponse:
    try:
        return await ingest_traceability_template(db, project_id, file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/traceability-templates", response_model=list[TraceabilityTemplateDocumentRead])
def list_traceability_templates(project_id: int, db: Session = Depends(get_db)) -> list[TraceabilityTemplateDocument]:
    return list(db.scalars(select(TraceabilityTemplateDocument).where(
        TraceabilityTemplateDocument.project_id == project_id
    ).order_by(TraceabilityTemplateDocument.id.desc())).all())


@router.get("/traceability-templates/{template_id}", response_model=TraceabilityTemplateDocumentRead)
def get_traceability_template(template_id: int, db: Session = Depends(get_db)) -> TraceabilityTemplateDocument:
    return _document_or_404(db, template_id)


@router.get("/traceability-templates/{template_id}/preview", response_model=TraceabilityTemplatePreviewResponse)
def preview_traceability_template(template_id: int, db: Session = Depends(get_db)) -> TraceabilityTemplatePreviewResponse:
    document = _document_or_404(db, template_id)
    results = list(db.scalars(select(TraceabilityTemplateParseResult).where(
        TraceabilityTemplateParseResult.template_document_id == template_id
    ).order_by(TraceabilityTemplateParseResult.id)).all())
    return TraceabilityTemplatePreviewResponse(document=document, results=results)


@router.post("/traceability-templates/{template_id}/apply", response_model=TraceabilityTemplateApplyResponse)
def apply_traceability_template_api(template_id: int, db: Session = Depends(get_db)) -> TraceabilityTemplateApplyResponse:
    try:
        return TraceabilityTemplateApplyResponse(**summary_dict(apply_traceability_template(db, template_id)))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _document_or_404(db: Session, template_id: int) -> TraceabilityTemplateDocument:
    document = db.get(TraceabilityTemplateDocument, template_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Traceability template not found")
    return document
