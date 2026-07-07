from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import KnowledgeDocument
from app.schemas import KnowledgeDocumentRead
from app.services.document_ingestion import ingest_document

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[KnowledgeDocumentRead])
def list_documents(project_id: int, db: Session = Depends(get_db)) -> list[KnowledgeDocument]:
    return list(
        db.scalars(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.project_id == project_id)
            .order_by(KnowledgeDocument.id.desc())
        ).all()
    )


@router.post("/upload", response_model=KnowledgeDocumentRead)
async def upload_document(
    project_id: int = Form(...),
    source_type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> KnowledgeDocument:
    try:
        document, _chunks = await ingest_document(db, project_id, source_type, file)
        return document
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
