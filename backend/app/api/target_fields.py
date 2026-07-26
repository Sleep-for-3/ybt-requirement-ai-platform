from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.models import FieldMappingDraft, TargetField
from app.schemas import FieldMappingDraftRead, GenerateMappingRequest, GenerateMappingResponse, ReviewDraftRequest, TargetFieldCreate, TargetFieldRead
from app.services.mapping_generator import generate_mapping_draft

router = APIRouter(prefix="/fields", tags=["fields"])


@router.get("", response_model=list[TargetFieldRead])
def list_fields(
    project_id: int,
    target_table_id: int | None = None,
    db: Session = Depends(get_db),
) -> list[TargetField]:
    statement = select(TargetField).where(TargetField.project_id == project_id)
    if target_table_id:
        statement = statement.where(TargetField.target_table_id == target_table_id)
    return list(db.scalars(statement.order_by(TargetField.id)).all())


@router.post("", response_model=TargetFieldRead)
def create_field(payload: TargetFieldCreate, db: Session = Depends(get_db)) -> TargetField:
    field = TargetField(**payload.model_dump())
    db.add(field)
    db.commit()
    db.refresh(field)
    return field


@router.get("/{field_id}", response_model=TargetFieldRead)
def get_field(field_id: int, db: Session = Depends(get_db)) -> TargetField:
    field = db.get(TargetField, field_id)
    if field is None:
        raise HTTPException(status_code=404, detail="Target field not found")
    return field


@router.post("/{field_id}/generate-mapping", response_model=GenerateMappingResponse)
async def generate_mapping(field_id: int, payload: GenerateMappingRequest | None = None, db: Session = Depends(get_db)) -> GenerateMappingResponse:
    try:
        return await generate_mapping_draft(db, field_id=field_id, options=payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{field_id}/drafts/latest", response_model=FieldMappingDraftRead | None)
def get_latest_draft(field_id: int, db: Session = Depends(get_db)) -> FieldMappingDraft | None:
    statement = (
        select(FieldMappingDraft)
        .options(selectinload(FieldMappingDraft.evidences))
        .where(FieldMappingDraft.target_field_id == field_id)
        .order_by(FieldMappingDraft.id.desc())
        .limit(1)
    )
    return db.execute(statement).scalar_one_or_none()


@router.patch("/drafts/{draft_id}/review", response_model=FieldMappingDraftRead)
def review_draft(draft_id: int, payload: ReviewDraftRequest, db: Session = Depends(get_db)) -> FieldMappingDraft:
    draft = db.get(FieldMappingDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    if payload.review_status not in {"pending", "approved", "rejected", "revised"}:
        raise HTTPException(status_code=400, detail="Invalid review_status")
    draft.review_status = payload.review_status
    if payload.final_content is not None:
        draft.final_content = payload.final_content
    db.commit()
    statement = select(FieldMappingDraft).options(selectinload(FieldMappingDraft.evidences)).where(FieldMappingDraft.id == draft.id)
    return db.execute(statement).scalar_one()
