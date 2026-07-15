from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.settings import get_settings
from app.models import MappingEvidenceReference, MappingVersion, MartField, MartToYbtMapping, Project, SourceToMartMapping, TargetField
from app.schemas import (
    MappingReviewRequest,
    MappingVersionCreate,
    MappingVersionRead,
    MartToYbtMappingCreate,
    MartToYbtMappingRead,
    MartToYbtMappingUpdate,
    SourceToMartMappingCreate,
    SourceToMartMappingRead,
    SourceToMartMappingUpdate,
)
from app.services.mapping.mart_to_ybt_generator import generate_mart_to_ybt_draft
from app.services.mapping.source_to_mart_generator import generate_source_to_mart_draft

router = APIRouter(tags=["mapping rules"])

VALID_STATUSES = {"draft", "reviewed", "approved", "rejected"}


@router.post("/mart-fields/{mart_field_id}/source-to-mart-mappings", response_model=SourceToMartMappingRead)
def create_source_to_mart_mapping(mart_field_id: int, payload: SourceToMartMappingCreate, db: Session = Depends(get_db)) -> SourceToMartMapping:
    mart_field = _get_mart_field_or_404(db, mart_field_id)
    mapping = SourceToMartMapping(project_id=mart_field.project_id, mart_field_id=mart_field.id, **payload.model_dump())
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return mapping


@router.get("/mart-fields/{mart_field_id}/source-to-mart-mappings", response_model=list[SourceToMartMappingRead])
def list_source_to_mart_mappings(mart_field_id: int, db: Session = Depends(get_db)) -> list[SourceToMartMapping]:
    _get_mart_field_or_404(db, mart_field_id)
    return list(db.scalars(select(SourceToMartMapping).where(SourceToMartMapping.mart_field_id == mart_field_id).order_by(SourceToMartMapping.id)).all())


@router.get("/source-to-mart-mappings/{mapping_id}", response_model=SourceToMartMappingRead)
def get_source_to_mart_mapping(mapping_id: int, db: Session = Depends(get_db)) -> SourceToMartMapping:
    return _get_source_to_mart_or_404(db, mapping_id)


@router.put("/source-to-mart-mappings/{mapping_id}", response_model=SourceToMartMappingRead)
def update_source_to_mart_mapping(mapping_id: int, payload: SourceToMartMappingUpdate, db: Session = Depends(get_db)) -> SourceToMartMapping:
    mapping = _get_source_to_mart_or_404(db, mapping_id)
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("mapping_status") in {"approved", "rejected"}:
        _reject_legacy_review(db, mapping.project_id)
    _validate_status(updates.get("mapping_status"))
    _apply_updates(mapping, updates)
    db.commit()
    db.refresh(mapping)
    return mapping


@router.delete("/source-to-mart-mappings/{mapping_id}")
def delete_source_to_mart_mapping(mapping_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    mapping = _get_source_to_mart_or_404(db, mapping_id)
    _delete_mapping_dependencies(db, "source_to_mart", mapping_id)
    db.delete(mapping)
    db.commit()
    return {"status": "deleted"}


@router.post("/source-to-mart-mappings/{mapping_id}/generate-draft", response_model=SourceToMartMappingRead)
async def generate_source_to_mart_mapping_draft(mapping_id: int, db: Session = Depends(get_db)) -> SourceToMartMapping:
    try:
        return await generate_source_to_mart_draft(db, mapping_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/source-to-mart-mappings/{mapping_id}/adopt-ai-draft", response_model=SourceToMartMappingRead)
def adopt_source_to_mart_draft(mapping_id: int, db: Session = Depends(get_db)) -> SourceToMartMapping:
    mapping = _get_source_to_mart_or_404(db, mapping_id)
    if not _has_text(mapping.ai_generated_content):
        raise HTTPException(status_code=400, detail="AI draft is empty")
    mapping.final_content = mapping.ai_generated_content
    mapping.mapping_status = "draft"
    db.commit()
    db.refresh(mapping)
    return mapping


@router.post("/source-to-mart-mappings/{mapping_id}/approve", response_model=SourceToMartMappingRead)
def approve_source_to_mart_mapping(mapping_id: int, payload: MappingReviewRequest | None = None, db: Session = Depends(get_db)) -> SourceToMartMapping:
    mapping = _get_source_to_mart_or_404(db, mapping_id)
    _reject_legacy_review(db, mapping.project_id)
    _approve_mapping(db, "source_to_mart", mapping, payload or MappingReviewRequest())
    db.commit()
    db.refresh(mapping)
    return mapping


@router.post("/source-to-mart-mappings/{mapping_id}/reject", response_model=SourceToMartMappingRead)
def reject_source_to_mart_mapping(mapping_id: int, payload: MappingReviewRequest | None = None, db: Session = Depends(get_db)) -> SourceToMartMapping:
    mapping = _get_source_to_mart_or_404(db, mapping_id)
    _reject_legacy_review(db, mapping.project_id)
    _reject_mapping(mapping, payload or MappingReviewRequest())
    db.commit()
    db.refresh(mapping)
    return mapping


@router.post("/source-to-mart-mappings/{mapping_id}/save-version", response_model=MappingVersionRead)
def save_source_to_mart_version(mapping_id: int, payload: MappingVersionCreate | None = None, db: Session = Depends(get_db)) -> MappingVersion:
    mapping = _get_source_to_mart_or_404(db, mapping_id)
    version = _create_version(db, "source_to_mart", mapping, payload or MappingVersionCreate())
    db.commit()
    db.refresh(version)
    return version


@router.post("/target-fields/{field_id}/mart-to-ybt-mappings", response_model=MartToYbtMappingRead)
def create_mart_to_ybt_mapping(field_id: int, payload: MartToYbtMappingCreate, db: Session = Depends(get_db)) -> MartToYbtMapping:
    target_field = _get_target_field_or_404(db, field_id)
    if payload.mart_field_id is not None:
        mart_field = _get_mart_field_or_404(db, payload.mart_field_id)
        if mart_field.project_id != target_field.project_id:
            raise HTTPException(status_code=400, detail="Mart field belongs to another project")
    mapping = MartToYbtMapping(project_id=target_field.project_id, target_field_id=target_field.id, **payload.model_dump())
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return mapping


@router.get("/target-fields/{field_id}/mart-to-ybt-mappings", response_model=list[MartToYbtMappingRead])
def list_mart_to_ybt_mappings(field_id: int, db: Session = Depends(get_db)) -> list[MartToYbtMapping]:
    _get_target_field_or_404(db, field_id)
    return list(db.scalars(select(MartToYbtMapping).where(MartToYbtMapping.target_field_id == field_id).order_by(MartToYbtMapping.id)).all())


@router.get("/mart-to-ybt-mappings/{mapping_id}", response_model=MartToYbtMappingRead)
def get_mart_to_ybt_mapping(mapping_id: int, db: Session = Depends(get_db)) -> MartToYbtMapping:
    return _get_mart_to_ybt_or_404(db, mapping_id)


@router.put("/mart-to-ybt-mappings/{mapping_id}", response_model=MartToYbtMappingRead)
def update_mart_to_ybt_mapping(mapping_id: int, payload: MartToYbtMappingUpdate, db: Session = Depends(get_db)) -> MartToYbtMapping:
    mapping = _get_mart_to_ybt_or_404(db, mapping_id)
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("mapping_status") in {"approved", "rejected"}:
        _reject_legacy_review(db, mapping.project_id)
    _validate_status(updates.get("mapping_status"))
    if updates.get("mart_field_id") is not None:
        mart_field = _get_mart_field_or_404(db, updates["mart_field_id"])
        if mart_field.project_id != mapping.project_id:
            raise HTTPException(status_code=400, detail="Mart field belongs to another project")
    _apply_updates(mapping, updates)
    db.commit()
    db.refresh(mapping)
    return mapping


@router.delete("/mart-to-ybt-mappings/{mapping_id}")
def delete_mart_to_ybt_mapping(mapping_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    mapping = _get_mart_to_ybt_or_404(db, mapping_id)
    _delete_mapping_dependencies(db, "mart_to_ybt", mapping_id)
    db.delete(mapping)
    db.commit()
    return {"status": "deleted"}


@router.post("/mart-to-ybt-mappings/{mapping_id}/generate-draft", response_model=MartToYbtMappingRead)
async def generate_mart_to_ybt_mapping_draft(mapping_id: int, db: Session = Depends(get_db)) -> MartToYbtMapping:
    try:
        return await generate_mart_to_ybt_draft(db, mapping_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/mart-to-ybt-mappings/{mapping_id}/adopt-ai-draft", response_model=MartToYbtMappingRead)
def adopt_mart_to_ybt_draft(mapping_id: int, db: Session = Depends(get_db)) -> MartToYbtMapping:
    mapping = _get_mart_to_ybt_or_404(db, mapping_id)
    if not _has_text(mapping.ai_generated_content):
        raise HTTPException(status_code=400, detail="AI draft is empty")
    mapping.final_content = mapping.ai_generated_content
    mapping.mapping_status = "draft"
    db.commit()
    db.refresh(mapping)
    return mapping


@router.post("/mart-to-ybt-mappings/{mapping_id}/approve", response_model=MartToYbtMappingRead)
def approve_mart_to_ybt_mapping(mapping_id: int, payload: MappingReviewRequest | None = None, db: Session = Depends(get_db)) -> MartToYbtMapping:
    mapping = _get_mart_to_ybt_or_404(db, mapping_id)
    _reject_legacy_review(db, mapping.project_id)
    _approve_mapping(db, "mart_to_ybt", mapping, payload or MappingReviewRequest())
    db.commit()
    db.refresh(mapping)
    return mapping


@router.post("/mart-to-ybt-mappings/{mapping_id}/reject", response_model=MartToYbtMappingRead)
def reject_mart_to_ybt_mapping(mapping_id: int, payload: MappingReviewRequest | None = None, db: Session = Depends(get_db)) -> MartToYbtMapping:
    mapping = _get_mart_to_ybt_or_404(db, mapping_id)
    _reject_legacy_review(db, mapping.project_id)
    _reject_mapping(mapping, payload or MappingReviewRequest())
    db.commit()
    db.refresh(mapping)
    return mapping


@router.post("/mart-to-ybt-mappings/{mapping_id}/save-version", response_model=MappingVersionRead)
def save_mart_to_ybt_version(mapping_id: int, payload: MappingVersionCreate | None = None, db: Session = Depends(get_db)) -> MappingVersion:
    mapping = _get_mart_to_ybt_or_404(db, mapping_id)
    version = _create_version(db, "mart_to_ybt", mapping, payload or MappingVersionCreate())
    db.commit()
    db.refresh(version)
    return version


def _get_mart_field_or_404(db: Session, field_id: int) -> MartField:
    field = db.get(MartField, field_id)
    if field is None:
        raise HTTPException(status_code=404, detail="Mart field not found")
    return field


def _get_target_field_or_404(db: Session, field_id: int) -> TargetField:
    field = db.get(TargetField, field_id)
    if field is None:
        raise HTTPException(status_code=404, detail="Target field not found")
    return field


def _get_source_to_mart_or_404(db: Session, mapping_id: int) -> SourceToMartMapping:
    mapping = db.get(SourceToMartMapping, mapping_id)
    if mapping is None:
        raise HTTPException(status_code=404, detail="Source-to-mart mapping not found")
    return mapping


def _get_mart_to_ybt_or_404(db: Session, mapping_id: int) -> MartToYbtMapping:
    mapping = db.get(MartToYbtMapping, mapping_id)
    if mapping is None:
        raise HTTPException(status_code=404, detail="Mart-to-YBT mapping not found")
    return mapping


def _apply_updates(model: object, values: dict) -> None:
    for key, value in values.items():
        setattr(model, key, value)


def _validate_status(status: str | None) -> None:
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid mapping_status")


def _approve_mapping(db: Session, mapping_type: str, mapping: SourceToMartMapping | MartToYbtMapping, payload: MappingReviewRequest) -> None:
    if payload.final_content is not None:
        mapping.final_content = payload.final_content
    if not _has_text(mapping.final_content):
        raise HTTPException(status_code=400, detail="final_content is required before approval")
    evidence_id = db.scalar(
        select(MappingEvidenceReference.id).where(
            MappingEvidenceReference.mapping_type == mapping_type,
            MappingEvidenceReference.mapping_id == mapping.id,
        ).limit(1)
    )
    if evidence_id is None:
        raise HTTPException(status_code=400, detail="At least one evidence reference is required before approval")
    mapping.mapping_status = "approved"
    mapping.reviewed_by = payload.reviewed_by
    mapping.reviewed_at = datetime.now(UTC)
    _create_version(
        db,
        mapping_type,
        mapping,
        MappingVersionCreate(
            content_snapshot=payload.final_content,
            change_note=payload.change_note or "审核通过自动保存版本",
            created_by=payload.reviewed_by,
        ),
    )


def _reject_mapping(mapping: SourceToMartMapping | MartToYbtMapping, payload: MappingReviewRequest) -> None:
    if payload.final_content is not None:
        mapping.final_content = payload.final_content
    mapping.mapping_status = "rejected"
    mapping.reviewed_by = payload.reviewed_by
    mapping.reviewed_at = datetime.now(UTC)


def _create_version(
    db: Session,
    mapping_type: str,
    mapping: SourceToMartMapping | MartToYbtMapping,
    payload: MappingVersionCreate,
) -> MappingVersion:
    snapshot = payload.content_snapshot or mapping.final_content or mapping.ai_generated_content or "暂无口径内容。"
    current_no = db.scalar(
        select(func.max(MappingVersion.version_no)).where(
            MappingVersion.mapping_type == mapping_type,
            MappingVersion.mapping_id == mapping.id,
        )
    )
    version = MappingVersion(
        project_id=mapping.project_id,
        mapping_type=mapping_type,
        mapping_id=mapping.id,
        version_no=(current_no or 0) + 1,
        content_snapshot=snapshot,
        change_note=payload.change_note,
        created_by=payload.created_by,
    )
    db.add(version)
    db.flush()
    return version


def _delete_mapping_dependencies(db: Session, mapping_type: str, mapping_id: int) -> None:
    for model in (MappingEvidenceReference, MappingVersion):
        rows = db.scalars(select(model).where(model.mapping_type == mapping_type, model.mapping_id == mapping_id)).all()
        for row in rows:
            db.delete(row)


def _has_text(value: str | None) -> bool:
    return bool(value and value.strip())


def _reject_legacy_review(db: Session, project_id: int) -> None:
    project = db.get(Project, project_id)
    if get_settings().auth_mode == "required" or bool(project and project.governance_workflow_enabled):
        raise HTTPException(status_code=409, detail="Mapping review must be completed through the current review task")
