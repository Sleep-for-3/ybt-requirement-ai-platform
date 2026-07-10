from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import MappingEvidenceReference, MartToYbtMapping, ScenarioBusinessMapping, ScenarioTechnicalLineage, SourceToMartMapping
from app.schemas import MappingEvidenceCreate, MappingEvidenceRead

router = APIRouter(tags=["mapping evidence"])

VALID_MAPPING_TYPES = {"source_to_mart", "mart_to_ybt", "scenario_business", "scenario_technical"}


@router.post("/mappings/{mapping_type}/{mapping_id}/evidence", response_model=MappingEvidenceRead)
def create_mapping_evidence(
    mapping_type: str,
    mapping_id: int,
    payload: MappingEvidenceCreate,
    db: Session = Depends(get_db),
) -> MappingEvidenceReference:
    if payload.evidence_type not in MappingEvidenceReference.supported_types():
        raise HTTPException(status_code=400, detail="Unsupported evidence_type")
    project_id = _mapping_project_id(db, mapping_type, mapping_id)
    evidence = MappingEvidenceReference(
        project_id=project_id,
        mapping_type=mapping_type,
        mapping_id=mapping_id,
        **payload.model_dump(),
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return evidence


@router.get("/mappings/{mapping_type}/{mapping_id}/evidence", response_model=list[MappingEvidenceRead])
def list_mapping_evidence(mapping_type: str, mapping_id: int, db: Session = Depends(get_db)) -> list[MappingEvidenceReference]:
    _mapping_project_id(db, mapping_type, mapping_id)
    return list(
        db.scalars(
            select(MappingEvidenceReference)
            .where(
                MappingEvidenceReference.mapping_type == mapping_type,
                MappingEvidenceReference.mapping_id == mapping_id,
            )
            .order_by(MappingEvidenceReference.id)
        ).all()
    )


@router.delete("/mapping-evidence/{evidence_id}")
def delete_mapping_evidence(evidence_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    evidence = db.get(MappingEvidenceReference, evidence_id)
    if evidence is None:
        raise HTTPException(status_code=404, detail="Mapping evidence not found")
    db.delete(evidence)
    db.commit()
    return {"status": "deleted"}


def _mapping_project_id(db: Session, mapping_type: str, mapping_id: int) -> int:
    if mapping_type not in VALID_MAPPING_TYPES:
        raise HTTPException(status_code=400, detail="Invalid mapping_type")
    if mapping_type == "source_to_mart":
        mapping = db.get(SourceToMartMapping, mapping_id)
    elif mapping_type == "mart_to_ybt":
        mapping = db.get(MartToYbtMapping, mapping_id)
    elif mapping_type == "scenario_business":
        mapping = db.get(ScenarioBusinessMapping, mapping_id)
    else:
        mapping = db.get(ScenarioTechnicalLineage, mapping_id)
    if mapping is None:
        raise HTTPException(status_code=404, detail="Mapping not found")
    return mapping.project_id
