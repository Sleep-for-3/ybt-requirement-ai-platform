from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    ImpactAnalysis, LineageEdge, LineageNode, MappingEvidenceReference, MartToYbtMapping, ScenarioTechnicalLineage,
    ProjectMembership, ScriptChangeItem, ScriptChangeSet, ScriptFile, ScriptFileVersion, SourceToMartMapping,
)
from app.services.lineage.version_diff import VersionDiffResult


def persist_change_impact(
    db: Session,
    *,
    script_file: ScriptFile,
    from_version: ScriptFileVersion,
    to_version: ScriptFileVersion,
    diff: VersionDiffResult,
    created_by: int | None,
) -> tuple[ScriptChangeSet, ImpactAnalysis]:
    change_set = ScriptChangeSet(
        project_id=script_file.project_id,
        script_file_id=script_file.id,
        from_version_id=from_version.id,
        to_version_id=to_version.id,
        change_type="modified",
        status="completed",
        summary_json=diff.summary,
        created_by=created_by,
    )
    db.add(change_set); db.flush()
    for item in diff.items:
        db.add(ScriptChangeItem(
            change_set_id=change_set.id,
            change_category=item.change_category,
            entity_type=item.entity_type,
            old_value_json=item.old_value,
            new_value_json=item.new_value,
            severity=item.severity,
        ))
    nodes = list(db.scalars(select(LineageNode).where(LineageNode.script_file_version_id.in_([from_version.id, to_version.id]))).all())
    target_ids = sorted({item.target_field_id for item in nodes if item.target_field_id})
    mart_ids = sorted({item.mart_field_id for item in nodes if item.mart_field_id})
    edge_ids = list(db.scalars(select(LineageEdge.id).where(LineageEdge.script_file_version_id.in_([from_version.id, to_version.id]))).all())
    scenario_rows = list(db.scalars(select(ScenarioTechnicalLineage).where(
        ScenarioTechnicalLineage.project_id == script_file.project_id,
        ScenarioTechnicalLineage.target_field_id.in_(target_ids),
    )).all()) if target_ids else []
    source_rows = list(db.scalars(select(SourceToMartMapping).where(
        SourceToMartMapping.project_id == script_file.project_id,
        SourceToMartMapping.mart_field_id.in_(mart_ids),
    )).all()) if mart_ids else []
    ybt_rows = list(db.scalars(select(MartToYbtMapping).where(
        MartToYbtMapping.project_id == script_file.project_id,
        or_(MartToYbtMapping.target_field_id.in_(target_ids), MartToYbtMapping.mart_field_id.in_(mart_ids)),
    )).all()) if target_ids or mart_ids else []
    mapping_refs = [f"scenario_technical:{item.id}" for item in scenario_rows]
    mapping_refs += [f"source_to_mart:{item.id}" for item in source_rows]
    mapping_refs += [f"mart_to_ybt:{item.id}" for item in ybt_rows]
    impact = ImpactAnalysis(
        institution_id=script_file.institution_id,
        project_id=script_file.project_id,
        change_set_id=change_set.id,
        status="completed",
        severity=diff.severity,
        affected_target_field_ids_json=target_ids,
        affected_mart_field_ids_json=mart_ids,
        affected_mapping_ids_json=mapping_refs,
        affected_scenario_mapping_ids_json=[item.id for item in scenario_rows],
        affected_lineage_edge_ids_json=edge_ids,
        summary_json={**diff.summary, "script_file_id": script_file.id, "from_version_no": from_version.version_no, "to_version_no": to_version.version_no},
        open_questions_json=[] if not diff.semantic_changed else ["请技术审核人员确认脚本变化是否要求更新人工口径"],
        completed_at=datetime.now(UTC),
    )
    db.add(impact); db.flush()
    for reference in mapping_refs:
        mapping_type, _, raw_id = reference.partition(":")
        mapping_id = int(raw_id)
        for evidence_type, evidence_id, source_name in (
            ("script_change_set", change_set.id, f"脚本变更集 #{change_set.id}"),
            ("impact_analysis", impact.id, f"血缘影响分析 #{impact.id}"),
        ):
            existing = db.scalar(select(MappingEvidenceReference).where(
                MappingEvidenceReference.project_id == script_file.project_id,
                MappingEvidenceReference.mapping_type == mapping_type,
                MappingEvidenceReference.mapping_id == mapping_id,
                MappingEvidenceReference.evidence_type == evidence_type,
                MappingEvidenceReference.evidence_id == evidence_id,
            ))
            if existing is None:
                db.add(MappingEvidenceReference(
                    project_id=script_file.project_id, mapping_type=mapping_type, mapping_id=mapping_id,
                    evidence_type=evidence_type, evidence_id=evidence_id, source_name=source_name,
                    location_text=f"{script_file.relative_path} v{to_version.version_no}", quoted_content=None,
                    evidence_summary=f"{diff.severity}：{'、'.join(sorted({item.change_category for item in diff.items}))}",
                ))
    status = "stale" if diff.severity == "critical" else "needs_review" if diff.severity in {"high", "medium"} else None
    if status and diff.semantic_changed:
        for mapping in [*scenario_rows, *source_rows, *ybt_rows]:
            mapping.lineage_status = status
            mapping.lineage_change_set_id = change_set.id
    if diff.semantic_changed and diff.severity in {"high", "critical"}:
        from app.services.governance.notifications import notify_user
        from app.services.governance.workflow import start_workflow
        memberships = list(db.scalars(select(ProjectMembership).where(
            ProjectMembership.project_id == script_file.project_id,
            ProjectMembership.project_role.in_(["project_manager", "technical_analyst", "technical_reviewer", "final_reviewer"]),
            ProjectMembership.status == "active",
        )).all())
        assignments: dict[str, int] = {}
        for membership in memberships:
            assignments.setdefault(membership.project_role, membership.user_id)
            notify_user(
                db, membership.user_id, "lineage_impact_detected", "检测到高风险血缘变化",
                f"脚本 #{script_file.id} 产生 {diff.severity} 级影响，请复核。",
                project_id=script_file.project_id, resource_type="impact_analysis", resource_id=impact.id,
            )
        start_workflow(
            db, project_id=script_file.project_id, workflow_key="lineage_change_review",
            target_type="impact_analysis", target_id=impact.id, created_by=created_by or 0,
            assignments={key: value for key, value in assignments.items() if key in {"technical_analyst", "technical_reviewer", "final_reviewer"}},
        )
    return change_set, impact
