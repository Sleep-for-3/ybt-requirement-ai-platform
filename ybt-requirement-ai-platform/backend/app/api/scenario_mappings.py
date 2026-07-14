from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import MappingEvidenceReference, ProductScenario, ScenarioBusinessMapping, ScenarioTechnicalLineage, TargetField
from app.schemas import (
    ConfirmMappingRequest,
    ScenarioBusinessMappingCreate,
    ScenarioBusinessMappingRead,
    ScenarioBusinessMappingUpdate,
    ScenarioTechnicalLineageCreate,
    ScenarioTechnicalLineageRead,
    ScenarioTechnicalLineageUpdate,
)
from app.services.mapping.scenario_draft_generator import generate_business_draft, generate_technical_draft

router = APIRouter(tags=["scenario mappings"])

PROCESSING_LOGIC_TYPES = {
    "direct", "default_value", "code_mapping", "concatenate", "calculate", "conditional",
    "manual_supplement", "external_data", "pending_confirmation",
}
CONFIRM_STATUSES = {"draft", "pending", "confirmed", "rejected"}


@router.post("/target-fields/{field_id}/scenarios/{scenario_id}/business-mapping", response_model=ScenarioBusinessMappingRead)
def create_business_mapping(field_id: int, scenario_id: int, payload: ScenarioBusinessMappingCreate, db: Session = Depends(get_db)) -> ScenarioBusinessMapping:
    field, scenario = _field_and_scenario(db, field_id, scenario_id)
    mapping = ScenarioBusinessMapping(project_id=field.project_id, target_field_id=field.id, scenario_id=scenario.id, **payload.model_dump())
    db.add(mapping)
    _commit_unique(db, "Business mapping already exists for this field and scenario")
    db.refresh(mapping)
    return mapping


@router.get("/target-fields/{field_id}/scenario-business-mappings", response_model=list[ScenarioBusinessMappingRead])
def list_business_mappings(field_id: int, db: Session = Depends(get_db)) -> list[ScenarioBusinessMapping]:
    _field_or_404(db, field_id)
    return list(db.scalars(select(ScenarioBusinessMapping).where(ScenarioBusinessMapping.target_field_id == field_id).order_by(ScenarioBusinessMapping.scenario_id)).all())


@router.get("/scenario-business-mappings/{mapping_id}", response_model=ScenarioBusinessMappingRead)
def get_business_mapping(mapping_id: int, db: Session = Depends(get_db)) -> ScenarioBusinessMapping:
    return _business_or_404(db, mapping_id)


@router.put("/scenario-business-mappings/{mapping_id}", response_model=ScenarioBusinessMappingRead)
def update_business_mapping(mapping_id: int, payload: ScenarioBusinessMappingUpdate, db: Session = Depends(get_db)) -> ScenarioBusinessMapping:
    mapping = _business_or_404(db, mapping_id)
    updates = payload.model_dump(exclude_unset=True)
    _validate_confirm_status(updates.get("business_confirm_status"))
    _apply(mapping, updates)
    db.commit()
    db.refresh(mapping)
    return mapping


@router.delete("/scenario-business-mappings/{mapping_id}")
def delete_business_mapping(mapping_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    mapping = _business_or_404(db, mapping_id)
    db.delete(mapping)
    db.commit()
    return {"status": "deleted"}


@router.post("/scenario-business-mappings/{mapping_id}/adopt-ai-draft", response_model=ScenarioBusinessMappingRead)
def adopt_business_draft(mapping_id: int, db: Session = Depends(get_db)) -> ScenarioBusinessMapping:
    mapping = _business_or_404(db, mapping_id)
    if not _has_text(mapping.ai_generated_content):
        raise HTTPException(status_code=400, detail="AI draft is empty")
    mapping.final_content = mapping.ai_generated_content
    mapping.business_confirm_status = "draft"
    db.commit()
    db.refresh(mapping)
    return mapping


@router.post("/scenario-business-mappings/{mapping_id}/generate-draft", response_model=ScenarioBusinessMappingRead)
async def generate_scenario_business_draft(mapping_id: int, db: Session = Depends(get_db)) -> ScenarioBusinessMapping:
    try:
        return await generate_business_draft(db, mapping_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/scenario-business-mappings/{mapping_id}/confirm", response_model=ScenarioBusinessMappingRead)
def confirm_business_mapping(mapping_id: int, payload: ConfirmMappingRequest | None = None, db: Session = Depends(get_db)) -> ScenarioBusinessMapping:
    mapping = _business_or_404(db, mapping_id)
    if not (_has_text(mapping.business_definition) or _has_text(mapping.final_content)):
        raise HTTPException(status_code=400, detail="Business definition or final content is required before confirmation")
    _require_evidence(db, "scenario_business", mapping.id)
    mapping.business_confirm_status = "confirmed"
    mapping.business_confirm_at = datetime.now(UTC)
    if payload and payload.confirmed_by:
        mapping.business_owner = payload.confirmed_by
    db.commit()
    db.refresh(mapping)
    return mapping


@router.post("/scenario-business-mappings/{mapping_id}/reject", response_model=ScenarioBusinessMappingRead)
def reject_business_mapping(mapping_id: int, db: Session = Depends(get_db)) -> ScenarioBusinessMapping:
    mapping = _business_or_404(db, mapping_id)
    mapping.business_confirm_status = "rejected"
    mapping.business_confirm_at = datetime.now(UTC)
    db.commit()
    db.refresh(mapping)
    return mapping


@router.post("/target-fields/{field_id}/scenarios/{scenario_id}/technical-lineage", response_model=ScenarioTechnicalLineageRead)
def create_technical_lineage(field_id: int, scenario_id: int, payload: ScenarioTechnicalLineageCreate, db: Session = Depends(get_db)) -> ScenarioTechnicalLineage:
    field, scenario = _field_and_scenario(db, field_id, scenario_id)
    _validate_logic_type(payload.processing_logic_type)
    if payload.business_mapping_id is not None:
        business = _business_or_404(db, payload.business_mapping_id)
        if business.target_field_id != field.id or business.scenario_id != scenario.id:
            raise HTTPException(status_code=400, detail="Business mapping belongs to another field or scenario")
    lineage = ScenarioTechnicalLineage(project_id=field.project_id, target_field_id=field.id, scenario_id=scenario.id, **payload.model_dump())
    db.add(lineage)
    _commit_unique(db, "Technical lineage already exists for this field and scenario")
    db.refresh(lineage)
    return lineage


@router.get("/target-fields/{field_id}/scenario-technical-lineages", response_model=list[ScenarioTechnicalLineageRead])
def list_technical_lineages(field_id: int, db: Session = Depends(get_db)) -> list[ScenarioTechnicalLineage]:
    _field_or_404(db, field_id)
    return list(db.scalars(select(ScenarioTechnicalLineage).where(ScenarioTechnicalLineage.target_field_id == field_id).order_by(ScenarioTechnicalLineage.scenario_id)).all())


@router.get("/scenario-technical-lineages/{lineage_id}", response_model=ScenarioTechnicalLineageRead)
def get_technical_lineage(lineage_id: int, db: Session = Depends(get_db)) -> ScenarioTechnicalLineage:
    return _lineage_or_404(db, lineage_id)


@router.put("/scenario-technical-lineages/{lineage_id}", response_model=ScenarioTechnicalLineageRead)
def update_technical_lineage(lineage_id: int, payload: ScenarioTechnicalLineageUpdate, db: Session = Depends(get_db)) -> ScenarioTechnicalLineage:
    lineage = _lineage_or_404(db, lineage_id)
    _validate_logic_type(payload.processing_logic_type)
    updates = payload.model_dump(exclude_unset=True)
    _validate_confirm_status(updates.get("tech_confirm_status"))
    _apply(lineage, updates)
    db.commit()
    db.refresh(lineage)
    return lineage


@router.delete("/scenario-technical-lineages/{lineage_id}")
def delete_technical_lineage(lineage_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    lineage = _lineage_or_404(db, lineage_id)
    db.delete(lineage)
    db.commit()
    return {"status": "deleted"}


@router.post("/scenario-technical-lineages/{lineage_id}/adopt-ai-draft", response_model=ScenarioTechnicalLineageRead)
def adopt_technical_draft(lineage_id: int, db: Session = Depends(get_db)) -> ScenarioTechnicalLineage:
    lineage = _lineage_or_404(db, lineage_id)
    if not _has_text(lineage.ai_generated_content):
        raise HTTPException(status_code=400, detail="AI draft is empty")
    lineage.final_content = lineage.ai_generated_content
    lineage.tech_confirm_status = "draft"
    db.commit()
    db.refresh(lineage)
    return lineage


@router.post("/scenario-technical-lineages/{lineage_id}/generate-draft", response_model=ScenarioTechnicalLineageRead)
async def generate_scenario_technical_draft(lineage_id: int, db: Session = Depends(get_db)) -> ScenarioTechnicalLineage:
    try:
        return await generate_technical_draft(db, lineage_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/scenario-technical-lineages/{lineage_id}/confirm", response_model=ScenarioTechnicalLineageRead)
def confirm_technical_lineage(lineage_id: int, payload: ConfirmMappingRequest | None = None, db: Session = Depends(get_db)) -> ScenarioTechnicalLineage:
    lineage = _lineage_or_404(db, lineage_id)
    missing = []
    if not _has_text(lineage.source_system_name):
        missing.append("source_system_name")
    if not _has_text(lineage.processing_logic_type):
        missing.append("processing_logic_type")
    if not (_has_text(lineage.final_content) or _has_text(lineage.processing_logic)):
        missing.append("final_content_or_processing_logic")
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing fields before confirmation: {', '.join(missing)}")
    _require_evidence(db, "scenario_technical", lineage.id)
    lineage.tech_confirm_status = "confirmed"
    lineage.tech_confirm_at = datetime.now(UTC)
    if payload and payload.confirmed_by:
        lineage.tech_owner = payload.confirmed_by
    db.commit()
    db.refresh(lineage)
    return lineage


@router.post("/scenario-technical-lineages/{lineage_id}/reject", response_model=ScenarioTechnicalLineageRead)
def reject_technical_lineage(lineage_id: int, db: Session = Depends(get_db)) -> ScenarioTechnicalLineage:
    lineage = _lineage_or_404(db, lineage_id)
    lineage.tech_confirm_status = "rejected"
    lineage.tech_confirm_at = datetime.now(UTC)
    db.commit()
    db.refresh(lineage)
    return lineage


def _field_and_scenario(db: Session, field_id: int, scenario_id: int) -> tuple[TargetField, ProductScenario]:
    field = _field_or_404(db, field_id)
    scenario = db.get(ProductScenario, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    if scenario.project_id != field.project_id:
        raise HTTPException(status_code=400, detail="Scenario belongs to another project")
    return field, scenario


def _field_or_404(db: Session, field_id: int) -> TargetField:
    field = db.get(TargetField, field_id)
    if field is None:
        raise HTTPException(status_code=404, detail="Target field not found")
    return field


def _business_or_404(db: Session, mapping_id: int) -> ScenarioBusinessMapping:
    mapping = db.get(ScenarioBusinessMapping, mapping_id)
    if mapping is None:
        raise HTTPException(status_code=404, detail="Scenario business mapping not found")
    return mapping


def _lineage_or_404(db: Session, lineage_id: int) -> ScenarioTechnicalLineage:
    lineage = db.get(ScenarioTechnicalLineage, lineage_id)
    if lineage is None:
        raise HTTPException(status_code=404, detail="Scenario technical lineage not found")
    return lineage


def _validate_logic_type(value: str | None) -> None:
    if value is not None and value not in PROCESSING_LOGIC_TYPES:
        raise HTTPException(status_code=400, detail="Invalid processing_logic_type")


def _validate_confirm_status(value: str | None) -> None:
    if value is not None and value not in CONFIRM_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid confirmation status")
    if value == "confirmed":
        raise HTTPException(status_code=400, detail="Use the confirmation endpoint so quality checks cannot be bypassed")


def _apply(model: object, values: dict) -> None:
    for key, value in values.items():
        setattr(model, key, value)


def _has_text(value: str | None) -> bool:
    return bool(value and value.strip())


def _require_evidence(db: Session, mapping_type: str, mapping_id: int) -> None:
    evidence_id = db.scalar(select(MappingEvidenceReference.id).where(
        MappingEvidenceReference.mapping_type == mapping_type,
        MappingEvidenceReference.mapping_id == mapping_id,
    ).limit(1))
    if evidence_id is None:
        raise HTTPException(status_code=400, detail="At least one evidence reference is required before confirmation")


def _commit_unique(db: Session, detail: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=detail) from exc
