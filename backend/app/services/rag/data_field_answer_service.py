"""Bounded, read-only field evidence collection and extractive model answers."""
import json
import re

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.models import (
    BusinessSystem, CatalogColumn, CatalogTable, DataSource, LineageEdge, LineageNode,
    MappingEvidenceReference, MartField, MartToYbtMapping, ProductScenario,
    ScenarioTechnicalLineage, SourceField, SourceTable, SourceToMartMapping, TargetField, Project,
)
from app.schemas.metadata import CatalogSearchRequest
from app.services.knowledge_evidence import document_citation, evidence_runtime, mode_knowledge_types
from app.services.llm.execution_metadata import build_execution_metadata, deterministic_execution_metadata, stable_hash
from app.services.llm.prompt_runtime import get_prompt_runtime, prepare_model_input, execute_runtime_chat_with_metadata
from app.services.metadata.catalog_service import search_catalog, like_pattern
from app.services.retrieval import HybridRetriever
from .citation_validator import validate_citations
from .grounded_answer_service import _invented_qualified_identifiers


class EvidenceExtract(BaseModel):
    citation_id: str
    text: str


class DataFieldOutput(BaseModel):
    # Extractive answers make unsupported relationships fail closed, not just names.
    claims: list[EvidenceExtract] = Field(default_factory=list, max_length=12)


def project_entity(db, model, entity_id, project_id):
    if entity_id is None:
        return None
    item = db.scalar(select(model).where(model.id == entity_id, model.project_id == project_id))
    if item is None:
        raise HTTPException(404, "Resource not found")
    return item


def _fields(item, names):
    return {name: getattr(item, name) for name in names.split()}


def _evidence_text(data):
    """Readable evidence, not a JSON dump masquerading as the business answer."""
    labels = {"source_system":"来源系统", "database":"数据库", "schema":"Schema", "table":"表", "field":"字段",
              "status":"状态", "comment":"说明", "join_condition":"关联条件", "filter_condition":"过滤条件",
              "processing_logic":"加工规则", "business_rule":"业务规则", "code_mapping_rule":"码值规则",
              "transformation_expression":"转换表达式", "source_system_name":"来源系统", "source_database_name":"数据库",
              "source_schema_name":"Schema", "source_table_english_name":"来源表", "source_field_english_name":"来源字段"}
    lines=[]
    for key,value in data.items():
        if value is None or key.endswith("_id") or key in {"nodes"}:
            continue
        lines.append(f"{labels.get(key,key)}：{value}")
    for node in data.get("nodes", []):
        lines.append("血缘节点：" + ".".join(str(node[k]) for k in ("database_name","schema_name","table_name","column_name") if node.get(k)))
    return "\n".join(lines)[:4000]


def collect_field_evidence(db, project_id, query, target_field_id=None, scenario_id=None):
    target = project_entity(db, TargetField, target_field_id, project_id)
    scenario = project_entity(db, ProductScenario, scenario_id, project_id)
    sections = {"target_field": _fields(target, "id project_id field_code field_name field_definition") if target else None,
                "source_paths": [], "join_conditions": [], "transformations": [], "code_mappings": [], "gaps": []}
    if scenario:
        sections["scenario"] = _fields(scenario, "id project_id scenario_code scenario_name description")
    evidence = []

    def add(kind, source_type, entity_id, label, data, href, **ids):
        citation = {"citation_id": f"{source_type}-{entity_id}", "citation_type": kind,
                    "source_type": source_type, "project_id": project_id, "label": label,
                    "quoted_content": _evidence_text(data),
                    "href": href, "locator": {}, **ids}
        if not any(e["citation_id"] == citation["citation_id"] for e in evidence):
            evidence.append(citation)
        return citation["citation_id"]

    # Context has real IDs but is not falsely typed as a mapping citation.
    context = {"target_field": sections["target_field"], "scenario": sections.get("scenario")}
    terms = list(dict.fromkeys(re.findall(r"[\w]+", query.lower())[:12] +
                              ([target.field_code.lower(), target.field_name.lower()] if target else [])))
    technical = []
    mappings = []
    if target or scenario:
        statement = select(ScenarioTechnicalLineage).where(ScenarioTechnicalLineage.project_id == project_id)
        if target:
            statement = statement.where(ScenarioTechnicalLineage.target_field_id == target.id)
        if scenario:
            statement = statement.where(ScenarioTechnicalLineage.scenario_id == scenario.id)
        technical = list(db.scalars(statement.order_by(ScenarioTechnicalLineage.id).limit(6)))
    if target:
        mappings = list(db.scalars(select(MartToYbtMapping).where(
            MartToYbtMapping.project_id == project_id, MartToYbtMapping.target_field_id == target.id,
        ).order_by(MartToYbtMapping.id).limit(6)))
    mart_ids = [m.mart_field_id for m in mappings if m.mart_field_id]
    valid_mart_ids = list(db.scalars(select(MartField.id).where(MartField.project_id == project_id, MartField.id.in_(mart_ids))))
    source_mappings = list(db.scalars(select(SourceToMartMapping).where(
        SourceToMartMapping.project_id == project_id, SourceToMartMapping.mart_field_id.in_(valid_mart_ids),
    ).order_by(SourceToMartMapping.id).limit(6))) if valid_mart_ids else []
    mapping_groups = [("scenario_technical", technical), ("mart_to_ybt", mappings), ("source_to_mart", source_mappings)]
    references = []
    for mapping_type, rows in mapping_groups:
        if rows:
            references.extend(db.scalars(select(MappingEvidenceReference).where(
                MappingEvidenceReference.project_id == project_id,
                MappingEvidenceReference.mapping_type == mapping_type,
                MappingEvidenceReference.mapping_id.in_([r.id for r in rows]),
            ).order_by(MappingEvidenceReference.id).limit(20)))
    bound_catalog = [r.evidence_id for r in references if r.evidence_type == "catalog_column"]
    bound_source = [r.evidence_id for r in references if r.evidence_type == "source_field"]
    exact_catalog = list(db.scalars(select(CatalogColumn.id).where(
        CatalogColumn.project_id == project_id, CatalogColumn.enabled.is_(True),
        or_(CatalogColumn.id.in_(bound_catalog), func.lower(CatalogColumn.column_name).in_(terms)),
    ).order_by(CatalogColumn.id.in_(bound_catalog).desc(), CatalogColumn.id).limit(8)))
    ranked = search_catalog(db, project_id, CatalogSearchRequest(
        query=query or (target.field_code if target else ""), target_field_id=target_field_id, top_k=8,
    )) if terms else []
    catalog_ids = list(dict.fromkeys(exact_catalog + [r["catalog_column_id"] for r in ranked]))[:8]
    for column_id in catalog_ids:
        column = project_entity(db, CatalogColumn, column_id, project_id)
        table = db.scalar(select(CatalogTable).where(CatalogTable.id == column.catalog_table_id, CatalogTable.project_id == project_id, CatalogTable.enabled.is_(True)))
        datasource = db.scalar(select(DataSource).where(DataSource.id == column.datasource_id, DataSource.project_id == project_id))
        if not table or not datasource or table.datasource_id != datasource.id:
            continue
        path = {"source_system": None, "datasource_name": datasource.name,
                "database": column.database_name or datasource.database_name, "schema": column.schema_name,
                "table": table.table_name, "field": column.column_name, "status": "candidate",
                "catalog_column_id": column.id, "catalog_table_id": table.id, "datasource_id": datasource.id}
        cid = add("catalog_column", "catalog_column", column.id, f"{table.table_name}.{column.column_name}",
                  {**path, "comment": column.column_comment}, f"/catalog?project_id={project_id}&column_id={column.id}",
                  catalog_column_id=column.id, catalog_table_id=table.id, datasource_id=datasource.id)
        sections["source_paths"].append({**path, "citation_ids": [cid]})
    source_ids = []
    if terms or bound_source:
        statement = select(SourceField, SourceTable, BusinessSystem).join(SourceTable, SourceTable.id == SourceField.source_table_id).join(BusinessSystem, BusinessSystem.id == SourceTable.business_system_id).where(
            SourceField.project_id == project_id, SourceTable.project_id == project_id,
            BusinessSystem.project_id == project_id, BusinessSystem.enabled.is_(True),
            or_(SourceField.id.in_(bound_source), func.lower(SourceField.field_code).in_(terms),
                func.lower(SourceField.physical_column_name).in_(terms),
                *[SourceField.field_name.ilike(like_pattern(term), escape="\\") for term in terms[:8]]),
        ).order_by(SourceField.id.in_(bound_source).desc(), func.lower(SourceField.field_code).in_(terms).desc(), SourceField.id).limit(8)
        for field, table, system in db.execute(statement):
            datasource = db.scalar(select(DataSource).where(DataSource.id == table.datasource_id, DataSource.project_id == project_id)) if table.datasource_id else None
            if table.datasource_id and not datasource:
                continue
            source_ids.append(field.id)
            path = {"source_system": system.system_name, "database": table.database_name or (datasource.database_name if datasource else None),
                    "schema": table.schema_name, "table": table.physical_table_name or table.table_code,
                    "field": field.physical_column_name or field.field_code, "status": "candidate",
                    "source_field_id": field.id, "source_table_id": table.id, "business_system_id": system.id}
            # The public four-type union uses mapping with a precise source_type;
            # source_field_id, not a fabricated mapping_id, identifies this evidence.
            cid = add("mapping", "source_field", field.id, f"{path['table']}.{path['field']}", path,
                      f"/business-systems?project_id={project_id}&source_field_id={field.id}",
                      source_field_id=field.id, source_table_id=table.id, business_system_id=system.id)
            sections["source_paths"].append({**path, "citation_ids": [cid]})

    def rules(data, cid, status):
        for section, names in (("join_conditions", ("join_condition",)),
                               ("transformations", ("processing_logic", "business_rule", "filter_condition", "transformation_expression", "aggregation_rule")),
                               ("code_mappings", ("code_mapping_rule",))):
            for name in names:
                if data.get(name):
                    sections[section].append({"rule_type": name, "text": data[name], "status": status, "citation_ids": [cid]})

    for mapping_type, rows in mapping_groups:
        for row in rows:
            if mapping_type == "scenario_technical":
                if not db.scalar(select(TargetField.id).where(TargetField.id == row.target_field_id, TargetField.project_id == project_id)) or not db.scalar(select(ProductScenario.id).where(ProductScenario.id == row.scenario_id, ProductScenario.project_id == project_id)):
                    continue
                data = _fields(row, "target_field_id scenario_id source_system_name source_database_name source_schema_name source_table_english_name source_field_english_name processing_logic tech_confirm_status")
                status = row.tech_confirm_status
            else:
                data = _fields(row, "mart_field_id mapping_status business_rule join_condition filter_condition code_mapping_rule")
                data.update(_fields(row, "source_system_summary source_tables_summary source_fields_summary" if mapping_type == "source_to_mart" else "target_field_id mart_table_summary mart_field_summary"))
                if row.mart_field_id and row.mart_field_id not in valid_mart_ids:
                    continue
                status = row.mapping_status
            cid = add("mapping", mapping_type, row.id, f"{mapping_type} {row.id}", data,
                      f"/fields?project_id={project_id}&target_field_id={target_field_id or ''}", mapping_id=row.id, mapping_type=mapping_type)
            rules(data, cid, status)
            if mapping_type == "scenario_technical" and row.source_table_english_name and row.source_field_english_name:
                sections["source_paths"].append({"source_system": row.source_system_name, "database": row.source_database_name,
                    "schema": row.source_schema_name, "table": row.source_table_english_name, "field": row.source_field_english_name,
                    "status": status, "citation_ids": [cid]})
    node_ids = list(db.scalars(select(LineageNode.id).where(
        LineageNode.project_id == project_id,
        or_(LineageNode.catalog_column_id.in_(catalog_ids), LineageNode.source_field_id.in_(source_ids),
            LineageNode.mart_field_id.in_(valid_mart_ids), LineageNode.target_field_id == target.id if target else False),
    ).order_by(LineageNode.id).limit(30)))
    edge_ids = [r.evidence_id for r in references if r.evidence_type == "lineage_edge"]
    edges = db.scalars(select(LineageEdge).where(
        LineageEdge.project_id == project_id, LineageEdge.enabled.is_(True),
        or_(LineageEdge.id.in_(edge_ids), LineageEdge.source_node_id.in_(node_ids), LineageEdge.target_node_id.in_(node_ids)),
    ).order_by(LineageEdge.id.in_(edge_ids).desc(), LineageEdge.id).limit(10))
    for edge in edges:
        nodes = [db.scalar(select(LineageNode).where(LineageNode.id == node_id, LineageNode.project_id == project_id)) for node_id in (edge.source_node_id, edge.target_node_id)]
        if not all(nodes):
            continue
        data = _fields(edge, "source_node_id target_node_id script_file_version_id statement_id edge_type transformation_expression join_condition filter_condition aggregation_rule code_mapping_rule source_line_start source_line_end")
        data["nodes"] = [_fields(n, "id database_name schema_name table_name column_name unresolved_flag") for n in nodes]
        cid = add("lineage_edge", "lineage_edge", edge.id, f"血缘边 {edge.id}", data,
                  f"/lineage?project_id={project_id}&edge_id={edge.id}", lineage_edge_id=edge.id,
                  script_file_version_id=edge.script_file_version_id)
        rules(data, cid, "unresolved" if any(n.unresolved_flag for n in nodes) else "persisted")
    for section, message in (("source_paths", "缺少真实来源字段证据。"), ("join_conditions", "关联条件未确认。"),
                             ("transformations", "加工转换未确认。"), ("code_mappings", "码值规则未确认。")):
        if not sections[section]:
            sections["gaps"].append(message)
    if any(p["status"] == "candidate" for p in sections["source_paths"]):
        sections["gaps"].append("目录和名称匹配仅为候选，不证明目标字段的真实取值关系。")
    if any(not all(p.get(key) for key in ("source_system", "database", "schema", "table", "field")) for p in sections["source_paths"]):
        sections["gaps"].append("部分来源的系统、数据库或Schema信息缺失，不能据名称补全。")
    if any(p.get("status") in {"draft", "unresolved", "pending_confirmation"} for key in ("source_paths", "join_conditions", "transformations", "code_mappings") for p in sections[key]):
        sections["gaps"].append("存在草稿或未解析关系，需技术人员确认。")
    return context, sections, evidence


async def data_field_answer(db, project_id, query, **filters):
    context, sections, evidence = collect_field_evidence(db, project_id, query, filters.get("target_field_id"), filters.get("scenario_id"))
    log_id = None
    retrieval_failed = False
    items = []
    try:
        log, items = HybridRetriever(db).search(project_id, query, filters.get("target_field_id"), filters.get("scenario_id"),
            mode_knowledge_types("data_field", filters.get("knowledge_types")), min(filters.get("top_k", 8), 8), retrieval_mode=filters.get("retrieval_mode", "hybrid"),
            include_history=filters.get("include_history", False), historical_as_of=filters.get("historical_as_of"))
        log_id = log.id
    except Exception:
        retrieval_failed = True
        sections["gaps"].append("知识检索暂不可用，仅返回已收集的结构化证据。")
    citations = [document_citation(item, project_id) for item in items]
    project = db.get(Project, project_id)
    validate_citations(db, citations, project_id=project_id, institution_name=project.bank_name if project else None)
    evidence.extend(citations)
    result = {"answer": "现有证据不足，结论待确认。", "confidence_level": "low", "citations": evidence,
              "supported_claims": [], "unsupported_claims": [], "open_questions": sections["gaps"],
              "retrieval_log_id": log_id, "answer_status": "needs_confirmation", "answer_mode": "data_field", "sections": sections,
              "execution_metadata": deterministic_execution_metadata(
                  "data_field_answer",
                  context_hash=stable_hash({"query": query, "filters": filters}),
              )}
    if not evidence:
        return result
    runtime = evidence_runtime(get_prompt_runtime(db, "regulatory_field_explanation"))
    try:
        runtime.system_prompt += "\n返回claims数组，每条仅含citation_id和从该证据quoted_content逐字摘录的text；候选不是已确认关系。无可靠摘录返回空数组。"
        prompt = json.dumps({"question": query, "context": context, "evidence": evidence}, ensure_ascii=False)
        levels = [item["confidentiality_level"] for item in items] + ["internal"]
        model_input = prepare_model_input(runtime, prompt, levels, db=db, project_id=project_id)
        output, execution_metadata = await execute_runtime_chat_with_metadata(db, project_id, runtime, model_input, DataFieldOutput,
            confidentiality=max(levels, key=lambda level: {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}.get(level, 1)),
            retrieval_log_id=log_id, interactive=True)
    except Exception as exc:
        execution_metadata = getattr(exc, "execution_metadata", None) or build_execution_metadata(
            runtime,
            execution_kind="degraded",
            degraded_reason=getattr(exc, "error_type", type(exc).__name__),
        )
        result.update(answer="模型生成暂时不可用，已返回结构化证据，结论待确认。", answer_status="degraded")
        sections["gaps"].append("模型生成失败或数据分类策略禁止外发，请人工核验证据。")
        result["execution_metadata"] = execution_metadata
        return result
    by_id = {e["citation_id"]: e for e in evidence}
    claims = []
    rejected = False
    for claim in output.get("claims", []):
        citation = by_id.get(claim.get("citation_id"))
        text = str(claim.get("text") or "").strip()
        if not citation or not text or text not in citation["quoted_content"] or _invented_qualified_identifiers(text, citation["quoted_content"]):
            rejected = True
            continue
        claims.append(f"[{citation['citation_id']}] {text}")
    if rejected:
        result["unsupported_claims"] = ["模型输出包含未受输入证据支持的引用或结论，已隐藏。"]
        sections["gaps"].append("部分模型结论未通过证据包含校验。")
    if claims:
        result["answer"] = "证据摘录（候选及草稿不代表已确认取值关系）：\n" + "\n".join(claims)
        result["supported_claims"] = claims
    result["answer_status"] = "degraded" if retrieval_failed else "needs_confirmation" if rejected or sections["gaps"] or not claims else "grounded"
    result["execution_metadata"] = execution_metadata
    return result
