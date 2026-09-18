"""Freeze explicitly selected parser facts inside existing requirement revisions.

This module never loads or executes uploaded files. Older script versions remain
selectable even when their edges are no longer enabled in the live graph.
"""
from copy import deepcopy

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.models import (CatalogClassification, CatalogColumn, CatalogTable, LineageEdge,
    LineageNode, ScriptFile, ScriptFileVersion, SqlStatement, TargetTable, TemplateVersion)
from app.services.requirement_revisions import append_revision, load_revision
from app.services.requirement_scope import content_digest


class ScriptSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    script_version_ids: list[int] = Field(min_length=1, max_length=50)


class ConfirmScriptBasis(ScriptSelection):
    expected_content_version: int = Field(gt=0)
    preview_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    template_version_id: int = Field(gt=0)
    target_key: str = Field(min_length=1, max_length=1000)
    # Explicitly confirmed physical output column -> requirement field ID.
    field_bindings: dict[str, int] = Field(default_factory=dict, max_length=500)


def table_key(node):
    # JSON preserves missing schema/database instead of silently guessing them.
    import json
    return json.dumps([node.database_name, node.schema_name, node.table_name], ensure_ascii=False)


def script_preview(db, project_id, version_ids):
    versions = list(db.execute(select(ScriptFileVersion, ScriptFile).join(
        ScriptFile, ScriptFile.id == ScriptFileVersion.script_file_id).where(
        ScriptFileVersion.project_id == project_id, ScriptFile.project_id == project_id,
        ScriptFile.enabled.is_(True), ScriptFileVersion.id.in_(version_ids)
    ).order_by(ScriptFileVersion.id)))
    if {v.id for v, _ in versions} != set(version_ids):
        raise HTTPException(404, "所选脚本版本不存在或不可见")
    if len({s.id for _, s in versions}) != len(versions):
        raise HTTPException(422, "同一脚本只能选择一个版本")
    statements = list(db.scalars(select(SqlStatement).where(SqlStatement.project_id == project_id,
        SqlStatement.script_file_version_id.in_(version_ids)).order_by(SqlStatement.id)))
    edges = list(db.scalars(select(LineageEdge).where(LineageEdge.project_id == project_id,
        LineageEdge.script_file_version_id.in_(version_ids)).order_by(LineageEdge.id).limit(2001)))
    if len(edges) > 2000 or len(statements) > 500:
        raise HTTPException(422, "脚本解析事实超出预览上限，请缩小选择范围")
    node_ids = {i for e in edges for i in (e.source_node_id, e.target_node_id)}
    nodes = {n.id: n for n in db.scalars(select(LineageNode).where(
        LineageNode.project_id == project_id, LineageNode.id.in_(node_ids)))}
    if set(nodes) != node_ids:
        raise HTTPException(409, "脚本血缘节点不完整")
    column_tables = dict(db.execute(select(CatalogColumn.id, CatalogColumn.catalog_table_id).where(
        CatalogColumn.project_id == project_id, CatalogColumn.enabled.is_(True),
        CatalogColumn.id.in_([n.catalog_column_id for n in nodes.values() if n.catalog_column_id]))).all())
    def catalog_id(node):
        return node.catalog_table_id or column_tables.get(node.catalog_column_id)
    from app.services.data_architecture import current_assignment, get_architecture
    architecture = get_architecture(db, project_id=project_id)
    metadata = {}
    for node in nodes.values():
        if catalog_id(node) and catalog_id(node) not in metadata:
            table = db.scalar(select(CatalogTable).where(CatalogTable.id == catalog_id(node),
                CatalogTable.project_id == project_id, CatalogTable.enabled.is_(True)))
            if table:
                assignment = db.scalar(select(CatalogClassification).where(
                    CatalogClassification.project_id == project_id, CatalogClassification.catalog_table_id == table.id))
                metadata[table.id] = {"id": table.id, "database_name": table.database_name,
                    "schema_name": table.schema_name, "table_name": table.table_name,
                    "assignment": current_assignment(assignment, architecture),
                    "architecture_revision_id": assignment.architecture_revision_id if assignment else None,
                    "columns": [{"id": c.id, "name": c.column_name, "data_type": c.data_type, "comment": c.column_comment}
                        for c in db.scalars(select(CatalogColumn).where(CatalogColumn.project_id == project_id,
                            CatalogColumn.catalog_table_id == table.id, CatalogColumn.enabled.is_(True)).order_by(CatalogColumn.id))]}
    def ref(node):
        return {"node_id": node.id, "table_key": table_key(node), "database_name": node.database_name,
            "schema_name": node.schema_name, "table_name": node.table_name, "column_name": node.column_name,
            "node_type": node.node_type, "catalog_table_id": catalog_id(node),
            "unresolved": node.unresolved_flag, "temporary": node.temporary_flag}
    targets = {}
    rules = []
    gaps = []
    produced = {(table_key(nodes[e.target_node_id]), nodes[e.target_node_id].column_name) for e in edges}
    for edge in edges:
        source, target = nodes[edge.source_node_id], nodes[edge.target_node_id]
        if target.table_name:
            entry = targets.setdefault(table_key(target), {"key": table_key(target),
                "database_name": target.database_name, "schema_name": target.schema_name,
                "table_name": target.table_name, "columns": []})
            if target.column_name and target.column_name not in entry["columns"]:
                entry["columns"].append(target.column_name)
        rules.append({"rule_id": f"script-edge-{edge.id}", "script_version_id": edge.script_file_version_id,
            "statement_id": edge.statement_id, "source_line_start": edge.source_line_start,
            "source_line_end": edge.source_line_end, "source": ref(source), "target": ref(target),
            **{key: getattr(edge, key) for key in ("edge_type", "transformation_type", "transformation_expression",
                "join_condition", "filter_condition", "aggregation_rule", "code_mapping_rule", "confidence_level")}})
        if (source.unresolved_flag and source.node_type != "constant"
                and (table_key(source), source.column_name) not in produced):
            gaps.append(f"未核验上游元数据：{source.logical_name}")
        if source.temporary_flag or target.temporary_flag:
            gaps.append("临时表解析范围尚未核验")
    import sqlglot
    from sqlglot import exp
    for statement in statements:
        gaps.extend(statement.warnings_json or [])
        try:
            tree = sqlglot.parse_one(statement.normalized_sql, read=statement.dialect or None)
            if isinstance(tree, exp.Insert) and not isinstance(tree.this, exp.Schema):
                gaps.append(f"语句 {statement.id} 缺少显式目标字段列表，不能据此确认字段顺序")
            if tree is not None and any(tree.find_all(exp.Star)):
                gaps.append(f"语句 {statement.id} 的星号需要元数据展开核验")
            if isinstance(tree, (exp.Command, exp.Create)) and (not isinstance(tree, exp.Create) or tree.kind != "TABLE"):
                gaps.append(f"语句 {statement.id} 含过程或命令，解析不完整")
        except (sqlglot.errors.ParseError, ValueError):
            gaps.append(f"语句 {statement.id} 无法完整解析")
    for version, script in versions:
        gaps.extend(version.warnings_json or [])
        if version.parse_status != "parsed" or script.file_type != "sql":
            gaps.append(f"脚本 {script.relative_path} 解析状态为 {version.parse_status}，须核验支持范围")
    if not targets:
        gaps.append("未识别可确认的写入目标")
    result = {"policy_version": "requirement-script-basis-v1",
        "versions": [{"id": v.id, "script_file_id": s.id, "version_no": v.version_no,
            "file_hash": v.file_hash, "path": s.relative_path, "dialect": v.dialect,
            "parse_status": v.parse_status} for v, s in versions],
        "statements": [{"id": s.id, "script_version_id": s.script_file_version_id,
            "statement_index": s.statement_index, "raw_sql_hash": s.raw_sql_hash,
            "source_line_start": s.source_line_start, "source_line_end": s.source_line_end,
            "statement_type": s.statement_type, "parse_status": s.parse_status} for s in statements],
        "targets": list(targets.values()), "rules": rules, "metadata": list(metadata.values()),
        "gaps": sorted(set(gaps))}
    result["preview_hash"] = content_digest(result)
    return result


def confirm_script_basis(db, requirement, payload, actor_id):
    previous = load_revision(db, requirement.project_id, requirement.id, payload.expected_content_version)
    if requirement.content_version != previous.content_version or previous.status != "draft":
        raise HTTPException(409, "只能为当前草稿确认脚本依据")
    basis = script_preview(db, requirement.project_id, payload.script_version_ids)
    if basis["preview_hash"] != payload.preview_hash:
        raise HTTPException(409, "解析事实或元数据已变化，请重新预览")
    target = next((t for t in basis["targets"] if t["key"] == payload.target_key), None)
    if target is None:
        raise HTTPException(422, "请确认所选脚本实际写入的目标")
    template = db.scalar(select(TemplateVersion).where(TemplateVersion.id == payload.template_version_id,
        TemplateVersion.project_id == requirement.project_id))
    regulator = db.get(TargetTable, requirement.scope_json["target_table_id"])
    if template is None or regulator is None or regulator.project_id != requirement.project_id:
        raise HTTPException(404, "监管目标或模板版本不存在或不可见")
    sheets = [sheet for sheet in template.parsed_snapshot_json or []
        if str(sheet.get("table_code") or sheet.get("sheet_name")) == regulator.table_code]
    if not sheets:
        raise HTTPException(422, "目标监管表不在所选模板版本中")
    field_ids = set(requirement.scope_json["field_ids"])
    if (not set(payload.field_bindings) <= set(target["columns"])
            or not set(payload.field_bindings.values()) <= field_ids
            or len(set(payload.field_bindings.values())) != len(payload.field_bindings)):
        raise HTTPException(422, "字段关联必须来自本需求字段及已识别的目标列，且不能重复关联")
    basis["confirmation"] = {"target_key": payload.target_key, "target_table_id": regulator.id,
        "field_bindings": payload.field_bindings, "field_ids": sorted(field_ids), "actor_id": actor_id}
    basis["template"] = {"id": template.id, "version_no": template.version_no, "file_hash": template.file_hash,
        "regulatory_version": template.regulatory_version, "status": template.status, "tables": deepcopy(sheets)}
    missing = field_ids - set(payload.field_bindings.values())
    basis["gaps"].extend(f"需求字段 {i} 尚未确认对应脚本输出列" for i in sorted(missing))
    from app.services.knowledge_eligibility import requirement_evidence
    evidence = requirement_evidence(db, requirement.project_id, requirement.scope_json.get("document_ids", []),
        requirement.scope_json.get("scenario_id"))
    if len(evidence) > 500:
        raise HTTPException(422, "制度片段超出固定输入限制，请缩小资料范围")
    basis["policy_snapshot"] = {"allowed": {"document_ids": sorted(set(requirement.scope_json.get("document_ids", [])))},
        "requirement": {"scenario_id": requirement.scope_json.get("scenario_id")}, "evidence": evidence}
    if not evidence:
        basis["gaps"].append("缺少依据：没有明确选择且当前有效的制度条款；脚本事实不能替代制度要求")
    basis["gaps"].append("制度条款与脚本规则的逐条对照尚未人工确认")
    content = deepcopy(previous.content_json)
    content["script_basis"] = basis
    # Existing authored text and Mapping review conditions remain authoritative.
    content["gaps"] = [g for g in content["gaps"] if not g["id"].startswith("scope:script:")]
    content["gaps"].extend({"id": f"scope:script:{i}", "field_id": None,
        "origin": "analysis", "status": "open", "message": message}
        for i, message in enumerate(basis["gaps"]))
    from app.services.requirement_policy_comparison import basis_hash, sync_comparison_gaps
    if content.get("policy_comparisons", {}).get("basis_hash") != basis_hash(basis):
        content.pop("policy_comparisons", None)
    sync_comparison_gaps(content)
    return append_revision(db, requirement, content, previous.content_version, actor_id)


def script_basis_changes(db, project_id, content):
    """Read-only drift detection: never rewrites historical requirements."""
    basis = content.get("script_basis")
    if not basis:
        return []
    changes = []
    for frozen in basis["versions"]:
        script = db.scalar(select(ScriptFile).where(ScriptFile.project_id == project_id,
            ScriptFile.id == frozen["script_file_id"]))
        if script is None or not script.enabled or script.current_version_no != frozen["version_no"]:
            changes.append({"code": f"script:{frozen['script_file_id']}", "message": f"脚本 {frozen['path']} 已变化或停用",
                "frozen_version": frozen["version_no"], "current_version": script.current_version_no if script else None})
    try:
        current = script_preview(db, project_id, [v["id"] for v in basis["versions"]])
        if current["preview_hash"] != basis["preview_hash"]:
            changes.append({"code": "script:metadata", "message": "固定脚本的解析事实、表结构或归属已变化"})
    except HTTPException:
        changes.append({"code": "script:unavailable", "message": "固定脚本依据当前不可核验"})
    from app.models import TemplateDocument
    version = db.scalar(select(TemplateVersion).where(TemplateVersion.project_id == project_id,
        TemplateVersion.id == basis["template"]["id"]))
    document = db.get(TemplateDocument, version.template_document_id) if version else None
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    def utc(value):
        return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value
    if (version is None or version.status != "active" or version.file_hash != basis["template"]["file_hash"]
            or (document and document.current_version_id != version.id)
            or (version.effective_at and utc(version.effective_at) > now)
            or (version.expires_at and utc(version.expires_at) <= now)
            or [sheet for sheet in version.parsed_snapshot_json or [] if sheet in basis["template"]["tables"]]
                != basis["template"]["tables"]):
        changes.append({"code": "script:template", "message": "监管模板不是当前生效版本或已发生变化"})
    from app.services.knowledge_eligibility import validate_frozen_requirement_evidence
    try:
        validate_frozen_requirement_evidence(db, project_id, basis["policy_snapshot"])
    except HTTPException:
        changes.append({"code": "script:policy", "message": "制度依据已失效、变化或不再适用于当前项目"})
    return changes
