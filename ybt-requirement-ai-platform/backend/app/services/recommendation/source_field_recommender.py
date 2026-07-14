from difflib import SequenceMatcher
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AIUserFeedback,
    BusinessSystem,
    CandidateSourceRecommendation,
    ColumnProfileSnapshot,
    DataSource,
    MappingEvidenceReference,
    MartToYbtMapping,
    ProductScenario,
    RegulatoryKnowledgeItem,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    SourceField,
    SourceTable,
    SqlParseResult,
    TargetField,
)
from app.schemas import CatalogSearchRequest
from app.services.metadata.catalog_service import search_catalog
from app.services.retrieval import HybridRetriever


def recommend_source_fields(db: Session, target_field_id: int, scenario_id: int, top_k: int = 20) -> list[CandidateSourceRecommendation]:
    target = db.get(TargetField, target_field_id)
    scenario = db.get(ProductScenario, scenario_id)
    if target is None:
        raise ValueError("Target field not found")
    if scenario is None:
        raise ValueError("Scenario not found")
    if target.project_id != scenario.project_id:
        raise ValueError("Scenario belongs to another project")

    candidates = db.execute(
        select(SourceField, SourceTable, BusinessSystem, DataSource)
        .join(SourceTable, SourceTable.id == SourceField.source_table_id)
        .join(BusinessSystem, BusinessSystem.id == SourceTable.business_system_id)
        .outerjoin(DataSource, DataSource.id == SourceTable.datasource_id)
        .where(SourceField.project_id == target.project_id, BusinessSystem.enabled.is_(True))
    ).all()
    knowledge = list(db.scalars(select(RegulatoryKnowledgeItem).where(
        RegulatoryKnowledgeItem.project_id == target.project_id,
        (RegulatoryKnowledgeItem.target_field_code == target.field_code) |
        (RegulatoryKnowledgeItem.target_field_name == target.field_name),
    )).all())
    history = list(db.scalars(select(ScenarioTechnicalLineage).where(
        ScenarioTechnicalLineage.project_id == target.project_id,
        ScenarioTechnicalLineage.target_field_id == target.id,
    )).all())
    sql_context = _sql_context(db, target.project_id)
    rag_log,rag_items=HybridRetriever(db).search(target.project_id," ".join(filter(None,[target.field_code,target.field_name,target.field_definition,scenario.scenario_name])),target.id,scenario.id,None,30)
    rag_unit_ids=[item["knowledge_unit_id"] for item in rag_items];rag_citations=[{"knowledge_unit_id":item["knowledge_unit_id"],"source_file_name":item["source_file_name"],"source_sheet_name":item["source_sheet_name"],"source_cell_range":item["source_cell_range"]} for item in rag_items]
    evidence_rows = db.scalars(select(MappingEvidenceReference).where(
        MappingEvidenceReference.project_id == target.project_id,
        MappingEvidenceReference.evidence_type.in_(["source_field", "catalog_column"]),
    )).all()
    relevant_mapping_ids = {
        "scenario_business": set(db.scalars(select(ScenarioBusinessMapping.id).where(
            ScenarioBusinessMapping.target_field_id == target.id,
            ScenarioBusinessMapping.scenario_id == scenario.id,
        )).all()),
        "scenario_technical": set(db.scalars(select(ScenarioTechnicalLineage.id).where(
            ScenarioTechnicalLineage.target_field_id == target.id,
            ScenarioTechnicalLineage.scenario_id == scenario.id,
        )).all()),
        "mart_to_ybt": set(db.scalars(select(MartToYbtMapping.id).where(
            MartToYbtMapping.target_field_id == target.id,
        )).all()),
    }
    bound_source_ids = {
        item.evidence_id for item in evidence_rows
        if item.evidence_type == "source_field" and item.evidence_id is not None and item.mapping_id in relevant_mapping_ids.get(item.mapping_type, set())
    }
    bound_catalog_ids = {
        item.evidence_id for item in evidence_rows
        if item.evidence_type == "catalog_column" and item.evidence_id is not None and item.mapping_id in relevant_mapping_ids.get(item.mapping_type, set())
    }

    scored = []
    for source, table, system, datasource in candidates:
        score, reasons, evidence = _score_candidate(
            target, scenario, source, table, system, knowledge, history, sql_context, source.id in bound_source_ids
        )
        if score <= 0:
            continue
        scored.append((score, source, table, system, datasource, reasons, evidence))
    scored.sort(key=lambda item: (item[0], -item[1].id), reverse=True)

    previous = db.scalars(select(CandidateSourceRecommendation).where(
        CandidateSourceRecommendation.target_field_id == target.id,
        CandidateSourceRecommendation.scenario_id == scenario.id,
        CandidateSourceRecommendation.selected_flag.is_(False),
    )).all()
    for item in previous:
        db.delete(item)
    db.flush()

    recommendations = []
    for score, source, table, system, datasource, reasons, evidence in scored[: max(top_k // 2, 1)]:
        recommendation = CandidateSourceRecommendation(
            project_id=target.project_id, target_field_id=target.id, scenario_id=scenario.id,
            recommended_source_system=system.system_name,
            recommended_database_name=datasource.database_name if datasource else None,
            recommended_schema_name=table.schema_name,
            recommended_table_name=table.physical_table_name or table.table_code,
            recommended_table_comment=table.table_comment or table.table_name,
            recommended_field_name=source.physical_column_name or source.field_code,
            recommended_field_comment=source.field_comment or source.field_name,
            recommended_processing_logic="源字段直接取值" if "字段代码精确匹配" in reasons else "根据历史口径和字段语义取值，具体处理逻辑待确认",
            recommend_reason="；".join(reasons), evidence_summary="；".join(evidence),
            confidence_level="high" if score >= 0.75 else "medium" if score >= 0.45 else "low",
            score=round(min(score, 1.0), 4), selected_flag=False,
            retrieval_log_id=rag_log.id,knowledge_unit_ids_json=rag_unit_ids,citation_summary_json=rag_citations,recommendation_basis="historical_explicit" if "历史" in "".join(reasons) else "semantic_candidate",
        )
        db.add(recommendation)
        recommendations.append(recommendation)
    catalog_items = search_catalog(db, target.project_id, CatalogSearchRequest(
        query=" ".join(filter(None, [target.field_code, target.field_name, target.field_definition, target.regulatory_description])),
        target_field_id=target.id, scenario_id=scenario.id, top_k=min(max(top_k * 5, 50), 100),
    ))
    for item in catalog_items:
        score,reasons,evidence=_score_catalog_candidate(item,scenario,knowledge,history,sql_context,item["catalog_column_id"] in bound_catalog_ids)
        matching_rag=[entry for entry in rag_items if any(value and value.lower() in entry["content"].lower() for value in [item["table_name"],item["column_name"]])]
        if matching_rag:score=min(1,score+.12);reasons.append("混合知识检索命中");evidence.append(f"{len(matching_rag)} 条知识单元引用该表字段")
        profile=db.scalar(select(ColumnProfileSnapshot).where(ColumnProfileSnapshot.catalog_column_id==item["catalog_column_id"]).order_by(ColumnProfileSnapshot.id.desc()))
        if profile and profile.total_count is not None:score=min(1,score+.05);reasons.append("数据探查支持");evidence.append(f"探查 total={profile.total_count}, null_rate={profile.null_rate}, distinct={profile.distinct_count}")
        positive=db.scalar(select(AIUserFeedback.id).where(AIUserFeedback.project_id==target.project_id,AIUserFeedback.feedback_type=="source_recommendation",AIUserFeedback.rating=="correct",AIUserFeedback.correct_table_name==item["table_name"],AIUserFeedback.correct_field_name==item["column_name"]))
        if positive:score=min(1,score+.08);reasons.append("历史正向反馈")
        item["score"]=score;item["match_reasons"]=reasons;item["catalog_evidence"]=evidence
    catalog_items.sort(key=lambda item:(item["score"],-item["catalog_column_id"]),reverse=True)
    existing_catalog_ids = {item.catalog_column_id for item in recommendations if item.catalog_column_id}
    for item in catalog_items:
        if item["catalog_column_id"] in existing_catalog_ids or len(recommendations) >= top_k:
            continue
        datasource = db.get(DataSource, item["datasource_id"])
        recommendation = CandidateSourceRecommendation(
            project_id=target.project_id, target_field_id=target.id, scenario_id=scenario.id,
            catalog_column_id=item["catalog_column_id"], datasource_id=item["datasource_id"],
            recommended_source_system=datasource.display_name or datasource.name,
            recommended_database_name=datasource.database_name,
            recommended_schema_name=item["schema_name"], recommended_table_name=item["table_name"],
            recommended_table_comment=item["table_comment"], recommended_field_name=item["column_name"],
            recommended_field_comment=item["column_comment"], data_type=item["data_type"], nullable=item["nullable"],
            profile_status="not_profiled", recommended_processing_logic="目录候选字段直接取值，处理逻辑待探查后确认",
            recommend_reason="；".join(item["match_reasons"] + ["真实数据目录候选"]),
            evidence_summary="；".join([f"来自命名数据源 {datasource.name} 的目录字段 {item['schema_name']}.{item['table_name']}.{item['column_name']}"]+item["catalog_evidence"]),
            confidence_level="high" if item["score"] >= .75 else "medium" if item["score"] >= .45 else "low",
            score=item["score"], selected_flag=False,
            retrieval_log_id=rag_log.id,knowledge_unit_ids_json=[entry["knowledge_unit_id"] for entry in matching_rag] if (matching_rag:=[entry for entry in rag_items if any(value and value.lower() in entry["content"].lower() for value in [item["table_name"],item["column_name"]])]) else rag_unit_ids[:5],citation_summary_json=[citation for citation in rag_citations if citation["knowledge_unit_id"] in ([entry["knowledge_unit_id"] for entry in matching_rag] if matching_rag else rag_unit_ids[:5])],recommendation_basis="profile_supported" if "数据探查支持" in item["match_reasons"] else "regulatory_advice" if "监管答疑匹配" in item["match_reasons"] else "semantic_candidate",
        )
        db.add(recommendation); recommendations.append(recommendation)
    recommendations.sort(key=lambda item: item.score or 0, reverse=True)
    db.commit()
    for recommendation in recommendations:
        db.refresh(recommendation)
    return recommendations


def select_recommendation(db: Session, recommendation_id: int) -> tuple[CandidateSourceRecommendation, ScenarioTechnicalLineage]:
    recommendation = db.get(CandidateSourceRecommendation, recommendation_id)
    if recommendation is None:
        raise ValueError("Source recommendation not found")
    lineage = db.scalar(select(ScenarioTechnicalLineage).where(
        ScenarioTechnicalLineage.target_field_id == recommendation.target_field_id,
        ScenarioTechnicalLineage.scenario_id == recommendation.scenario_id,
    ))
    if lineage is None:
        lineage = ScenarioTechnicalLineage(
            project_id=recommendation.project_id, target_field_id=recommendation.target_field_id,
            scenario_id=recommendation.scenario_id,
        )
        db.add(lineage)
        db.flush()
    if recommendation.catalog_column_id is None:
        _apply_recommendation(lineage, recommendation)
    for item in db.scalars(select(CandidateSourceRecommendation).where(
        CandidateSourceRecommendation.target_field_id == recommendation.target_field_id,
        CandidateSourceRecommendation.scenario_id == recommendation.scenario_id,
    )).all():
        item.selected_flag = item.id == recommendation.id
    if recommendation.catalog_column_id is not None:
        exists = db.scalar(select(MappingEvidenceReference.id).where(
            MappingEvidenceReference.mapping_type == "scenario_technical",
            MappingEvidenceReference.mapping_id == lineage.id,
            MappingEvidenceReference.evidence_type == "catalog_column",
            MappingEvidenceReference.evidence_id == recommendation.catalog_column_id,
        ))
        if exists is None:
            db.add(MappingEvidenceReference(
                project_id=recommendation.project_id, mapping_type="scenario_technical", mapping_id=lineage.id,
                evidence_type="catalog_column", evidence_id=recommendation.catalog_column_id,
                source_name=f"{recommendation.recommended_source_system}.{recommendation.recommended_schema_name}.{recommendation.recommended_table_name}.{recommendation.recommended_field_name}",
                location_text="metadata catalog", evidence_summary=recommendation.evidence_summary,
            ))
    db.commit()
    db.refresh(recommendation)
    db.refresh(lineage)
    return recommendation, lineage


def adopt_recommendation(db: Session, recommendation_id: int) -> tuple[CandidateSourceRecommendation, ScenarioTechnicalLineage]:
    recommendation = db.get(CandidateSourceRecommendation, recommendation_id)
    if recommendation is None:
        raise ValueError("Source recommendation not found")
    if not recommendation.selected_flag:
        raise ValueError("Source recommendation must be selected before adoption")
    lineage = db.scalar(select(ScenarioTechnicalLineage).where(
        ScenarioTechnicalLineage.target_field_id == recommendation.target_field_id,
        ScenarioTechnicalLineage.scenario_id == recommendation.scenario_id,
    ))
    if lineage is None:
        lineage = ScenarioTechnicalLineage(project_id=recommendation.project_id, target_field_id=recommendation.target_field_id, scenario_id=recommendation.scenario_id)
        db.add(lineage)
    _apply_recommendation(lineage, recommendation)
    db.commit(); db.refresh(recommendation); db.refresh(lineage); return recommendation, lineage


def _apply_recommendation(lineage, recommendation):
    lineage.source_system_name = recommendation.recommended_source_system
    lineage.source_database_name = recommendation.recommended_database_name
    lineage.source_schema_name = recommendation.recommended_schema_name
    lineage.source_table_english_name = recommendation.recommended_table_name
    lineage.source_table_chinese_name = recommendation.recommended_table_comment
    lineage.source_field_english_name = recommendation.recommended_field_name
    lineage.source_field_chinese_name = recommendation.recommended_field_comment
    lineage.processing_logic = recommendation.recommended_processing_logic
    lineage.processing_logic_type = "direct" if recommendation.recommended_processing_logic == "源字段直接取值" else "pending_confirmation"
    lineage.tech_confirm_status = "draft"


def _score_candidate(target, scenario, source, table, system, knowledge, history, sql_context: str,
                     manually_bound: bool) -> tuple[float, list[str], list[str]]:
    score, reasons, evidence = 0.0, [], []
    if _norm(source.field_code) == _norm(target.field_code):
        score += 0.45
        reasons.append("字段代码精确匹配")
        evidence.append(f"目标字段与源字段代码均为 {target.field_code}")
    name_similarity = _similarity(source.field_name, target.field_name)
    if name_similarity >= 0.6:
        score += 0.2 * name_similarity
        reasons.append("字段名称匹配")
        evidence.append(f"源字段名称“{source.field_name}”与目标字段“{target.field_name}”相近")
    target_text = " ".join(filter(None, [
        target.field_definition,
        target.regulatory_description,
        target.regulatory_original_definition,
        target.regulatory_refined_definition,
        target.east_definition,
        target.internal_definition,
    ]))
    comment_similarity = _similarity(source.field_comment or source.description or "", target_text)
    if comment_similarity >= 0.25:
        score += 0.15 * comment_similarity
        reasons.append("字段注释匹配")
        evidence.append(f"源字段注释与目标口径语义相似度 {comment_similarity:.2f}")
    history_text = " ".join(
        " ".join(filter(None, [item.source_system_name, item.source_table_english_name, item.source_field_english_name]))
        for item in history
    ).lower()
    if any(value and value.lower() in history_text for value in [system.system_name, table.table_code, source.field_code]):
        score += 0.1
        reasons.append("历史场景来源匹配")
        evidence.append(f"{scenario.scenario_name}历史技术溯源包含该系统、表或字段")
    source_tokens = [system.system_name, table.table_code, source.field_code]
    matching_knowledge = [item for item in knowledge if _mentions_source(item, source_tokens)]
    if any(item.knowledge_type == "historical_mapping" for item in matching_knowledge):
        score += 0.08
        reasons.append("历史表字段匹配")
        evidence.append("历史技术溯源知识中出现该来源表或字段")
    if any(item.scenario_id == scenario.id for item in matching_knowledge):
        score += 0.07
        reasons.append("场景匹配")
        evidence.append(f"{scenario.scenario_name}场景的结构化知识命中该来源候选")
    if any(item.knowledge_type == "regulatory_qa" for item in matching_knowledge):
        score += 0.05
        reasons.append("监管答疑匹配")
        evidence.append("监管答疑知识中出现该来源候选")
    if any(item.knowledge_type == "east_mapping" for item in matching_knowledge):
        score += 0.05
        reasons.append("EAST 映射匹配")
        evidence.append("EAST 同源映射知识中出现该来源候选")
    if any(value and value.lower() in sql_context for value in [table.table_code, source.field_code]):
        score += 0.05
        reasons.append("SQL 解析证据匹配")
        evidence.append("项目 SQL 解析证据中出现该表或字段")
    if manually_bound:
        score += 0.1
        reasons.append("已绑定人工证据")
        evidence.append("该源字段已作为人工证据绑定")
    if not reasons:
        reasons.append("弱语义候选")
        evidence.append("仅存在低强度字段语义相似，需人工复核")
    return score, reasons, evidence


def _score_catalog_candidate(item, scenario, knowledge, history, sql_context: str, manually_bound: bool):
    score=float(item["score"]);reasons=list(item["match_reasons"]);evidence=[]
    tokens=[item["datasource_name"],item["schema_name"],item["table_name"],item["column_name"]]
    matching_history=[lineage for lineage in history if any(value and value.lower() in " ".join(filter(None,[lineage.source_database_name,lineage.source_schema_name,lineage.source_table_english_name,lineage.source_field_english_name])).lower() for value in tokens[1:])]
    if matching_history:
        score+=.12;reasons.append("历史技术溯源匹配");evidence.append("历史场景技术溯源中出现该目录表或字段")
    if any(lineage.scenario_id==scenario.id for lineage in matching_history):
        score+=.05;reasons.append("当前场景历史匹配");evidence.append(f"{scenario.scenario_name}场景已使用该目录来源")
    matching_knowledge=[knowledge_item for knowledge_item in knowledge if _mentions_source(knowledge_item,tokens)]
    if any(knowledge_item.knowledge_type=="historical_mapping" for knowledge_item in matching_knowledge):
        score+=.08;reasons.append("历史口径匹配");evidence.append("历史口径知识中出现该目录来源")
    if any(knowledge_item.knowledge_type=="regulatory_qa" for knowledge_item in matching_knowledge):
        score+=.05;reasons.append("监管答疑匹配");evidence.append("监管答疑知识中出现该目录来源")
    if any(knowledge_item.scenario_id==scenario.id for knowledge_item in matching_knowledge):
        score+=.05;reasons.append("当前场景知识匹配");evidence.append(f"{scenario.scenario_name}场景知识命中该目录来源")
    if any(value and value.lower() in sql_context for value in [item["table_name"],item["column_name"]]):
        score+=.05;reasons.append("SQL 解析证据匹配");evidence.append("项目 SQL 解析结果中出现该目录表或字段")
    if item.get("imported_source_field_id"):
        score+=.08;reasons.append("已导入来源字段");evidence.append("该目录字段已导入 SourceField")
    if manually_bound:
        score+=.1;reasons.append("已绑定人工证据");evidence.append("该目录字段已绑定到当前字段口径证据")
    return round(min(score,1.0),4),list(dict.fromkeys(reasons)),evidence


def _sql_context(db: Session, project_id: int) -> str:
    rows = db.scalars(select(SqlParseResult).where(SqlParseResult.project_id == project_id)).all()
    return " ".join(str(value) for row in rows for value in [row.source_tables_json, row.selected_fields_json]).lower()


def _mentions_source(item: RegulatoryKnowledgeItem, tokens: list[str | None]) -> bool:
    text = " ".join(filter(None, [
        item.question_text,
        item.answer_text,
        item.institution_suggestion,
        item.regulatory_reply,
        item.business_explanation,
    ])).lower()
    return any(token and token.lower() in text for token in tokens)


def _norm(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    left_norm, right_norm = _norm(left), _norm(right)
    if left_norm and right_norm:
        return SequenceMatcher(None, left_norm, right_norm).ratio()
    left_chars, right_chars = set(left), set(right)
    return len(left_chars & right_chars) / max(len(left_chars | right_chars), 1)
