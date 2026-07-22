from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import aliased

from app.models import (
    ImpactAnalysis,
    LineageEdge,
    LineageNode,
    MartToYbtMapping,
    ReviewDecision,
    ReviewTask,
    ScriptChangeItem,
    ScriptChangeSet,
    ScriptFile,
    ScriptFileVersion,
    SourceToMartMapping,
    TargetField,
    TargetTable,
    User,
    WorkflowInstance,
)
from app.services.security import redact_content


def build_lineage_records(db, project_id: int, target_table_id: int) -> list[dict]:
    table, fields = _target_scope(db, project_id, target_table_id)
    field_by_id = {field.id: field for field in fields}
    field_ids = set(field_by_id)
    if not field_ids:
        return []
    source_node = aliased(LineageNode, name="deliverable_source_node")
    target_node = aliased(LineageNode, name="deliverable_target_node")
    rows = db.execute(
        select(LineageEdge, source_node, target_node, ScriptFileVersion, ScriptFile)
        .join(source_node, source_node.id == LineageEdge.source_node_id)
        .join(target_node, target_node.id == LineageEdge.target_node_id)
        .join(ScriptFileVersion, ScriptFileVersion.id == LineageEdge.script_file_version_id)
        .join(ScriptFile, ScriptFile.id == ScriptFileVersion.script_file_id)
        .where(
            LineageEdge.project_id == project_id,
            LineageEdge.enabled.is_(True),
            source_node.project_id == project_id,
            target_node.project_id == project_id,
            ScriptFileVersion.project_id == project_id,
            ScriptFile.project_id == project_id,
            ScriptFile.enabled.is_(True),
            ScriptFileVersion.version_no == ScriptFile.current_version_no,
            or_(
                target_node.target_table_id == table.id,
                target_node.target_field_id.in_(field_ids),
            ),
        )
        .order_by(ScriptFile.relative_path, LineageEdge.id)
    ).all()
    result = []
    for edge, source, target, version, script in rows:
        target_field = field_by_id.get(target.target_field_id)
        result.append({
            "source_script": _safe_relative_path(script.relative_path),
            "script_version": version.version_no,
            "script_version_hash": version.file_hash,
            "source_database": redact_content(source.database_name or ""),
            "source_schema": redact_content(source.schema_name or ""),
            "source_table": redact_content(source.table_name or ""),
            "source_column": redact_content(source.column_name or ""),
            "target_database": redact_content(target.database_name or ""),
            "target_schema": redact_content(target.schema_name or ""),
            "target_table": redact_content(target.table_name or table.table_code),
            "target_column": redact_content(target.column_name or (target_field.field_code if target_field else "")),
            "edge_type": edge.edge_type,
            "transformation_summary": _presence_summary(edge.transformation_expression, edge.transformation_type, "转换"),
            "filter_summary": _presence_summary(edge.filter_condition, None, "过滤条件"),
            "join_summary": _presence_summary(edge.join_condition, None, "关联条件"),
            "lineage_status": "linked" if not target.unresolved_flag else "unresolved",
            "reviewed_status": "verified" if edge.confidence_level == "high" and not target.unresolved_flag else "pending_review",
            "reviewed_at": edge.updated_at if edge.confidence_level == "high" and not target.unresolved_flag else None,
            "affected_target_field_code": target_field.field_code if target_field else target.column_name,
            "affected_mapping_type": "target_field",
            "affected_mapping_id": target_field.id if target_field else None,
        })
    return result


def build_change_impact_records(db, project_id: int, target_table_id: int) -> list[dict]:
    table, fields = _target_scope(db, project_id, target_table_id)
    field_by_id = {field.id: field for field in fields}
    field_ids = set(field_by_id)
    mart_to_ybt = list(db.scalars(select(MartToYbtMapping).where(
        MartToYbtMapping.project_id == project_id,
        MartToYbtMapping.target_field_id.in_(field_ids),
    )).all()) if field_ids else []
    mart_field_ids = {mapping.mart_field_id for mapping in mart_to_ybt if mapping.mart_field_id}
    source_to_mart = list(db.scalars(select(SourceToMartMapping).where(
        SourceToMartMapping.project_id == project_id,
        SourceToMartMapping.mart_field_id.in_(mart_field_ids),
    )).all()) if mart_field_ids else []
    relevant_mapping_ids = {
        "source_to_mart": {mapping.id for mapping in source_to_mart},
        "mart_to_ybt": {mapping.id for mapping in mart_to_ybt},
    }

    impacts = list(db.scalars(select(ImpactAnalysis).where(ImpactAnalysis.project_id == project_id).order_by(ImpactAnalysis.id)).all())
    result = []
    for impact in impacts:
        affected_fields = field_ids.intersection(impact.affected_target_field_ids_json or [])
        typed_affected_mappings = _typed_mapping_ids(impact.affected_mapping_ids_json or [])
        affected_source_to_mart = relevant_mapping_ids["source_to_mart"].intersection(typed_affected_mappings["source_to_mart"])
        affected_mart_to_ybt = relevant_mapping_ids["mart_to_ybt"].intersection(typed_affected_mappings["mart_to_ybt"])
        if not affected_fields and not affected_source_to_mart and not affected_mart_to_ybt:
            continue
        change_set = db.scalar(select(ScriptChangeSet).where(
            ScriptChangeSet.project_id == project_id,
            ScriptChangeSet.id == impact.change_set_id,
        ))
        if change_set is None:
            continue
        script = db.scalar(select(ScriptFile).where(
            ScriptFile.project_id == project_id,
            ScriptFile.id == change_set.script_file_id,
        ))
        if script is None:
            continue
        old_version = db.scalar(select(ScriptFileVersion).where(
            ScriptFileVersion.project_id == project_id,
            ScriptFileVersion.script_file_id == script.id,
            ScriptFileVersion.id == change_set.from_version_id,
        )) if change_set.from_version_id else None
        new_version = db.scalar(select(ScriptFileVersion).where(
            ScriptFileVersion.project_id == project_id,
            ScriptFileVersion.script_file_id == script.id,
            ScriptFileVersion.id == change_set.to_version_id,
            ScriptFileVersion.version_no == script.current_version_no,
        )) if change_set.to_version_id else None
        if new_version is None:
            continue
        items = list(db.scalars(select(ScriptChangeItem).where(
            ScriptChangeItem.change_set_id == change_set.id,
        ).order_by(ScriptChangeItem.id)).all())
        decision, reviewer, reviewed_at = _impact_review(db, project_id, impact.id)
        field_names = [field_by_id[field_id].field_code for field_id in sorted(affected_fields)]
        result.append({
            "script_path": _safe_relative_path(script.relative_path),
            "old_version_no": old_version.version_no if old_version else None,
            "new_version_no": new_version.version_no if new_version else None,
            "change_type": change_set.change_type,
            "impact_severity": impact.severity,
            "impact_status": impact.status,
            "affected_target_table": table.table_code,
            "affected_target_field": ", ".join(field_names),
            "affected_scenario": ", ".join(str(item) for item in impact.affected_scenario_mapping_ids_json or []),
            "affected_source_to_mart_mapping": ", ".join(str(item.id) for item in source_to_mart if item.id in affected_source_to_mart),
            "affected_mart_to_ybt_mapping": ", ".join(str(item.id) for item in mart_to_ybt if item.id in affected_mart_to_ybt),
            "change_summary": _change_summary(items),
            "review_decision": decision,
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
        })
    return result


def _target_scope(db, project_id: int, target_table_id: int) -> tuple[TargetTable, list[TargetField]]:
    table = db.scalar(select(TargetTable).where(
        TargetTable.project_id == project_id,
        TargetTable.id == target_table_id,
    ))
    if table is None:
        raise ValueError("Target table not found in project")
    fields = list(db.scalars(select(TargetField).where(
        TargetField.project_id == project_id,
        TargetField.target_table_id == target_table_id,
    ).order_by(TargetField.id)).all())
    return table, fields


def _impact_review(db, project_id: int, impact_id: int) -> tuple[str, str | None, object | None]:
    row = db.execute(
        select(ReviewDecision, User)
        .join(ReviewTask, ReviewTask.id == ReviewDecision.review_task_id)
        .join(WorkflowInstance, WorkflowInstance.id == ReviewTask.workflow_instance_id)
        .join(User, User.id == ReviewDecision.decided_by)
        .where(
            WorkflowInstance.project_id == project_id,
            WorkflowInstance.target_type == "impact_analysis",
            WorkflowInstance.target_id == impact_id,
        )
        .order_by(ReviewDecision.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return "pending_review", None, None
    decision, user = row
    return decision.decision, redact_content(user.display_name or user.username), decision.decided_at


def _presence_summary(value: str | None, kind: str | None, label: str) -> str:
    if not value and not kind:
        return ""
    suffix = f"（{redact_content(kind)}）" if kind else ""
    return f"存在{label}{suffix}，具体表达式已从正式交付包中移除"


def _change_summary(items: list[ScriptChangeItem]) -> str:
    categories = sorted({redact_content(item.change_category) for item in items})
    return "；".join(categories) if categories else "变更摘要待人工补充"


def _safe_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or ":/" in normalized:
        normalized = normalized.rsplit("/", 1)[-1]
    return redact_content(normalized)


def _typed_mapping_ids(values: list) -> dict[str, set[int]]:
    result = {"source_to_mart": set(), "mart_to_ybt": set()}
    for value in values:
        mapping_type, separator, raw_id = str(value).partition(":")
        if not separator or mapping_type not in result:
            continue
        try:
            result[mapping_type].add(int(raw_id))
        except ValueError:
            continue
    return result
