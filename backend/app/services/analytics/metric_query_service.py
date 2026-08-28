from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ImpactAnalysis,
    MappingEvidenceReference,
    MetadataDriftEvent,
    ProductScenario,
    ReviewTask,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    TargetField,
    ReportingCycle,
)
from app.services.analytics.metric_registry import get_metric_definition
from app.services.project_readiness import build_project_readiness


def build_project_overview(db: Session, project_id: int, cycle_id: int | None = None) -> dict:
    """Build a governed analytics dataset without fabricating historical data."""
    cycle = db.get(ReportingCycle, cycle_id) if cycle_id is not None else None
    if cycle is not None and cycle.project_id != project_id:
        raise ValueError("reporting cycle does not belong to project")
    as_of = cycle.data_cutoff_at if cycle and cycle.data_cutoff_at else datetime.now(UTC)
    field_ids = select(TargetField.id).where(TargetField.project_id == project_id)
    enabled_scenarios = select(ProductScenario.id).where(ProductScenario.project_id == project_id, ProductScenario.enabled.is_(True))
    field_count = _count(db, TargetField, TargetField.project_id == project_id)
    scenario_count = db.scalar(select(func.count()).select_from(enabled_scenarios.subquery())) or 0
    eligible = field_count * scenario_count
    business_count = _count(db, ScenarioBusinessMapping, ScenarioBusinessMapping.project_id == project_id, ScenarioBusinessMapping.target_field_id.in_(field_ids), ScenarioBusinessMapping.scenario_id.in_(enabled_scenarios))
    technical_count = _count(db, ScenarioTechnicalLineage, ScenarioTechnicalLineage.project_id == project_id, ScenarioTechnicalLineage.target_field_id.in_(field_ids), ScenarioTechnicalLineage.scenario_id.in_(enabled_scenarios))
    business_confirmed = _count(db, ScenarioBusinessMapping, ScenarioBusinessMapping.project_id == project_id, ScenarioBusinessMapping.target_field_id.in_(field_ids), ScenarioBusinessMapping.scenario_id.in_(enabled_scenarios), ScenarioBusinessMapping.business_confirm_status.in_(("confirmed", "approved")))
    technical_confirmed = _count(db, ScenarioTechnicalLineage, ScenarioTechnicalLineage.project_id == project_id, ScenarioTechnicalLineage.target_field_id.in_(field_ids), ScenarioTechnicalLineage.scenario_id.in_(enabled_scenarios), ScenarioTechnicalLineage.tech_confirm_status.in_(("confirmed", "approved")))
    eligible_business_ids = select(ScenarioBusinessMapping.id).where(
        ScenarioBusinessMapping.project_id == project_id,
        ScenarioBusinessMapping.target_field_id.in_(field_ids),
        ScenarioBusinessMapping.scenario_id.in_(enabled_scenarios),
    )
    eligible_technical_ids = select(ScenarioTechnicalLineage.id).where(
        ScenarioTechnicalLineage.project_id == project_id,
        ScenarioTechnicalLineage.target_field_id.in_(field_ids),
        ScenarioTechnicalLineage.scenario_id.in_(enabled_scenarios),
    )
    business_evidence = _distinct_mapping_count(db, "scenario_business", eligible_business_ids)
    technical_evidence = _distinct_mapping_count(db, "scenario_technical", eligible_technical_ids)
    mapping_total = business_count + technical_count
    evidence_with_mapping = business_evidence + technical_evidence
    pending_tasks = _count(db, ReviewTask, ReviewTask.project_id == project_id, ReviewTask.status.in_(("pending", "claimed", "returned")))
    completed_tasks = _count(db, ReviewTask, ReviewTask.project_id == project_id, ReviewTask.status.in_(("completed", "approved")))
    overdue_tasks = _count(db, ReviewTask, ReviewTask.project_id == project_id, ReviewTask.status.in_(("pending", "claimed", "returned")), ReviewTask.due_at < as_of)
    high_risk_impacts = _count(db, ImpactAnalysis, ImpactAnalysis.project_id == project_id, ImpactAnalysis.status.notin_(("reviewed", "approved", "closed")), ImpactAnalysis.severity.in_(("high", "critical")))
    drift_count = _count(db, MetadataDriftEvent, MetadataDriftEvent.project_id == project_id)
    readiness = build_project_readiness(db, project_id)
    metrics = {
        "readiness_score": _score_metric("readiness_score", readiness["score"], "当前项目准备度维度", as_of),
        "business_definition_coverage": _ratio_metric("business_definition_coverage", business_count, eligible, as_of),
        "technical_lineage_coverage": _ratio_metric("technical_lineage_coverage", technical_count, eligible, as_of),
        "evidence_coverage": _ratio_metric("evidence_coverage", evidence_with_mapping, mapping_total, as_of),
        "review_completion_rate": _ratio_metric("review_completion_rate", completed_tasks, pending_tasks + completed_tasks, as_of),
        "review_sla_compliance": _ratio_metric("review_sla_compliance", max(completed_tasks - overdue_tasks, 0), completed_tasks, as_of),
        "high_risk_impact_count": _count_metric("high_risk_impact_count", high_risk_impacts, as_of),
        "schema_drift_count": _count_metric("schema_drift_count", drift_count, as_of),
    }
    return {
        "dataset_id": "project-analytics-overview",
        "project_id": project_id,
        "as_of": as_of.isoformat(),
        "reporting_cycle": None if cycle is None else {
            "id": cycle.id,
            "cycle_code": cycle.cycle_code,
            "cycle_name": cycle.cycle_name,
            "status": cycle.status,
            "period_start": cycle.period_start,
            "period_end": cycle.period_end,
            "submission_deadline": cycle.submission_deadline,
            "snapshot_available": False,
        },
        "filters": {"project_id": project_id, "reporting_cycle_id": cycle_id},
        "metrics": metrics,
        "risk_distribution": [
            {"code": "missing_business_definition", "label": "缺少业务口径", "value": max(eligible - business_count, 0), "drill_target": "/fields"},
            {"code": "missing_technical_lineage", "label": "缺少技术血缘", "value": max(eligible - technical_count, 0), "drill_target": "/lineage"},
            {"code": "missing_evidence", "label": "缺少证据", "value": max(mapping_total - evidence_with_mapping, 0), "drill_target": "/knowledge"},
            {"code": "overdue_review", "label": "审核超期", "value": overdue_tasks, "drill_target": "/work"},
            {"code": "high_risk_impact", "label": "高风险影响", "value": high_risk_impacts, "drill_target": "/lineage/changes"},
            {"code": "schema_drift", "label": "Schema Drift", "value": drift_count, "drill_target": "/catalog"},
        ],
    }


def _count(db: Session, model, *conditions) -> int:
    return int(db.scalar(select(func.count(model.id)).where(*conditions)) or 0)


def _distinct_mapping_count(db: Session, mapping_type: str, mapping_ids) -> int:
    return int(db.scalar(select(func.count(func.distinct(MappingEvidenceReference.mapping_id))).where(MappingEvidenceReference.mapping_type == mapping_type, MappingEvidenceReference.mapping_id.in_(mapping_ids))) or 0)


def _metric_payload(metric_code: str, numerator: int | float, denominator: int | float, as_of: datetime, *, scope: str | None = None) -> dict:
    definition = get_metric_definition(metric_code)
    value = None if denominator == 0 else numerator / denominator
    return {
        "metric_code": metric_code,
        "metric_name": definition.metric_name,
        "measure_type": definition.measure_type,
        "numerator": numerator,
        "denominator": denominator,
        "value": value,
        "scope": scope or definition.eligible_population,
        "as_of": as_of.isoformat(),
        "definition": {
            "description": definition.description,
            "numerator_definition": definition.numerator_definition,
            "denominator_definition": definition.denominator_definition,
            "eligible_population": definition.eligible_population,
            "excluded_population": definition.excluded_population,
            "dimensions": list(definition.dimensions),
            "owner": definition.owner,
            "version": definition.version,
            "certification_status": definition.certification_status,
        },
    }


def _ratio_metric(metric_code: str, numerator: int, denominator: int, as_of: datetime) -> dict:
    return _metric_payload(metric_code, numerator, denominator, as_of)


def _score_metric(metric_code: str, value: float, scope: str, as_of: datetime) -> dict:
    return _metric_payload(metric_code, value, 1, as_of, scope=scope)


def _count_metric(metric_code: str, value: int, as_of: datetime) -> dict:
    return _metric_payload(metric_code, value, 1, as_of)
