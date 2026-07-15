from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import (
    BackgroundJob, CatalogColumn, KnowledgeDocument, MappingEvidenceReference, ProductScenario, Project,
    ReviewTask, ScenarioBusinessMapping, ScenarioTechnicalLineage, TargetField, TargetTable, WorkflowInstance,
)
from app.services.auth.dependencies import RealPrincipal
from app.services.auth.permission_service import PermissionService


router = APIRouter(tags=["project dashboard"])


@router.get("/projects/{project_id}/dashboard")
def project_dashboard(project_id: int, principal: RealPrincipal, target_table_id: int | None = None, scenario_id: int | None = None, assignee_user_id: int | None = None, review_status: str | None = None, evidence_completeness: str | None = None, confidence_level: str | None = None, db: Session = Depends(get_db)) -> dict:
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    field_filter = [TargetField.project_id == project_id]
    if target_table_id is not None: field_filter.append(TargetField.target_table_id == target_table_id)
    field_ids = select(TargetField.id).where(*field_filter)
    business_filter = [ScenarioBusinessMapping.project_id == project_id, ScenarioBusinessMapping.target_field_id.in_(field_ids)]
    technical_filter = [ScenarioTechnicalLineage.project_id == project_id, ScenarioTechnicalLineage.target_field_id.in_(field_ids)]
    if scenario_id is not None:
        business_filter.append(ScenarioBusinessMapping.scenario_id == scenario_id)
        technical_filter.append(ScenarioTechnicalLineage.scenario_id == scenario_id)
    if confidence_level is not None:
        business_filter.append(ScenarioBusinessMapping.confidence_level == confidence_level)
        technical_filter.append(ScenarioTechnicalLineage.confidence_level == confidence_level)
    now = datetime.now(UTC)
    task_filter = [ReviewTask.project_id == project_id]
    if assignee_user_id is not None: task_filter.append(ReviewTask.assignee_user_id == assignee_user_id)
    if review_status is not None: task_filter.append(ReviewTask.status == review_status)
    business_ids = select(ScenarioBusinessMapping.id).where(*business_filter)
    technical_ids = select(ScenarioTechnicalLineage.id).where(*technical_filter)
    counts = {
        "target_table_count": _count(db, TargetTable, TargetTable.project_id == project_id),
        "field_count": db.scalar(select(func.count(TargetField.id)).where(*field_filter)) or 0,
        "scenario_count": _count(db, ProductScenario, ProductScenario.project_id == project_id),
        "missing_business_mapping_count": _missing_mapping_count(db, field_ids, ScenarioBusinessMapping, project_id, scenario_id),
        "missing_technical_lineage_count": _missing_mapping_count(db, field_ids, ScenarioTechnicalLineage, project_id, scenario_id),
        "pending_business_review_count": _count(db, ReviewTask, *task_filter, ReviewTask.step_key == "business_review", ReviewTask.status.in_(["pending", "claimed", "returned"]) if review_status is None else ReviewTask.status == review_status),
        "pending_technical_review_count": _count(db, ReviewTask, *task_filter, ReviewTask.step_key == "technical_review", ReviewTask.status.in_(["pending", "claimed", "returned"]) if review_status is None else ReviewTask.status == review_status),
        "pending_final_review_count": _count(db, ReviewTask, *task_filter, ReviewTask.step_key == "final_review", ReviewTask.status.in_(["pending", "claimed", "returned"]) if review_status is None else ReviewTask.status == review_status),
        "approved_count": _count(db, WorkflowInstance, WorkflowInstance.project_id == project_id, WorkflowInstance.status == "approved"),
        "open_question_count": (_count(db, ScenarioBusinessMapping, *business_filter, ScenarioBusinessMapping.open_questions.is_not(None)) + _count(db, ScenarioTechnicalLineage, *technical_filter, ScenarioTechnicalLineage.open_questions.is_not(None))),
        "without_evidence_count": _without_evidence(db, business_ids, technical_ids),
        "low_confidence_count": (_count(db, ScenarioBusinessMapping, *business_filter, ScenarioBusinessMapping.confidence_level == "low") + _count(db, ScenarioTechnicalLineage, *technical_filter, ScenarioTechnicalLineage.confidence_level == "low")),
        "overdue_task_count": _count(db, ReviewTask, *task_filter, ReviewTask.due_at < now, ReviewTask.status.in_(["pending", "claimed", "returned"])),
        "knowledge_document_count": _count(db, KnowledgeDocument, KnowledgeDocument.project_id == project_id, KnowledgeDocument.document_status != "archived"),
        "catalog_column_count": _count(db, CatalogColumn, CatalogColumn.project_id == project_id, CatalogColumn.enabled.is_(True)),
    }
    failed = db.scalars(select(BackgroundJob).where(BackgroundJob.project_id == project_id, BackgroundJob.status.in_(["failed", "partially_completed"])).order_by(BackgroundJob.id.desc()).limit(10)).all()
    if evidence_completeness == "complete": counts["without_evidence_count"] = 0
    return {**counts, "filters": {"target_table_id": target_table_id, "scenario_id": scenario_id, "assignee_user_id": assignee_user_id, "review_status": review_status, "evidence_completeness": evidence_completeness, "confidence_level": confidence_level}, "recent_failed_jobs": [{"id": job.id, "job_type": job.job_type, "status": job.status, "error_message": job.error_message, "finished_at": job.finished_at} for job in failed]}


def _count(db, model, *conditions): return db.scalar(select(func.count(model.id)).where(*conditions)) or 0


def _missing_mapping_count(db, field_ids, model, project_id, scenario_id):
    total_fields = db.scalar(select(func.count()).select_from(field_ids.subquery())) or 0
    scenario_count = 1 if scenario_id is not None else _count(db, ProductScenario, ProductScenario.project_id == project_id, ProductScenario.enabled.is_(True))
    existing = _count(db, model, model.project_id == project_id, model.target_field_id.in_(field_ids), *((model.scenario_id == scenario_id,) if scenario_id is not None else ()))
    return max(total_fields * scenario_count - existing, 0)


def _without_evidence(db, business_ids, technical_ids):
    business_total = db.scalar(select(func.count()).select_from(business_ids.subquery())) or 0
    technical_total = db.scalar(select(func.count()).select_from(technical_ids.subquery())) or 0
    business_evidence = db.scalar(select(func.count(func.distinct(MappingEvidenceReference.mapping_id))).where(MappingEvidenceReference.mapping_type == "scenario_business", MappingEvidenceReference.mapping_id.in_(business_ids))) or 0
    technical_evidence = db.scalar(select(func.count(func.distinct(MappingEvidenceReference.mapping_id))).where(MappingEvidenceReference.mapping_type == "scenario_technical", MappingEvidenceReference.mapping_id.in_(technical_ids))) or 0
    return max(business_total - business_evidence, 0) + max(technical_total - technical_evidence, 0)
