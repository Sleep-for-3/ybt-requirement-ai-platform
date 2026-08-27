from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import (
    DataQualityExpectation,
    DataQualityExpectationBinding,
    FieldMappingDraft,
    MartToYbtMapping,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    SourceToMartMapping,
    TargetField,
    UatCase,
)
from app.schemas.quality import (
    QualityExpectationBindingCreate,
    QualityExpectationBindingRead,
    QualityExpectationCreate,
    QualityExpectationRead,
    QualityExpectationStatusTransition,
)
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.governance.audit import record_audit


router = APIRouter(tags=["data quality expectations"])

_SCOPE_MODELS = {
    "requirement": {
        "target_field": TargetField,
        "field_mapping_draft": FieldMappingDraft,
        "scenario_business_mapping": ScenarioBusinessMapping,
    },
    "mapping": {
        "source_to_mart_mapping": SourceToMartMapping,
        "mart_to_ybt_mapping": MartToYbtMapping,
        "scenario_business_mapping": ScenarioBusinessMapping,
        "scenario_technical_lineage": ScenarioTechnicalLineage,
    },
    "uat": {"uat_case": UatCase},
    "monitoring": {"monitoring_target": None},
}


@router.get(
    "/projects/{project_id}/quality-expectations",
    response_model=list[QualityExpectationRead],
)
def list_quality_expectations(
    project_id: int,
    principal: CurrentPrincipal,
    status: str | None = Query(default=None),
    rule_type: str | None = Query(default=None),
    scope_type: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    entity_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
) -> list[dict]:
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    statement = select(DataQualityExpectation).where(DataQualityExpectation.project_id == project_id)
    if status:
        statement = statement.where(DataQualityExpectation.status == status)
    if rule_type:
        statement = statement.where(DataQualityExpectation.rule_type == rule_type)
    if scope_type or entity_type or entity_id:
        binding_scope = select(DataQualityExpectationBinding.id).where(
            DataQualityExpectationBinding.expectation_id == DataQualityExpectation.id,
            DataQualityExpectationBinding.project_id == project_id,
        )
        if scope_type:
            binding_scope = binding_scope.where(DataQualityExpectationBinding.scope_type == scope_type)
        if entity_type:
            binding_scope = binding_scope.where(DataQualityExpectationBinding.entity_type == entity_type)
        if entity_id:
            binding_scope = binding_scope.where(DataQualityExpectationBinding.entity_id == entity_id)
        statement = statement.where(exists(binding_scope))
    rows = list(db.scalars(statement.order_by(DataQualityExpectation.id.desc())).all())
    return [_expectation_detail(db, item) for item in rows]


@router.post(
    "/projects/{project_id}/quality-expectations",
    response_model=QualityExpectationRead,
    status_code=201,
)
def create_quality_expectation(
    project_id: int,
    payload: QualityExpectationCreate,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> dict:
    project = PermissionService(db, principal).require_project_permission(project_id, "project.manage")
    values = payload.model_dump(exclude={"bindings"})
    expectation = DataQualityExpectation(
        project_id=project_id,
        rule_code=values["rule_code"].upper(),
        rule_name=values["rule_name"],
        description=values["description"],
        rule_type=values["rule_type"],
        expression=values["expression"],
        parameters_json=values["parameters_json"],
        severity=values["severity"],
        status=values["status"],
        source_type=values["source_type"],
        source_id=values["source_id"],
        confidence_level=values["confidence_level"],
        created_by=principal.username,
    )
    db.add(expectation)
    try:
        db.flush()
        for binding in payload.bindings:
            _create_binding(db, project_id, expectation.id, binding)
    except (IntegrityError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=409 if isinstance(exc, IntegrityError) else 422, detail=str(exc)) from exc
    record_audit(
        db,
        action="create_data_quality_expectation",
        resource_type="data_quality_expectation",
        resource_id=expectation.id,
        actor_user_id=principal.user_id,
        institution_id=project.institution_id,
        project_id=project_id,
        after={"rule_type": expectation.rule_type, "status": expectation.status, "binding_count": len(payload.bindings)},
    )
    db.commit()
    return _expectation_detail(db, expectation)


@router.get("/quality-expectations/{expectation_id}", response_model=QualityExpectationRead)
def get_quality_expectation(
    expectation_id: int,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> dict:
    expectation = PermissionService(db, principal).load_project_resource_or_404(
        DataQualityExpectation, expectation_id, "project.view"
    )
    return _expectation_detail(db, expectation)


@router.post(
    "/quality-expectations/{expectation_id}/bindings",
    response_model=QualityExpectationBindingRead,
    status_code=201,
)
def add_quality_expectation_binding(
    expectation_id: int,
    payload: QualityExpectationBindingCreate,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> DataQualityExpectationBinding:
    expectation = PermissionService(db, principal).load_project_resource_or_404(
        DataQualityExpectation, expectation_id, "project.manage"
    )
    try:
        binding = _create_binding(db, expectation.project_id, expectation.id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_audit(
        db,
        action="bind_data_quality_expectation",
        resource_type="data_quality_expectation",
        resource_id=expectation.id,
        actor_user_id=principal.user_id,
        project_id=expectation.project_id,
        after={"binding_id": binding.id, "scope_type": binding.scope_type, "entity_type": binding.entity_type, "entity_id": binding.entity_id},
    )
    db.commit()
    db.refresh(binding)
    return binding


@router.post("/quality-expectations/{expectation_id}/status", response_model=QualityExpectationRead)
def transition_quality_expectation(
    expectation_id: int,
    payload: QualityExpectationStatusTransition,
    principal: CurrentPrincipal,
    db: Session = Depends(get_db),
) -> dict:
    expectation = PermissionService(db, principal).load_project_resource_or_404(
        DataQualityExpectation, expectation_id, "project.manage"
    )
    if expectation.status == "retired":
        raise HTTPException(status_code=409, detail="Retired quality expectations cannot be transitioned")
    if payload.status == "confirmed" and expectation.status not in {"draft", "ai_suggested"}:
        raise HTTPException(status_code=409, detail="Only a draft or AI suggestion can be confirmed")
    before_status = expectation.status
    expectation.status = payload.status
    expectation.status_reason = payload.comment
    if payload.status == "confirmed":
        expectation.confirmed_by = principal.username
        expectation.confirmed_at = datetime.now(UTC)
    record_audit(
        db,
        action="transition_data_quality_expectation",
        resource_type="data_quality_expectation",
        resource_id=expectation.id,
        actor_user_id=principal.user_id,
        project_id=expectation.project_id,
        before={"status": before_status},
        after={"status": payload.status, "comment_provided": bool(payload.comment)},
    )
    db.commit()
    return _expectation_detail(db, expectation)


def _create_binding(
    db: Session,
    project_id: int,
    expectation_id: int,
    payload: QualityExpectationBindingCreate,
) -> DataQualityExpectationBinding:
    allowed_entities = _SCOPE_MODELS[payload.scope_type]
    model = allowed_entities.get(payload.entity_type)
    if payload.entity_type not in allowed_entities:
        raise ValueError(f"{payload.entity_type} cannot be used for {payload.scope_type} quality scope")
    if model is None:
        if payload.entity_id is not None or not payload.entity_key:
            raise ValueError("monitoring_target requires entity_key and does not accept entity_id")
    else:
        if payload.entity_id is None or payload.entity_key:
            raise ValueError(f"{payload.entity_type} requires entity_id and does not accept entity_key")
        entity = db.get(model, payload.entity_id)
        if entity is None or entity.project_id != project_id:
            raise ValueError("quality binding target does not belong to the project")
    duplicate = db.scalar(select(DataQualityExpectationBinding.id).where(
        DataQualityExpectationBinding.expectation_id == expectation_id,
        DataQualityExpectationBinding.scope_type == payload.scope_type,
        DataQualityExpectationBinding.entity_type == payload.entity_type,
        DataQualityExpectationBinding.entity_id == payload.entity_id,
        DataQualityExpectationBinding.entity_key == payload.entity_key,
        DataQualityExpectationBinding.binding_status == "active",
    ))
    if duplicate is not None:
        raise ValueError("active quality expectation binding already exists")
    binding = DataQualityExpectationBinding(
        project_id=project_id,
        expectation_id=expectation_id,
        scope_type=payload.scope_type,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        entity_key=payload.entity_key,
        configuration_json=payload.configuration_json,
    )
    db.add(binding)
    db.flush()
    return binding


def _expectation_detail(db: Session, expectation: DataQualityExpectation) -> dict:
    bindings = list(db.scalars(select(DataQualityExpectationBinding).where(
        DataQualityExpectationBinding.expectation_id == expectation.id,
        DataQualityExpectationBinding.project_id == expectation.project_id,
    ).order_by(DataQualityExpectationBinding.id)).all())
    return {
        "id": expectation.id,
        "project_id": expectation.project_id,
        "rule_code": expectation.rule_code,
        "rule_name": expectation.rule_name,
        "description": expectation.description,
        "rule_type": expectation.rule_type,
        "expression": expectation.expression,
        "parameters_json": expectation.parameters_json or {},
        "severity": expectation.severity,
        "status": expectation.status,
        "source_type": expectation.source_type,
        "source_id": expectation.source_id,
        "confidence_level": expectation.confidence_level,
        "created_by": expectation.created_by,
        "confirmed_by": expectation.confirmed_by,
        "confirmed_at": expectation.confirmed_at,
        "status_reason": expectation.status_reason,
        "created_at": expectation.created_at,
        "updated_at": expectation.updated_at,
        "bindings": [
            {
                "id": item.id,
                "project_id": item.project_id,
                "expectation_id": item.expectation_id,
                "scope_type": item.scope_type,
                "entity_type": item.entity_type,
                "entity_id": item.entity_id,
                "entity_key": item.entity_key,
                "binding_status": item.binding_status,
                "configuration_json": item.configuration_json or {},
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
            for item in bindings
        ],
    }
