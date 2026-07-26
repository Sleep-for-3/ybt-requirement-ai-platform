from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import inspect as sa_inspect, or_, select
from sqlalchemy.orm import Session

from app.models import (
    CatalogColumn,
    MappingEvidenceReference,
    ProductScenario,
    ReviewDecision,
    ReviewTask,
    ScenarioBusinessMapping,
    ScenarioReviewPackage,
    ScenarioTechnicalLineage,
    TargetField,
    WorkflowInstance,
)


def get_or_create_review_package(
    db: Session,
    *,
    project_id: int,
    target_field_id: int,
    scenario_id: int,
    created_by: int,
) -> ScenarioReviewPackage:
    existing = db.scalar(select(ScenarioReviewPackage).where(
        ScenarioReviewPackage.project_id == project_id,
        ScenarioReviewPackage.target_field_id == target_field_id,
        ScenarioReviewPackage.scenario_id == scenario_id,
    ))
    field = db.get(TargetField, target_field_id)
    scenario = db.get(ProductScenario, scenario_id)
    if field is None or field.project_id != project_id or scenario is None or scenario.project_id != project_id:
        raise HTTPException(status_code=404, detail="Field scenario was not found in this project")
    business = db.scalar(select(ScenarioBusinessMapping).where(
        ScenarioBusinessMapping.project_id == project_id,
        ScenarioBusinessMapping.target_field_id == target_field_id,
        ScenarioBusinessMapping.scenario_id == scenario_id,
    ))
    technical = db.scalar(select(ScenarioTechnicalLineage).where(
        ScenarioTechnicalLineage.project_id == project_id,
        ScenarioTechnicalLineage.target_field_id == target_field_id,
        ScenarioTechnicalLineage.scenario_id == scenario_id,
    ))
    if business is None or technical is None:
        raise HTTPException(status_code=409, detail="Business mapping and technical lineage must be saved before review submission")
    if technical.business_mapping_id not in {None, business.id}:
        raise HTTPException(status_code=409, detail="Technical lineage is bound to a different business mapping")
    if existing:
        if existing.business_mapping_id != business.id or existing.technical_lineage_id != technical.id:
            existing.business_mapping_id = business.id
            existing.technical_lineage_id = technical.id
        return existing
    package = ScenarioReviewPackage(
        project_id=project_id,
        target_field_id=target_field_id,
        scenario_id=scenario_id,
        business_mapping_id=business.id,
        technical_lineage_id=technical.id,
        status="draft",
        current_version_no=1,
        created_by=created_by,
    )
    db.add(package)
    db.flush()
    return package


def validate_review_package(db: Session, project_id: int, package_id: int) -> ScenarioReviewPackage:
    package = db.get(ScenarioReviewPackage, package_id)
    if package is None or package.project_id != project_id:
        raise HTTPException(status_code=404, detail="Scenario review package not found")
    business = db.get(ScenarioBusinessMapping, package.business_mapping_id)
    technical = db.get(ScenarioTechnicalLineage, package.technical_lineage_id)
    expected = (package.project_id, package.target_field_id, package.scenario_id)
    if business is None or technical is None:
        raise HTTPException(status_code=409, detail="Scenario review package content no longer exists")
    if (business.project_id, business.target_field_id, business.scenario_id) != expected:
        raise HTTPException(status_code=409, detail="Business mapping does not belong to the review package scope")
    if (technical.project_id, technical.target_field_id, technical.scenario_id) != expected:
        raise HTTPException(status_code=409, detail="Technical lineage does not belong to the review package scope")
    return package


def snapshot_review_step(
    db: Session,
    package: ScenarioReviewPackage,
    step_key: str,
    workflow_instance_id: int,
) -> dict[str, Any]:
    business = db.get(ScenarioBusinessMapping, package.business_mapping_id)
    technical = db.get(ScenarioTechnicalLineage, package.technical_lineage_id)
    business_snapshot = _row_snapshot(business)
    technical_snapshot = _row_snapshot(technical)
    business_evidence = _evidence(db, "scenario_business", package.business_mapping_id)
    technical_evidence = _evidence(db, "scenario_technical", package.technical_lineage_id)
    base = {
        "scenario_review_package_id": package.id,
        "package_version_no": package.current_version_no,
        "project_id": package.project_id,
        "target_field_id": package.target_field_id,
        "scenario_id": package.scenario_id,
    }
    if step_key == "business_draft":
        return {**base, "business_mapping_id": package.business_mapping_id, "business_mapping": business_snapshot}
    if step_key == "business_review":
        return {
            **base,
            "business_mapping_id": package.business_mapping_id,
            "business_mapping": business_snapshot,
            "evidence_summary": business_evidence,
        }
    if step_key == "technical_draft":
        return {**base, "technical_lineage_id": package.technical_lineage_id, "technical_lineage": technical_snapshot}
    source_catalog_fields = _source_catalog_fields(db, technical)
    if step_key == "technical_review":
        return {
            **base,
            "technical_lineage_id": package.technical_lineage_id,
            "technical_lineage": technical_snapshot,
            "source_catalog_fields": source_catalog_fields,
            "profile_evidence_summary": [item for item in technical_evidence if item["evidence_type"] in {"column_profile", "profile_snapshot"}],
            "evidence_summary": technical_evidence,
        }
    prior = db.execute(select(ReviewDecision, ReviewTask.step_key).join(
        ReviewTask, ReviewTask.id == ReviewDecision.review_task_id,
    ).where(
        ReviewTask.workflow_instance_id == workflow_instance_id,
    ).order_by(ReviewDecision.id)).all()
    return {
        **base,
        "business_mapping_id": package.business_mapping_id,
        "business_mapping": business_snapshot,
        "technical_lineage_id": package.technical_lineage_id,
        "technical_lineage": technical_snapshot,
        "source_catalog_fields": source_catalog_fields,
        "evidence_summary": business_evidence + technical_evidence,
        "open_questions": {
            "business": business.open_questions,
            "technical": technical.open_questions,
        },
        "prior_decisions": [
            {
                "decision_id": decision.id,
                "step_key": step,
                "decision": decision.decision,
                "comment": decision.comment,
                "decided_by": decision.decided_by,
                "decided_at": _json_value(decision.decided_at),
            }
            for decision, step in prior
        ],
    }


def finalize_review_package(db: Session, package: ScenarioReviewPackage) -> None:
    business = db.get(ScenarioBusinessMapping, package.business_mapping_id)
    technical = db.get(ScenarioTechnicalLineage, package.technical_lineage_id)
    now = datetime.now(UTC)
    business.business_confirm_status = "confirmed"
    business.business_confirm_at = now
    technical.tech_confirm_status = "confirmed"
    technical.tech_confirm_at = now
    package.status = "approved"


def ensure_scenario_mapping_editable(db: Session, mapping_type: str, mapping_id: int) -> None:
    package_column = {
        "scenario_business": ScenarioReviewPackage.business_mapping_id,
        "scenario_technical": ScenarioReviewPackage.technical_lineage_id,
    }.get(mapping_type)
    required_step = {
        "scenario_business": "business_draft",
        "scenario_technical": "technical_draft",
    }.get(mapping_type)
    if package_column is None or required_step is None:
        raise ValueError("Unsupported scenario mapping type")
    package = db.scalar(select(ScenarioReviewPackage).where(package_column == mapping_id))
    if package is None or package.status in {"draft", "withdrawn"}:
        return
    instance = db.scalar(select(WorkflowInstance).where(
        WorkflowInstance.target_type == "scenario_review_package",
        WorkflowInstance.target_id == package.id,
    ).order_by(WorkflowInstance.id.desc()))
    if instance is None:
        return
    if package.status == "approved" or instance.status == "approved":
        raise HTTPException(status_code=409, detail="Approved review package content is immutable; create a new review version")
    if instance.status in {"in_progress", "rejected"} and instance.current_step != required_step:
        raise HTTPException(status_code=409, detail=f"Content can only be edited during {required_step}")


def _evidence(db: Session, mapping_type: str, mapping_id: int) -> list[dict[str, Any]]:
    rows = db.scalars(select(MappingEvidenceReference).where(
        MappingEvidenceReference.mapping_type == mapping_type,
        MappingEvidenceReference.mapping_id == mapping_id,
    ).order_by(MappingEvidenceReference.id)).all()
    return [{
        "evidence_reference_id": row.id,
        "evidence_type": row.evidence_type,
        "evidence_id": row.evidence_id,
        "source_name": row.source_name,
        "location_text": row.location_text,
        "evidence_summary": row.evidence_summary or row.quoted_content,
    } for row in rows]


def _source_catalog_fields(db: Session, technical: ScenarioTechnicalLineage) -> list[dict[str, Any]]:
    evidence_column_ids = list(db.scalars(select(MappingEvidenceReference.evidence_id).where(
        MappingEvidenceReference.mapping_type == "scenario_technical",
        MappingEvidenceReference.mapping_id == technical.id,
        MappingEvidenceReference.evidence_type == "catalog_column",
        MappingEvidenceReference.evidence_id.is_not(None),
    )).all())
    clauses = []
    if technical.source_table_english_name and technical.source_field_english_name:
        clauses.append(
            (CatalogColumn.table_name == technical.source_table_english_name)
            & (CatalogColumn.column_name == technical.source_field_english_name)
        )
    if evidence_column_ids:
        clauses.append(CatalogColumn.id.in_(evidence_column_ids))
    if not clauses:
        return []
    rows = db.scalars(select(CatalogColumn).where(
        CatalogColumn.project_id == technical.project_id,
        or_(*clauses),
    ).order_by(CatalogColumn.id).limit(50)).all()
    return [{
        "catalog_column_id": row.id,
        "datasource_id": row.datasource_id,
        "database_name": row.database_name,
        "schema_name": row.schema_name,
        "table_name": row.table_name,
        "column_name": row.column_name,
        "column_comment": row.column_comment,
        "data_type": row.data_type,
    } for row in rows]


def _row_snapshot(row: Any) -> dict[str, Any]:
    return {column.key: _json_value(getattr(row, column.key)) for column in sa_inspect(row).mapper.column_attrs}


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (dict, list)):
        return value
    return str(value)
