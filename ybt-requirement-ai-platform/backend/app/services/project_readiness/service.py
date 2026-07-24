from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ColumnProfileSnapshot,
    DataSource,
    DeliverablePackage,
    DeliverableTemplateVersion,
    ImpactAnalysis,
    KnowledgeDocument,
    LineageEdge,
    MartToYbtMapping,
    PendingQuestion,
    ProductScenario,
    Project,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    SourceToMartMapping,
    TargetField,
    UatFinding,
    UatRun,
    UatSignoff,
    WorkflowInstance,
)
from app.services.deployment import database_revisions


@dataclass(frozen=True)
class DimensionSpec:
    completed: int
    required: int
    blockers: tuple[dict[str, str], ...]
    actions: tuple[str, ...]
    links: tuple[str, ...]
    weight: int = 1


def build_project_readiness(db: Session, project_id: int) -> dict[str, Any]:
    """Return the canonical, server-side readiness assessment for one project."""
    project = db.get(Project, project_id)
    if project is None:
        raise LookupError("Project not found")

    counts = _project_counts(db, project_id)
    dimensions = _dimension_specs(project_id, counts)
    rendered = {key: _render_dimension(spec) for key, spec in dimensions.items()}
    critical_blockers = [
        blocker
        for key, spec in dimensions.items()
        for blocker in spec.blockers
        if blocker.get("severity") == "critical"
    ]
    weighted_score = round(
        sum(rendered[key]["score"] * spec.weight for key, spec in dimensions.items())
        / sum(spec.weight for spec in dimensions.values()),
        4,
    )
    statuses = {item["status"] for item in rendered.values()}
    if critical_blockers:
        overall_status = "blocked"
    elif statuses == {"ready"}:
        overall_status = "ready"
    elif weighted_score == 0:
        overall_status = "not_started"
    else:
        overall_status = "partial"

    return {
        "project_id": project_id,
        "overall_status": overall_status,
        "score": weighted_score,
        "scoring_method": "weighted_dimensions_with_critical_blocker_override",
        "critical_blockers": critical_blockers,
        "dimensions": rendered,
    }


def build_onboarding_state(db: Session, project_id: int) -> dict[str, Any]:
    readiness = build_project_readiness(db, project_id)
    dimensions = readiness["dimensions"]
    definitions = (
        ("project_configuration", "配置项目", ("project_configuration",), False),
        ("target_definition", "导入并确认目标字段", ("target_field_definition",), False),
        ("knowledge_base", "准备知识资料", ("knowledge_base",), True),
        ("datasource_catalog", "连接数据源并同步目录", ("datasource_and_catalog", "source_profiling"), True),
        ("scenario_definition", "定义产品场景", ("scenario_definition",), False),
        ("mapping_lineage", "完成映射与技术血缘", ("business_mapping", "technical_lineage", "double_layer_mapping"), False),
        ("deliverable_template", "配置正式交付模板", ("deliverable_template",), False),
        ("governance_readiness", "完成治理复核与就绪检查", ("governance_review", "open_questions", "change_impact"), False),
        ("uat_acceptance", "执行 UAT 并签署验收", ("uat_status",), False),
        ("deliverable_package", "生成并校验交付包", ("deliverable_package", "deployment_readiness"), False),
    )
    steps = []
    for index, (key, title, dimension_keys, skippable) in enumerate(definitions, start=1):
        selected = [dimensions[item] for item in dimension_keys]
        if all(item["status"] == "ready" for item in selected):
            status = "completed"
        elif any(item["status"] == "blocked" for item in selected):
            status = "blocked"
        elif any(item["completed_count"] for item in selected):
            status = "in_progress"
        else:
            status = "not_started"
        reasons = [reason for item in selected for reason in item["blocking_reasons"]]
        actions = [action for item in selected for action in item["recommended_actions"]]
        links = list(dict.fromkeys(link for item in selected for link in item["links"]))
        steps.append({
            "step": index,
            "key": key,
            "title": title,
            "status": status,
            "blocking_reasons": reasons,
            "next_action": actions[0] if actions else None,
            "links": links,
            "skippable": skippable,
        })
    return {"project_id": project_id, "overall_status": readiness["overall_status"], "steps": steps}


def _count(db: Session, model: type, project_id: int, *conditions: Any) -> int:
    statement = select(func.count()).select_from(model).where(model.project_id == project_id, *conditions)
    return int(db.scalar(statement) or 0)


def _project_counts(db: Session, project_id: int) -> dict[str, Any]:
    current_revision, head_revision = _database_revisions(db)
    latest_signoffs = select(
        UatSignoff.uat_run_id,
        UatSignoff.signoff_role,
        func.max(UatSignoff.id).label("latest_id"),
    ).where(
        UatSignoff.project_id == project_id,
        UatSignoff.signoff_role.in_(("business_owner", "technical_owner", "project_manager", "final_acceptance")),
    ).group_by(UatSignoff.uat_run_id, UatSignoff.signoff_role).subquery()
    signed_runs = select(UatSignoff.uat_run_id).join(
        latest_signoffs,
        UatSignoff.id == latest_signoffs.c.latest_id,
    ).where(UatSignoff.signoff_status == "approved").group_by(
        UatSignoff.uat_run_id,
    ).having(func.count(func.distinct(UatSignoff.signoff_role)) >= 4)
    return {
        "target_fields": _count(db, TargetField, project_id),
        "scenarios": _count(db, ProductScenario, project_id, ProductScenario.enabled.is_(True)),
        "knowledge": _count(db, KnowledgeDocument, project_id, KnowledgeDocument.document_status != "deleted"),
        "datasources": _count(db, DataSource, project_id, DataSource.enabled.is_(True)),
        "profiles": _count(db, ColumnProfileSnapshot, project_id),
        "business_mappings": _count(db, ScenarioBusinessMapping, project_id),
        "business_confirmed": int(db.scalar(
            select(func.count()).select_from(ScenarioBusinessMapping)
            .join(ProductScenario, ProductScenario.id == ScenarioBusinessMapping.scenario_id)
            .where(
                ScenarioBusinessMapping.project_id == project_id,
                ScenarioBusinessMapping.business_confirm_status.in_(("confirmed", "approved")),
                ProductScenario.enabled.is_(True),
            )
        ) or 0),
        "technical_lineages": _count(db, ScenarioTechnicalLineage, project_id),
        "technical_confirmed": int(db.scalar(
            select(func.count()).select_from(ScenarioTechnicalLineage)
            .join(ProductScenario, ProductScenario.id == ScenarioTechnicalLineage.scenario_id)
            .where(
                ScenarioTechnicalLineage.project_id == project_id,
                ScenarioTechnicalLineage.tech_confirm_status.in_(("confirmed", "approved")),
                ProductScenario.enabled.is_(True),
            )
        ) or 0),
        "source_mart": _count(db, SourceToMartMapping, project_id),
        "mart_ybt": _count(db, MartToYbtMapping, project_id),
        "governance_completed": _count(db, WorkflowInstance, project_id, WorkflowInstance.status.in_(("approved", "completed"))),
        "lineage_edges": _count(db, LineageEdge, project_id, LineageEdge.enabled.is_(True)),
        "critical_impacts": _count(db, ImpactAnalysis, project_id, ImpactAnalysis.severity.in_(("critical", "high")), ImpactAnalysis.status.notin_(("reviewed", "approved", "closed"))),
        "template_versions": _count(db, DeliverableTemplateVersion, project_id),
        "valid_packages": _count(db, DeliverablePackage, project_id, DeliverablePackage.status.in_(("validated", "approved", "released"))),
        "failed_packages": _count(db, DeliverablePackage, project_id, DeliverablePackage.status.in_(("validation_failed", "failed", "rejected"))),
        "high_questions": _count(db, PendingQuestion, project_id, PendingQuestion.priority.in_(("critical", "high")), PendingQuestion.question_status.notin_(("answered", "closed", "resolved"))),
        "passed_uat_runs": _count(db, UatRun, project_id, UatRun.status == "passed"),
        "fully_signed_uat_runs": _count(db, UatRun, project_id, UatRun.status == "passed", UatRun.id.in_(signed_runs)),
        "active_critical_findings": _count(db, UatFinding, project_id, UatFinding.severity == "critical", UatFinding.status.notin_(("verified", "closed"))),
        "database_revision_current": current_revision,
        "database_revision_head": head_revision,
    }


def _database_revisions(db: Session) -> tuple[str | None, str | None]:
    return database_revisions(db.connection())


def _blocker(code: str, message: str, dimension: str, *, critical: bool = False) -> dict[str, str]:
    return {"code": code, "message": message, "dimension": dimension, "severity": "critical" if critical else "warning"}


def _dimension_specs(project_id: int, c: dict[str, Any]) -> dict[str, DimensionSpec]:
    base = f"/projects/{project_id}"
    target_required = max(c["target_fields"] * max(c["scenarios"], 1), 1)
    return {
        "project_configuration": DimensionSpec(1, 1, (), (), (base,), 2),
        "target_field_definition": DimensionSpec(c["target_fields"], 1, () if c["target_fields"] else (_blocker("target_fields_missing", "尚未定义目标字段。", "target_field_definition", critical=True),), ("导入或创建监管目标字段。",), (f"{base}/target-fields",), 4),
        "scenario_definition": DimensionSpec(c["scenarios"], 1, () if c["scenarios"] else (_blocker("scenarios_missing", "尚未定义产品场景。", "scenario_definition"),), ("至少创建一个启用的产品场景。",), (f"{base}/scenarios",), 2),
        "knowledge_base": DimensionSpec(c["knowledge"], 1, (), ("上传监管口径、业务制度或历史参考资料。",), (f"{base}/knowledge",)),
        "datasource_and_catalog": DimensionSpec(c["datasources"], 1, (), ("配置只读数据源并同步数据目录。",), (f"{base}/datasources",), 2),
        "source_profiling": DimensionSpec(c["profiles"], 1, (), ("对候选源字段执行脱敏剖析。",), (f"{base}/profiling",)),
        "business_mapping": DimensionSpec(c["business_confirmed"], target_required, () if not c["target_fields"] or c["business_confirmed"] >= target_required else (_blocker("business_mapping_unconfirmed", "仍有字段场景组合未完成业务映射确认。", "business_mapping", critical=True),), ("完成每个字段场景组合的业务口径确认。",), (f"{base}/scenario-mapping",), 4),
        "technical_lineage": DimensionSpec(c["technical_confirmed"], target_required, () if not c["target_fields"] or c["technical_confirmed"] >= target_required else (_blocker("technical_lineage_unconfirmed", "仍有字段场景组合未完成技术血缘确认。", "technical_lineage", critical=True),), ("完成每个字段场景组合的源系统、表、字段及加工逻辑确认。",), (f"{base}/scenario-mapping",), 4),
        "double_layer_mapping": DimensionSpec(min(c["source_mart"], c["mart_ybt"]), 1, (), ("补齐源到集市、集市到监管目标的双层映射。",), (f"{base}/double-layer-lineage",), 2),
        "governance_review": DimensionSpec(c["governance_completed"], 1, (), ("提交关键内容并完成治理审批。",), (f"{base}/governance",), 2),
        "sql_lineage": DimensionSpec(c["lineage_edges"], 1, (), ("上传 SQL 并生成可追溯血缘。",), (f"{base}/lineage",), 2),
        "change_impact": DimensionSpec(0 if c["critical_impacts"] else 1, 1, () if not c["critical_impacts"] else (_blocker("critical_impact_unreviewed", "存在未复核的高风险变更影响。", "change_impact", critical=True),), ("复核并关闭高风险变更影响。",), (f"{base}/impact",), 3),
        "deliverable_template": DimensionSpec(c["template_versions"], 1, () if c["template_versions"] else (_blocker("formal_template_missing", "尚未配置正式交付模板版本。", "deliverable_template", critical=True),), ("上传、映射并激活正式交付模板。",), (f"{base}/deliverables/templates",), 4),
        "deliverable_package": DimensionSpec(c["valid_packages"], 1, () if not c["failed_packages"] else (_blocker("deliverable_validation_failed", "存在正式交付校验失败记录。", "deliverable_package", critical=True),), ("修复校验错误并重新生成交付包。",), (f"{base}/deliverables",), 3),
        "open_questions": DimensionSpec(0 if c["high_questions"] else 1, 1, () if not c["high_questions"] else (_blocker("high_priority_questions_open", "存在未关闭的高优先级待确认问题。", "open_questions", critical=True),), ("回答并关闭高优先级问题。",), (f"{base}/deliverables/questions",), 3),
        "uat_status": DimensionSpec(
            c["fully_signed_uat_runs"],
            1,
            (() if not c["active_critical_findings"] else (_blocker("critical_uat_findings_open", "存在未验证关闭的严重 UAT 发现。", "uat_status", critical=True),))
            + (() if not c["passed_uat_runs"] or c["fully_signed_uat_runs"] else (_blocker("uat_signoff_incomplete", "通过的 UAT 轮次尚未完成四方签署。", "uat_status", critical=True),)),
            ("执行 UAT、关闭严重发现并完成签署。",),
            ("/uat",),
            4,
        ),
        "deployment_readiness": DimensionSpec(1 if c["fully_signed_uat_runs"] and c["valid_packages"] and c["database_revision_current"] == c["database_revision_head"] else 0, 1, () if c["database_revision_current"] == c["database_revision_head"] else (_blocker("database_revision_not_head", "数据库迁移版本不是当前 head。", "deployment_readiness", critical=True),), ("升级数据库到当前 Alembic head，并通过 UAT 与交付校验。",), (f"{base}/readiness",), 3),
    }


def _render_dimension(spec: DimensionSpec) -> dict[str, Any]:
    completed = min(spec.completed, spec.required)
    score = round(completed / spec.required, 4)
    if spec.blockers:
        status = "blocked"
    elif completed >= spec.required:
        status = "ready"
    elif completed:
        status = "partial"
    else:
        status = "not_started"
    return {
        "status": status,
        "score": score,
        "completed_count": completed,
        "required_count": spec.required,
        "blocking_reasons": list(spec.blockers),
        "recommended_actions": list(spec.actions),
        "links": list(spec.links),
    }
