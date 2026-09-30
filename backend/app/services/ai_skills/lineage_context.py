"""Read-only auxiliary evidence bounded to the selected revision's endpoints.

No datasource connections or profiling jobs are started here. Mutable metadata
newer than the revision is excluded; absent historical values become gaps.
"""
from sqlalchemy import select
from fastapi import HTTPException

from app.models import CatalogColumn, ColumnProfileSnapshot, DataSource, LineageRevision, MartField, SourceField, TargetField
from app.models import Requirement, RequirementRevision, RequirementGenerationInput, RequirementGenerationItem
from app.models import ScriptFileVersion, SqlStatement, StoredFile
from app.schemas.ai_skill import EvidenceSource, SkillEvidence, SkillGap
from app.services.lineage.revisions import LineageRevisionService
from app.services.llm.execution_metadata import stable_hash

FIELD_MODELS = (("catalog_column_id", CatalogColumn), ("source_field_id", SourceField),
                ("mart_field_id", MartField), ("target_field_id", TargetField))
CONSTRAINT_FIELDS = ("data_type", "database_native_type", "field_type", "required_flag", "nullable",
                     "is_primary_key", "character_max_length", "numeric_precision", "numeric_scale", "data_format")
PROFILE_FIELDS = ("total_count", "null_count", "null_rate", "distinct_count", "min_length", "max_length", "average_length")


def evidence(project, scope, kind, source_type, source_id, value, locator):
    digest = stable_hash(value)
    return SkillEvidence(id=f"{source_type}:{source_id}:{digest[:20]}", kind=kind, value=value,
        source=EvidenceSource(source_type=source_type, source_id=str(source_id), source_version=digest,
                              locator=locator, scope=scope), confidentiality=project.confidentiality_level or "internal")


def auxiliary_context(db, project, revision, nodes, selected_edge, scope, providers):
    endpoint_keys = {str(selected_edge.get("source_node_key")), str(selected_edge.get("target_node_key"))}
    endpoints = [node for node in nodes if str(node.get("node_key")) in endpoint_keys]
    facts, gaps = [], []
    if "script_evidence" in providers:
        version_id = selected_edge.get("script_file_version_id")
        manifest = next((item for item in revision.source_manifest_json or [] if item.get("version_id") == version_id), None)
        row = db.execute(select(SqlStatement, ScriptFileVersion, StoredFile)
            .join(ScriptFileVersion, ScriptFileVersion.id == SqlStatement.script_file_version_id)
            .join(StoredFile, StoredFile.id == ScriptFileVersion.raw_content_storage_file_id)
            .where(SqlStatement.id == selected_edge.get("statement_id"), SqlStatement.project_id == project.id,
                   ScriptFileVersion.project_id == project.id, ScriptFileVersion.id == version_id,
                   StoredFile.project_id == project.id, StoredFile.institution_id == project.institution_id,
                   StoredFile.enabled.is_(True))).first() if manifest else None
        if row is None or row[1].file_hash != manifest.get("file_hash"):
            gaps.append(SkillGap(code="fixed_script_statement_missing", message="缺少所选关系对应的固定脚本语句，只能依据已解析边事实解释"))
        else:
            statement, script_version, stored = row
            material = {"script_version_id": script_version.id, "file_hash": script_version.file_hash,
                "statement_index": statement.statement_index, "normalized_sql": statement.normalized_sql,
                "raw_sql_hash": statement.raw_sql_hash, "parse_status": statement.parse_status,
                "source_line_start": statement.source_line_start, "source_line_end": statement.source_line_end}
            item = evidence(project, scope, "script_statement", "sql_statement", statement.id, material, f"script_version:{script_version.id}")
            ranking = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
            file_level = stored.classification if stored.classification in ranking else "restricted"
            item.confidentiality = max((item.confidentiality, file_level), key=ranking.__getitem__)
            facts.append(item)
            for warning in statement.warnings_json or []:
                gaps.append(SkillGap(code="parse_gap", message=str(warning)))
            if statement.parse_status not in {"parsed", "success", "succeeded"}:
                gaps.append(SkillGap(code="incomplete_script_parse", message="固定脚本语句未完整解析，动态部分不能推断为完整血缘"))
    if "field_constraints" in providers:
        for node in endpoints:
            found = False
            for key, model in FIELD_MODELS:
                if not node.get(key):
                    continue
                field = db.scalar(select(model).where(model.id == node[key], model.project_id == project.id,
                    model.updated_at <= revision.created_at))
                if field is None or getattr(field, "enabled", True) is False:
                    continue
                values = {name: getattr(field, name) for name in CONSTRAINT_FIELDS if getattr(field, name, None) is not None}
                if not values:
                    continue
                material = {"node_key": node["node_key"], "as_of_revision_id": revision.id,
                            "metadata_updated_at": str(field.updated_at), "constraints": values}
                facts.append(evidence(project, scope, "field_constraints", model.__tablename__, field.id, material, f"{key}:{field.id}"))
                found = True
            if not found:
                gaps.append(SkillGap(code="historical_constraints_missing", message="所选字段缺少不晚于血缘版本的约束，未使用后续修改的元数据"))
    if "quality_profile" in providers:
        for node in endpoints:
            column_id = node.get("catalog_column_id")
            column = db.scalar(select(CatalogColumn).join(DataSource, DataSource.id == CatalogColumn.datasource_id)
                .where(CatalogColumn.id == column_id, CatalogColumn.project_id == project.id,
                DataSource.project_id == project.id, DataSource.enabled.is_(True), CatalogColumn.enabled.is_(True))) if column_id else None
            profile = db.scalar(select(ColumnProfileSnapshot).where(ColumnProfileSnapshot.project_id == project.id,
                ColumnProfileSnapshot.catalog_column_id == column.id,
                ColumnProfileSnapshot.datasource_id == column.datasource_id,
                ColumnProfileSnapshot.profile_date <= revision.created_at)
                .order_by(ColumnProfileSnapshot.profile_date.desc(), ColumnProfileSnapshot.id.desc()).limit(1)) if column else None
            if profile is None:
                gaps.append(SkillGap(code="historical_profile_missing", message="所选字段没有对应血缘时点的质量画像；未发起实际数据查询"))
                continue
            material = {"node_key": node["node_key"], "as_of_revision_id": revision.id,
                        "profile_date": str(profile.profile_date),
                        "statistics": {name: getattr(profile, name) for name in PROFILE_FIELDS},
                        "interpretation": "历史采样画像不代表当前全量数据"}
            # Never expose observed min/max text, top-values, or raw data samples.
            facts.append(evidence(project, scope, "quality_profile", "column_profile", profile.id, material, f"column:{column.id}"))
    if "script_diff" in providers:
        parent = db.scalar(select(LineageRevision).where(LineageRevision.id == revision.parent_revision_id,
            LineageRevision.project_id == project.id, LineageRevision.revision_no < revision.revision_no)) if revision.parent_revision_id else None
        if parent is None:
            gaps.append(SkillGap(code="revision_baseline_missing", message="所选血缘版本缺少可见前置版本，无法计算脚本差异"))
        else:
            diff = LineageRevisionService(db).diff(revision, parent)
            relevant = []
            for item in diff["items"]:
                if any(str(item.get(side, {}).get(key)) in endpoint_keys for side in ("old_value", "new_value")
                       for key in ("node_key", "source_node_key", "target_node_key")):
                    relevant.append(item)
            material = {"from_revision_id": parent.id, "from_graph_hash": parent.graph_hash,
                        "to_revision_id": revision.id, "to_graph_hash": revision.graph_hash,
                        "scope": "selected_endpoints", "items": relevant}
            facts.append(evidence(project, scope, "script_diff", "lineage_revision_diff", revision.id, material, f"parent:{parent.id}"))
    if "prior_human_decisions" in providers:
        targets = {node.get("target_field_id") for node in endpoints if node.get("target_field_id")}
        rows = db.scalars(select(RequirementGenerationItem)
            .join(RequirementGenerationInput, RequirementGenerationInput.id == RequirementGenerationItem.input_id)
            .join(Requirement, Requirement.id == RequirementGenerationInput.requirement_id)
            .join(RequirementRevision, RequirementRevision.id == RequirementGenerationInput.revision_id)
            .join(TargetField, TargetField.id == RequirementGenerationItem.field_id)
            .where(RequirementGenerationInput.project_id == project.id, Requirement.project_id == project.id,
                RequirementRevision.project_id == project.id, TargetField.project_id == project.id,
                RequirementRevision.requirement_id == Requirement.id, RequirementGenerationItem.field_id.in_(targets),
                RequirementGenerationItem.decision.in_(["adopted", "rejected"]),
                RequirementGenerationItem.decided_by.is_not(None),
                RequirementGenerationItem.decided_at <= revision.created_at)
            .order_by(RequirementGenerationItem.decided_at.desc(), RequirementGenerationItem.id.desc()).limit(21)).all() if targets else []
        if len(rows) > 20:
            raise HTTPException(409, detail={"error_code": "history_scope_exceeded", "gaps": [{"code": "history_scope_exceeded", "message": "人工历史超过 20 条，请缩小目标范围"}]})
        for row in rows:
            material = {"field_id": row.field_id, "input_id": row.input_id, "section": row.section,
                "decision": row.decision, "reason": row.decision_reason, "decided_by": row.decided_by,
                "decided_at": str(row.decided_at), "adopted_content_version": row.adopted_content_version,
                "interpretation": "历史人工决策只提供上下文，不构成本次候选的人工确认"}
            facts.append(evidence(project, scope, "prior_human_decision", "requirement_generation_item", row.id, material, f"input:{row.input_id}"))
        if not rows:
            gaps.append(SkillGap(code="prior_human_decision_missing", message="所选目标字段缺少血缘时点之前的可追溯人工决策"))
    return facts, gaps
