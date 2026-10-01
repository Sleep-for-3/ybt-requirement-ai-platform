"""Builtin agent tools that are not backed by an AI-skill adapter.

Every handler re-enforces project scope itself: this codebase keeps permission
logic out of services, so a tool that skipped the check would be a bypass.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from sqlalchemy import or_, select

from app.models import (
    AgentStep,
    ImpactAnalysis,
    MartField,
    MartTable,
    RegulatoryKnowledgeItem,
    ScriptFile,
    ScriptFileVersion,
    SourceField,
    SourceTable,
    SqlStatement,
    TargetField,
)
from app.services.agent.tools.evidence import (
    confidentiality_of,
    evidence,
    gap,
    knowledge_evidence,
    policy_clause_evidence,
    project_scope,
)
from app.services.agent.tools.registry import (
    AgentToolSpec,
    ToolContext,
    ToolExecutionError,
    ToolResult,
    register_tool,
)
from app.services.auth.permission_service import PermissionService
from app.services.lineage.path_resolver import LineagePathResolver, LineagePathNotFound
from app.services.lineage.semantic_impact import resolve_semantic_impact
from app.services.llm.execution_metadata import stable_hash
from app.services.metadata.catalog_service import like_pattern, search_catalog
from app.services.retrieval.hybrid_retriever import HybridRetriever
from app.schemas.ai_skill import (
    SkillEvidence,
    SkillInputEnvelope,
    SkillPolicyComparison,
    validate_policy_comparison,
)
from app.schemas.metadata import CatalogSearchRequest

MAX_TOOL_ROWS = 50
MAX_ROWS_PER_SOURCE = 20


def _require(ctx: ToolContext, permission: str) -> None:
    """Fail-closed project permission check for a tool invocation."""

    PermissionService(ctx.db, ctx.principal).require_project_permission(ctx.project_id, permission)


def _clip(value: Any, limit: int = 300) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[: limit - 1] + "…"
    if isinstance(value, dict):
        return {str(key): _clip(item, limit) for key, item in list(value.items())[:40]}
    if isinstance(value, list):
        return [_clip(item, limit) for item in value[:40]]
    return value


# --------------------------------------------------------------------------------------
# 1. search_regulatory_knowledge
# --------------------------------------------------------------------------------------
def _search_regulatory_knowledge(ctx: ToolContext) -> ToolResult:
    _require(ctx, "knowledge.search")
    query = str(ctx.tool_input.get("query") or ctx.task.objective or "").strip()
    top_k = int(ctx.tool_input.get("top_k") or 10)
    mode = str(ctx.tool_input.get("retrieval_mode") or "hybrid")
    if not query:
        raise ToolExecutionError("query_required", "监管知识检索需要 query 或任务目标。")
    scope = project_scope(ctx.task)
    confidentiality = confidentiality_of(ctx.project)

    facts: list[dict[str, Any]] = []
    policy: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    hits: list[dict[str, Any]] = []
    degraded: str | None = None

    try:
        _, hits = HybridRetriever(ctx.db).search(
            ctx.project_id, query, top_k=top_k, created_by=ctx.principal.user_id,
            retrieval_mode=mode, commit=False,
        )
    except Exception as exc:  # retrieval degradation must not fail the whole task
        degraded = "knowledge_retrieval_unavailable"
        gaps.append(gap("knowledge_retrieval_unavailable", f"知识检索不可用：{type(exc).__name__}").model_dump(mode="json"))

    for hit in hits:
        clause, clause_gap = policy_clause_evidence(hit, scope=scope, confidentiality=confidentiality)
        if clause is not None:
            policy.append(clause.model_dump(mode="json"))
            continue
        if clause_gap is not None:
            gaps.append(clause_gap.model_dump(mode="json"))
        # Everything non-normative is still recorded, but only as a fact.
        non_normative = knowledge_evidence(hit, scope=scope, confidentiality=confidentiality)
        if non_normative is not None:
            facts.append(non_normative.model_dump(mode="json"))

    if not policy:
        rows = list(ctx.db.scalars(select(RegulatoryKnowledgeItem).where(
            RegulatoryKnowledgeItem.project_id == ctx.project_id,
            or_(
                RegulatoryKnowledgeItem.question_text.ilike(like_pattern(query), escape="\\"),
                RegulatoryKnowledgeItem.answer_text.ilike(like_pattern(query), escape="\\"),
                RegulatoryKnowledgeItem.target_field_name.ilike(like_pattern(query), escape="\\"),
                RegulatoryKnowledgeItem.target_field_code.ilike(like_pattern(query), escape="\\"),
            ),
        ).order_by(RegulatoryKnowledgeItem.id.desc()).limit(min(top_k, MAX_TOKEN_ROWS))).all())
        for row in rows:
            facts.append(evidence(
                evidence_id=f"regulatory_knowledge_item:{row.id}",
                kind="regulatory_knowledge_item",
                value={"question": _clip(row.question_text), "answer": _clip(row.answer_text), "knowledge_type": row.knowledge_type},
                source_type="regulatory_knowledge_item",
                source_id=row.id,
                locator=row.source_document_name or row.source_cell_range,
                scope=scope,
                confidentiality=confidentiality,
            ).model_dump(mode="json"))
        if rows and not hits:
            degraded = "knowledge_units_empty_used_knowledge_items"
        if not rows and not hits:
            gaps.append(gap("missing_basis", "未检索到任何监管知识依据，结论必须标记为缺少依据。").model_dump(mode="json"))

    evidence_refs = [item["id"] for item in [*policy, *facts]]
    return ToolResult(
        facts=facts,
        policy_evidence=policy,
        gaps=gaps,
        evidence_refs=evidence_refs,
        degraded_path=degraded,
        model_metadata={"retrieval_mode": mode, "hit_count": len(hits)},
        output={
            "query": query,
            "hit_count": len(hits),
            "policy_clause_count": len(policy),
            "fact_count": len(facts),
            "top_titles": [item["value"].get("title") for item in policy[:5] if isinstance(item.get("value"), dict)],
        },
        step_output={"policy_clause_ids": [item["id"] for item in policy], "fact_ids": [item["id"] for item in facts]},
    )


MAX_TOKEN_ROWS = MAX_ROWS_PER_SOURCE


# --------------------------------------------------------------------------------------
# 2. search_metadata
# --------------------------------------------------------------------------------------
def _search_metadata(ctx: ToolContext) -> ToolResult:
    _require(ctx, "catalog.search")
    query = str(ctx.tool_input.get("query") or ctx.task.objective or "").strip()
    top_k = min(int(ctx.tool_input.get("top_k") or 20), MAX_TOOL_ROWS)
    scope = project_scope(ctx.task)
    confidentiality = confidentiality_of(ctx.project)
    pattern = like_pattern(query)
    facts: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []

    catalog_rows = search_catalog(ctx.db, ctx.project_id, CatalogSearchRequest(query=query, top_k=top_k))
    for row in catalog_rows:
        rows.append({"layer": "catalog", **{key: _clip(value, 120) for key, value in row.items()}})
        facts.append(evidence(
            evidence_id=f"catalog:{row['catalog_column_id']}",
            kind="catalog_field",
            value={
                "database_name": row.get("database_name"), "schema_name": row.get("schema_name"),
                "table_name": row.get("table_name"), "column_name": row.get("column_name"),
                "column_comment": _clip(row.get("column_comment"), 200), "data_type": row.get("data_type"),
                "score": row.get("score"),
            },
            source_type="catalog_column",
            source_id=row["catalog_column_id"],
            locator=f"{row.get('schema_name')}.{row.get('table_name')}.{row.get('column_name')}",
            scope=scope,
            confidentiality=confidentiality,
        ).model_dump(mode="json"))

    registered = (
        ("source_table", SourceTable, ("table_code", "table_name", "table_comment", "description"), "table_name", "table_code"),
        ("source_field", SourceField, ("field_code", "field_name", "field_comment", "description"), "field_name", "field_code"),
        ("mart_table", MartTable, ("table_code", "table_name", "table_comment", "description"), "table_name", "table_code"),
        ("mart_field", MartField, ("field_code", "field_name", "field_comment", "description"), "field_name", "field_code"),
    )
    for kind, model, columns, label_attr, code_attr in registered:
        filters = [getattr(model, name).ilike(pattern, escape="\\") for name in columns if hasattr(model, name)]
        if not filters:
            continue
        for row in ctx.db.scalars(select(model).where(model.project_id == ctx.project_id, or_(*filters)).limit(top_k)).all():
            rows.append({"layer": kind, "id": row.id, "name": _clip(getattr(row, label_attr), 120), "code": _clip(getattr(row, code_attr), 120)})
            facts.append(evidence(
                evidence_id=f"{kind}:{row.id}",
                kind=kind,
                value={"name": getattr(row, label_attr), "code": getattr(row, code_attr)},
                source_type=kind,
                source_id=row.id,
                locator=getattr(row, code_attr),
                scope=scope,
                confidentiality=confidentiality,
            ).model_dump(mode="json"))

    gaps = []
    if not facts:
        gaps.append(gap("metadata_not_found", f"元数据目录中没有与 {query!r} 匹配的表或字段。").model_dump(mode="json"))
    return ToolResult(
        facts=facts,
        gaps=gaps,
        evidence_refs=[item["id"] for item in facts],
        output={"query": query, "catalog_match_count": len(catalog_rows), "registered_match_count": len(facts) - len(catalog_rows), "rows": rows[:top_k]},
        step_output={"catalog_column_ids": [row["catalog_column_id"] for row in catalog_rows], "fact_ids": [item["id"] for item in facts]},
    )


# --------------------------------------------------------------------------------------
# 3. get_lineage
# --------------------------------------------------------------------------------------
def _get_lineage(ctx: ToolContext) -> ToolResult:
    _require(ctx, "lineage.view")
    root_type = str(ctx.tool_input.get("root_entity_type") or "target_field")
    root_id = ctx.tool_input.get("root_entity_id") or ctx.tool_input.get("target_field_id")
    if not isinstance(root_id, int) or isinstance(root_id, bool):
        root_id = (ctx.step.input_json or {}).get("subject", {}).get("target_field_id")
    direction = str(ctx.tool_input.get("direction") or "both")
    depth = int(ctx.tool_input.get("depth") or 3)
    if not isinstance(root_id, int) or isinstance(root_id, bool):
        return ToolResult(
            status="skipped",
            gaps=[gap("lineage_root_missing", "任务没有可用的目标字段主体，血缘查询按缺口跳过。").model_dump(mode="json")],
            output={"root_entity_type": root_type, "node_count": 0, "edge_count": 0},
        )
    scope = project_scope(ctx.task)
    confidentiality = confidentiality_of(ctx.project)
    try:
        graph = LineagePathResolver(ctx.db).resolve(
            ctx.project_id, root_entity_type=root_type, root_entity_id=root_id,
            direction=direction, depth=max(1, min(depth, 10)), max_paths=20,
        )
    except LineagePathNotFound as exc:
        return ToolResult(status="blocked", gaps=[gap("lineage_root_not_found", str(exc)).model_dump(mode="json")],
                          output={"root_entity_type": root_type, "root_entity_id": root_id})
    except ValueError as exc:
        raise ToolExecutionError("lineage_root_invalid", str(exc)) from exc

    nodes = graph.get("nodes", []) or []
    edges = graph.get("edges", []) or []
    facts = []
    for node in nodes[:MAX_TOOL_ROWS]:
        node_id = node.get("id") or node.get("node_id")
        facts.append(evidence(
            evidence_id=f"lineage_node:{node_id}",
            kind="lineage_node",
            value={"name": node.get("label") or node.get("name"), "node_type": node.get("node_type"), "layer": node.get("layer")},
            source_type="lineage_node",
            source_id=node_id,
            locator=node.get("label") or node.get("name"),
            scope=scope,
            confidentiality=confidentiality,
        ).model_dump(mode="json"))
    for edge in edges[:MAX_TOOL_ROWS]:
        edge_id = edge.get("id") or edge.get("edge_id")
        facts.append(evidence(
            evidence_id=f"lineage_edge:{edge_id}",
            kind="lineage_edge",
            value={
                "edge_type": edge.get("edge_type"), "source": edge.get("source"), "target": edge.get("target"),
                "transformation_type": edge.get("transformation_type"),
                "filter_condition": _clip(edge.get("filter_condition"), 200),
            },
            source_type="lineage_edge",
            source_id=edge_id,
            locator=f"{edge.get('source')}->{edge.get('target')}",
            scope=scope,
            confidentiality=confidentiality,
        ).model_dump(mode="json"))

    gaps = [gap(code=str(item.get("code") or "lineage_gap"), message=str(item.get("message") or ""), source_ref=item.get("source_ref")).model_dump(mode="json")
            for item in (graph.get("gaps") or [])[:20]]
    if not nodes:
        gaps.append(gap("lineage_empty", "该目标没有已解析的血缘节点。").model_dump(mode="json"))
    return ToolResult(
        facts=facts,
        gaps=gaps,
        evidence_refs=[item["id"] for item in facts],
        output={
            "root_entity_type": root_type, "root_entity_id": root_id, "direction": direction,
            "node_count": len(nodes), "edge_count": len(edges), "truncated": bool(graph.get("truncated")),
            "paths": _clip(graph.get("paths"), 200)[:5] if isinstance(graph.get("paths"), list) else [],
        },
        step_output={"node_count": len(nodes), "edge_count": len(edges)},
    )


# --------------------------------------------------------------------------------------
# 4. analyze_lineage_impact
# --------------------------------------------------------------------------------------
def _analyze_lineage_impact(ctx: ToolContext) -> ToolResult:
    _require(ctx, "impact.view")
    scope = project_scope(ctx.task)
    confidentiality = confidentiality_of(ctx.project)
    impact_id = ctx.tool_input.get("impact_id")
    facts: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []

    if isinstance(impact_id, int):
        impact = ctx.db.get(ImpactAnalysis, impact_id)
        if impact is None or impact.project_id != ctx.project_id:
            raise ToolExecutionError("impact_not_found", "影响分析不存在或不属于当前项目。")
        facts.append(evidence(
            evidence_id=f"impact:{impact.id}",
            kind="impact_analysis",
            value={
                "severity": impact.severity, "status": impact.status,
                "affected_target_field_ids": impact.affected_target_field_ids_json,
                "affected_mapping_ids": impact.affected_mapping_ids_json,
            },
            source_type="impact_analysis",
            source_id=impact.id,
            locator=f"impact:{impact.id}",
            scope=scope,
            confidentiality=confidentiality,
        ).model_dump(mode="json"))
        return ToolResult(
            facts=facts,
            gaps=gaps,
            evidence_refs=[item["id"] for item in facts],
            output={"impact_id": impact.id, "severity": impact.severity, "status": impact.status,
                    "summary": _clip(impact.summary_json, 400), "open_questions": _clip(impact.open_questions_json, 200)},
            step_output={"impact_id": impact.id, "severity": impact.severity},
        )

    source_field_ids = [int(item) for item in (ctx.tool_input.get("source_field_ids") or [])][:50]
    mart_field_ids = [int(item) for item in (ctx.tool_input.get("mart_field_ids") or [])][:50]
    target_field_ids = [int(item) for item in (ctx.tool_input.get("target_field_ids") or [])][:50]
    if not any((source_field_ids, mart_field_ids, target_field_ids)):
        subject = (ctx.step.input_json or {}).get("subject") or {}
        if isinstance(subject.get("target_field_id"), int):
            target_field_ids = [int(subject["target_field_id"])]
    if not any((source_field_ids, mart_field_ids, target_field_ids)):
        return ToolResult(
            status="skipped",
            gaps=[gap("impact_scope_missing", "任务没有可用的字段范围，影响分析按缺口跳过。").model_dump(mode="json")],
            output={"binding_ids": [], "concept_ids": [], "requirement_ids": []},
        )
    resolved = resolve_semantic_impact(
        ctx.db, project_id=ctx.project_id, source_field_ids=source_field_ids,
            mart_field_ids=mart_field_ids, target_field_ids=target_field_ids,
            mapping_entity_ids={},
    )
    facts.append(evidence(
        evidence_id=f"semantic_impact:{stable_hash({'s': source_field_ids, 'm': mart_field_ids, 't': target_field_ids})[:16]}",
        kind="semantic_impact_scope",
        value={
            "binding_ids": resolved.binding_ids, "concept_ids": resolved.concept_ids,
            "regulatory_knowledge_item_ids": resolved.regulatory_knowledge_item_ids,
            "requirement_ids": resolved.requirement_ids,
        },
        source_type="semantic_impact_scope",
        source_id=ctx.task.id,
        locator="semantic-impact",
        scope=scope,
        confidentiality=confidentiality,
    ).model_dump(mode="json"))
    downstream = bool(resolved.binding_ids or resolved.concept_ids or resolved.requirement_ids)
    if not downstream:
        gaps.append(gap("impact_empty", "未发现下游语义绑定、概念或需求受影响。").model_dump(mode="json"))
    return ToolResult(
        facts=facts,
        gaps=gaps,
        evidence_refs=[item["id"] for item in facts],
        output={"binding_ids": resolved.binding_ids, "concept_ids": resolved.concept_ids,
                "requirement_ids": resolved.requirement_ids, "knowledge_item_ids": resolved.regulatory_knowledge_item_ids},
        step_output={"binding_ids": resolved.binding_ids, "concept_ids": resolved.concept_ids},
    )


# --------------------------------------------------------------------------------------
# 5. inspect_sql_rule
# --------------------------------------------------------------------------------------
def _inspect_sql_rule(ctx: ToolContext) -> ToolResult:
    _require(ctx, "lineage.view")
    scope = project_scope(ctx.task)
    confidentiality = confidentiality_of(ctx.project)
    statement_id = ctx.tool_input.get("sql_statement_id")
    script_file_id = ctx.tool_input.get("script_file_id")
    limit = min(int(ctx.tool_input.get("limit") or 5), 20)
    facts: list[dict[str, Any]] = []
    statements: list[SqlStatement] = []

    query = select(SqlStatement)
    if isinstance(statement_id, int):
        statement = ctx.db.get(SqlStatement, statement_id)
        if statement is None:
            raise ToolExecutionError("sql_statement_not_found", "SQL 语句不存在。")
        statements = [statement]
    else:
        if not isinstance(script_file_id, int):
            # Deterministic discovery: the script that declares the subject field as its
            # logical target, else the project's first script. Never a guess about intent.
            subject = (ctx.step.input_json or {}).get("subject") or {}
            code = str(subject.get("target_field_code") or "")
            candidates = select(ScriptFile).where(ScriptFile.project_id == ctx.project_id)
            discovered = None
            if code:
                discovered = ctx.db.scalar(candidates.where(ScriptFile.logical_target_name == code)
                                          .order_by(ScriptFile.id))
            discovered = discovered or ctx.db.scalar(candidates.order_by(ScriptFile.id))
            if discovered is None:
                return ToolResult(
                    status="skipped",
                    gaps=[gap("sql_scope_missing", "当前项目没有可检查的脚本，实现检查按缺口跳过。").model_dump(mode="json")],
                    output={"statement_count": 0, "statements": []},
                )
            script_file_id = int(discovered.id)
        script = ctx.db.get(ScriptFile, script_file_id)
        if script is None or script.project_id != ctx.project_id:
            raise ToolExecutionError("script_not_found", "脚本不存在或不属于当前项目。")
        version = ctx.db.scalar(select(ScriptFileVersion).where(
            ScriptFileVersion.script_file_id == script.id,
            ScriptFileVersion.version_no == script.current_version_no,
        ))
        if version is None:
            raise ToolExecutionError("script_version_not_found", "脚本没有可解析的当前版本。")
        statements = list(ctx.db.scalars(query.where(SqlStatement.script_file_version_id == version.id)
                                          .order_by(SqlStatement.statement_index).limit(limit)).all())

    for statement in statements:
        facts.append(evidence(
            evidence_id=f"sql:{statement.id}",
            kind="script_statement",
            value={
                "statement_type": statement.statement_type,
                "normalized_sql": _clip(statement.normalized_sql, 800),
                "parse_status": statement.parse_status,
                "source_line_range": [statement.source_line_start, statement.source_line_end],
            },
            source_type="sql_statement",
            source_id=statement.id,
            source_version=statement.raw_sql_hash,
            locator=f"lines {statement.source_line_start}-{statement.source_line_end}",
            scope=scope,
            confidentiality=confidentiality,
        ).model_dump(mode="json"))

    gaps = []
    if not statements:
        gaps.append(gap("sql_rule_not_found", "当前项目没有匹配的 SQL/加工规则。").model_dump(mode="json"))
    return ToolResult(
        facts=facts,
        gaps=gaps,
        evidence_refs=[item["id"] for item in facts],
        output={"statement_count": len(statements),
                "statements": [{"statement_id": item.id, "statement_type": item.statement_type,
                                "parse_status": item.parse_status, "normalized_sql": _clip(item.normalized_sql, 400)} for item in statements]},
        step_output={"statement_ids": [item.id for item in statements]},
    )


# --------------------------------------------------------------------------------------
# 6. create_gap_report
# --------------------------------------------------------------------------------------
def _task_gaps(ctx: ToolContext) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    steps = list(ctx.db.scalars(select(AgentStep).where(AgentStep.task_id == ctx.task.id)
                                .order_by(AgentStep.order_index)).all())
    gaps: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    for step in steps:
        summary = step.output_summary_json or {}
        for item in summary.get("gaps") or []:
            gaps.append({"step_key": step.step_key, "tool_key": step.tool_key, **item})
        for item in summary.get("policy_comparisons") or []:
            if item.get("status") in {"conflict", "missing_implementation", "pending"}:
                comparisons.append({"step_key": step.step_key, **item})
        for item in step.gap_codes_json or []:
            if not any(existing.get("code") == item for existing in gaps):
                gaps.append({"step_key": step.step_key, "tool_key": step.tool_key, "code": item, "message": ""})
    return gaps, comparisons


def _create_gap_report(ctx: ToolContext) -> ToolResult:
    _require(ctx, "project.view")
    gaps, comparisons = _task_gaps(ctx)
    blocking = [item for item in comparisons if item.get("status") == "conflict"]
    unsupported = [item for item in gaps if item.get("code") in {"missing_basis", "clause_locator_missing", "model_output_unavailable", "context_budget_exceeded"}]
    summary = {
        "gap_count": len(gaps),
        "conflict_count": len(blocking),
        "missing_implementation_count": len([item for item in comparisons if item.get("status") == "missing_implementation"]),
        "unsupported_basis_count": len(unsupported),
        "requires_human_confirmation": bool(gaps or comparisons),
    }
    return ToolResult(
        gaps=[],
        output=summary,
        step_output={"gap_codes": sorted({str(item.get("code")) for item in gaps})},
        artifacts=[{
            "artifact_type": "gap_report",
            "title": "缺口与冲突报告",
            "status": "draft",
            "summary": {**summary, "gaps": gaps[:50], "comparisons": comparisons[:50]},
            "evidence_refs": [],
        }],
    )


# --------------------------------------------------------------------------------------
# 7. summarize_evidence
# --------------------------------------------------------------------------------------
def _summarize_evidence(ctx: ToolContext) -> ToolResult:
    _require(ctx, "project.view")
    steps = list(ctx.db.scalars(select(AgentStep).where(AgentStep.task_id == ctx.task.id)
                                .order_by(AgentStep.order_index)).all())
    by_kind: dict[str, int] = {}
    by_step: list[dict[str, Any]] = []
    total = 0
    for step in steps:
        summary = step.output_summary_json or {}
        facts = summary.get("facts") or []
        policy = summary.get("policy_evidence") or []
        for item in [*facts, *policy]:
            by_kind[str(item.get("kind"))] = by_kind.get(str(item.get("kind")), 0) + 1
        total += len(facts) + len(policy)
        by_step.append({
            "step_key": step.step_key, "tool_key": step.tool_key, "status": step.status,
            "fact_count": len(facts), "policy_clause_count": len(policy),
            "gap_count": len(summary.get("gaps") or []),
        })
    covered = [item for item in by_step if item["fact_count"] or item["policy_clause_count"]]
    coverage = round(len(covered) / len(by_step), 4) if by_step else 0.0
    return ToolResult(
        output={"evidence_count": total, "by_kind": by_kind, "evidence_coverage": coverage, "steps": by_step},
        step_output={"evidence_count": total},
        artifacts=[{
            "artifact_type": "evidence_summary",
            "title": "证据汇总",
            "status": "draft",
            "summary": {"evidence_count": total, "by_kind": by_kind, "evidence_coverage": coverage, "steps": by_step},
            "evidence_refs": [],
        }],
    )


# --------------------------------------------------------------------------------------
# 8. request_human_confirmation
# --------------------------------------------------------------------------------------
def _request_human_confirmation(ctx: ToolContext) -> ToolResult:
    _require(ctx, "project.view")
    gate_key = str(ctx.tool_input.get("gate_key") or "agent_human_confirmation")
    title = str(ctx.tool_input.get("title") or "Agent 人工确认")[:255]
    summary = ctx.tool_input.get("summary") if isinstance(ctx.tool_input.get("summary"), dict) else {}
    required_permission = str(ctx.tool_input.get("required_permission") or "final.review")
    return ToolResult(
        status="waiting_human",
        output={"gate_key": gate_key, "title": title, "required_permission": required_permission},
        human_gate={
            "gate_key": gate_key,
            "title": title,
            "summary": _clip(summary, 400),
            "required_permission": required_permission,
        },
        step_output={"gate_key": gate_key},
    )


IMPLEMENTATION_KINDS = frozenset({
    "script_statement", "lineage_edge", "lineage_node", "catalog_field", "source_field",
    "mart_field", "impact_analysis", "semantic_impact_scope",
})


def _collected_evidence(ctx: ToolContext) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Facts/policy collected by the other steps of the same task."""

    steps = ctx.db.scalars(select(AgentStep).where(
        AgentStep.task_id == ctx.task.id, AgentStep.id != ctx.step.id,
    ).order_by(AgentStep.order_index)).all()
    facts: dict[str, dict[str, Any]] = {}
    policy: dict[str, dict[str, Any]] = {}
    for step in steps:
        summary = step.output_summary_json or {}
        for item in summary.get("facts") or []:
            if isinstance(item, dict) and item.get("id"):
                facts.setdefault(str(item["id"]), item)
        for item in summary.get("policy_evidence") or []:
            if isinstance(item, dict) and item.get("id"):
                policy.setdefault(str(item["id"]), item)
    return list(facts.values()), list(policy.values())


def _project_field_tokens(ctx: ToolContext, limit: int = 300) -> set[str]:
    tokens: set[str] = set()
    for row in ctx.db.scalars(select(TargetField).where(TargetField.project_id == ctx.project_id).limit(limit)).all():
        for value in (row.field_code, row.field_name):
            text = str(value or "").strip()
            if len(text) >= 2:
                tokens.add(text)
    return tokens


def _evidence_text(item: SkillEvidence) -> str:
    return json.dumps(item.value, ensure_ascii=False) + " " + str(item.source.locator or "")


def _compare_policy_and_implementation(ctx: ToolContext) -> ToolResult:
    """Structural comparison only: the Agent never rules on regulatory compliance."""

    _require(ctx, "lineage.view")
    scope = project_scope(ctx.task)
    confidentiality = confidentiality_of(ctx.project)
    raw_facts, raw_policy = _collected_evidence(ctx)
    gaps: list[dict[str, Any]] = []
    facts: list[SkillEvidence] = []
    policy: list[SkillEvidence] = []
    rejected = 0
    for item in raw_facts:
        try:
            facts.append(SkillEvidence.model_validate(item))
        except Exception:  # noqa: BLE001 - contract violation is reported, not raised
            rejected += 1
    for item in raw_policy:
        try:
            policy.append(SkillEvidence.model_validate(item))
        except Exception:  # noqa: BLE001
            rejected += 1
    if rejected:
        gaps.append(gap("evidence_contract_violation", f"{rejected} 条历史证据未通过证据契约校验，已排除。").model_dump(mode="json"))
    if not policy:
        return ToolResult(
            status="blocked",
            gaps=[*gaps, gap("missing_basis", "没有可用的监管条款依据，无法开展监管与实现比对。").model_dump(mode="json")],
            output={"comparison_count": 0, "gap_count": len(gaps) + 1},
        )
    envelope = SkillInputEnvelope(
        skill_key="agent_policy_implementation_comparison", task_key="policy_implementation_comparison",
        scope=scope, subject_ref=f"agent-task:{ctx.task.id}", facts=facts, policy_evidence=policy, gaps=[],
    )
    tokens = _project_field_tokens(ctx)
    comparisons: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    for clause in envelope.policy_evidence:
        text = _evidence_text(clause)
        related_tokens = sorted({token for token in tokens if token in text})
        related = [item for item in envelope.facts if item.kind in IMPLEMENTATION_KINDS and related_tokens
                   and any(token in _evidence_text(item) for token in related_tokens)]
        if not related:
            gaps.append(gap("missing_implementation",
                            f"未找到与监管条款 {clause.id} 对应的实现证据（SQL/血缘/元数据）。",
                            source_ref=clause.id).model_dump(mode="json"))
            continue
        candidate = SkillPolicyComparison(
            status="pending", fact_ids=[item.id for item in related][:20], policy_clause_ids=[clause.id],
            rationale="已定位实现事实，但实现是否符合监管表述必须由模型或人工确认。",
            difference="Agent 不自行判定合规一致性，差异结论待人工确认。",
        )
        try:
            validate_policy_comparison(candidate, envelope)
        except ValueError as exc:
            gaps.append(gap("comparison_reference_invalid", str(exc)).model_dump(mode="json"))
            continue
        comparisons.append(candidate.model_dump(mode="json"))
    metadata: dict[str, Any] = {}
    degraded: str | None = None
    skill_key = ctx.tool_input.get("skill_key")
    if isinstance(skill_key, str) and skill_key:
        from app.services.ai_skills.runtime import execute_skill

        try:
            result = asyncio.run(execute_skill(ctx.db, ctx.principal, envelope.model_copy(update={"skill_key": skill_key})))
        except Exception as exc:  # noqa: BLE001 - a missing skill degrades, never breaks
            result = None
            degraded = "comparison_skill_failed"
            gaps.append(gap("comparison_skill_failed", f"比对技能调用失败：{type(exc).__name__}").model_dump(mode="json"))
        if result is None:
            degraded = degraded or "skill_binding_missing"
            gaps.append(gap("skill_binding_missing",
                            f"未找到已发布并绑定的比对技能 {skill_key}，仅输出确定性结论。").model_dump(mode="json"))
        else:
            comparisons.extend(result.get("policy_comparisons") or [])
            claims.extend(result.get("claims") or [])
            metadata = result.get("execution_metadata") or {}
    return ToolResult(
        claims=claims,
        policy_comparisons=comparisons,
        gaps=gaps,
        evidence_refs=sorted({item.id for item in envelope.policy_evidence} | {item.id for item in envelope.facts}),
        model_metadata=metadata,
        degraded_path=degraded,
        output={
            "comparison_count": len(comparisons), "gap_count": len(gaps),
            "policy_clause_count": len(envelope.policy_evidence),
            "implementation_fact_count": len(envelope.facts),
        },
        step_output={"comparison_count": len(comparisons)},
    )


def register_builtin_tools() -> None:
    register_tool(AgentToolSpec(
        tool_key="search_regulatory_knowledge",
        display_name="检索监管知识",
        description="在项目可访问的监管知识库中检索制度条款与知识条目，产出带条款定位的监管依据。",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer"},
                "retrieval_mode": {"type": "string", "enum": ["keyword_only", "vector_only", "hybrid"]},
            },
            "additionalProperties": False,
        },
        output_schema={"type": "object", "properties": {"hit_count": {"type": "integer"}, "policy_clause_count": {"type": "integer"}}},
        required_permissions=frozenset({"knowledge.search"}),
        risk_level="medium",
        timeout_seconds=60,
        retry_policy={"max_attempts": 2, "retry_on": ["knowledge_retrieval_unavailable"]},
        read_only=True,
        requires_human_confirmation=False,
        evidence_contract={"fact_kinds": ["knowledge_evidence", "regulatory_knowledge_item"], "policy_kinds": ["policy_clause"], "artifact_types": []},
        audit_fields=("query", "retrieval_mode", "hit_count"),
        handler=_search_regulatory_knowledge,
    ))
    register_tool(AgentToolSpec(
        tool_key="search_metadata",
        display_name="检索元数据",
        description="在元数据目录与项目登记的来源/集市/目标表字段中按关键词定位候选实体。",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}}, "additionalProperties": False},
        output_schema={"type": "object", "properties": {"catalog_match_count": {"type": "integer"}, "registered_match_count": {"type": "integer"}}},
        required_permissions=frozenset({"catalog.search"}),
        risk_level="low",
        timeout_seconds=45,
        retry_policy={"max_attempts": 2},
        read_only=True,
        requires_human_confirmation=False,
        evidence_contract={"fact_kinds": ["catalog_field", "source_field", "mart_field", "source_table", "mart_table"], "policy_kinds": [], "artifact_types": []},
        audit_fields=("query", "top_k"),
        handler=_search_metadata,
    ))
    register_tool(AgentToolSpec(
        tool_key="get_lineage",
        display_name="查询血缘",
        description="围绕目标字段/集市字段/来源字段/目录列查询上下游血缘路径与边，只读。",
        input_schema={
            "type": "object",
            "properties": {
                "root_entity_type": {"type": "string", "enum": ["target_field", "mart_field", "source_field", "catalog_column", "lineage_node"]},
                "root_entity_id": {"type": "integer"},
                "direction": {"type": "string", "enum": ["upstream", "downstream", "both"]},
                "depth": {"type": "integer"},
                "target_field_id": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        output_schema={"type": "object", "properties": {"node_count": {"type": "integer"}, "edge_count": {"type": "integer"}}},
        required_permissions=frozenset({"lineage.view"}),
        risk_level="low",
        timeout_seconds=60,
        retry_policy={"max_attempts": 2},
        read_only=True,
        requires_human_confirmation=False,
        evidence_contract={"fact_kinds": ["lineage_node", "lineage_edge"], "policy_kinds": [], "artifact_types": []},
        audit_fields=("root_entity_type", "root_entity_id", "direction", "depth"),
        handler=_get_lineage,
        requires_target_field=True,
    ))
    register_tool(AgentToolSpec(
        tool_key="analyze_lineage_impact",
        display_name="分析血缘影响",
        description="读取或计算字段变更的下游影响范围（语义绑定、概念、需求、知识条目）。",
        input_schema={
            "type": "object",
            "properties": {
                "impact_id": {"type": "integer"},
                "source_field_ids": {"type": "array", "items": {"type": "integer"}, "maxItems": 50},
                "mart_field_ids": {"type": "array", "items": {"type": "integer"}, "maxItems": 50},
                "target_field_ids": {"type": "array", "items": {"type": "integer"}, "maxItems": 50},
            },
            "additionalProperties": False,
        },
        output_schema={"type": "object", "properties": {"binding_ids": {"type": "array"}, "concept_ids": {"type": "array"}}},
        required_permissions=frozenset({"impact.view"}),
        risk_level="medium",
        timeout_seconds=90,
        retry_policy={"max_attempts": 1},
        read_only=True,
        requires_human_confirmation=False,
        evidence_contract={"fact_kinds": ["impact_analysis", "semantic_impact_scope"], "policy_kinds": [], "artifact_types": []},
        audit_fields=("impact_id",),
        handler=_analyze_lineage_impact,
    ))
    register_tool(AgentToolSpec(
        tool_key="inspect_sql_rule",
        display_name="检查 SQL 加工规则",
        description="读取目标字段相关脚本的当前 SQL 语句与解析状态，作为实现事实（不能作为监管依据）。",
        input_schema={
            "type": "object",
            "properties": {
                "script_file_id": {"type": "integer"},
                "sql_statement_id": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        output_schema={"type": "object", "properties": {"statement_count": {"type": "integer"}, "statements": {"type": "array"}}},
        required_permissions=frozenset({"lineage.view"}),
        risk_level="low",
        timeout_seconds=45,
        retry_policy={"max_attempts": 2},
        read_only=True,
        requires_human_confirmation=False,
        evidence_contract={"fact_kinds": ["script_statement"], "policy_kinds": [], "artifact_types": []},
        audit_fields=("script_file_id", "sql_statement_id"),
        handler=_inspect_sql_rule,
    ))
    register_tool(AgentToolSpec(
        tool_key="create_gap_report",
        display_name="生成缺口报告",
        description="汇总本任务所有步骤的缺口、冲突与缺失依据，形成结构化缺口报告产物。",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={"type": "object", "properties": {"gap_count": {"type": "integer"}, "conflict_count": {"type": "integer"}}},
        required_permissions=frozenset({"project.view"}),
        risk_level="low",
        timeout_seconds=30,
        retry_policy={"max_attempts": 1},
        read_only=False,
        requires_human_confirmation=False,
        evidence_contract={"fact_kinds": [], "policy_kinds": [], "artifact_types": ["gap_report"]},
        audit_fields=("gap_count", "conflict_count"),
        handler=_create_gap_report,
    ))
    register_tool(AgentToolSpec(
        tool_key="summarize_evidence",
        display_name="汇总证据",
        description="按步骤汇总本任务收集到的事实与监管依据，输出证据覆盖率与证据清单产物。",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={"type": "object", "properties": {"evidence_count": {"type": "integer"}, "evidence_coverage": {"type": "number"}}},
        required_permissions=frozenset({"project.view"}),
        risk_level="low",
        timeout_seconds=30,
        retry_policy={"max_attempts": 1},
        read_only=False,
        requires_human_confirmation=False,
        evidence_contract={"fact_kinds": [], "policy_kinds": [], "artifact_types": ["evidence_summary"]},
        audit_fields=("evidence_count",),
        handler=_summarize_evidence,
    ))
    register_tool(AgentToolSpec(
        tool_key="request_human_confirmation",
        display_name="请求人工确认",
        description="暂停 Agent 并创建受治理的人工确认节点，等待人工 approve/reject/edit/request_reanalysis 后继续。",
        input_schema={
            "type": "object",
            "properties": {
                "gate_key": {"type": "string"},
                "title": {"type": "string"},
                "required_permission": {"type": "string"},
                "summary": {"type": "object"},
            },
            "additionalProperties": False,
        },
        output_schema={"type": "object", "properties": {"gate_key": {"type": "string"}, "required_permission": {"type": "string"}}},
        required_permissions=frozenset({"project.view"}),
        risk_level="high",
        timeout_seconds=30,
        retry_policy={"max_attempts": 1},
        read_only=True,
        requires_human_confirmation=True,
        evidence_contract={"fact_kinds": [], "policy_kinds": [], "artifact_types": []},
        audit_fields=("gate_key", "required_permission"),
        handler=_request_human_confirmation,
    ))
    register_tool(AgentToolSpec(
        tool_key="compare_policy_and_implementation",
        display_name="对比监管要求与实现",
        description="把已收集的监管条款与实现事实（SQL/血缘/元数据）做结构化比对，输出待人工确认的一致性结论；不自行判定监管合规。",
        input_schema={
            "type": "object",
            "properties": {"skill_key": {"type": "string"}, "note": {"type": "string"}},
            "additionalProperties": False,
        },
        output_schema={"type": "object", "properties": {"comparison_count": {"type": "integer"}, "gap_count": {"type": "integer"}}},
        required_permissions=frozenset({"lineage.view"}),
        risk_level="high",
        timeout_seconds=90,
        retry_policy={"max_attempts": 1},
        read_only=True,
        requires_human_confirmation=True,
        evidence_contract={"fact_kinds": [], "policy_kinds": [], "artifact_types": []},
        audit_fields=("comparison_count", "skill_key"),
        handler=_compare_policy_and_implementation,
    ))


register_builtin_tools()
