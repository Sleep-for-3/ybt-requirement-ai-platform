from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CatalogColumn, MappingEvidenceReference, ProductScenario, ScenarioBusinessMapping, ScenarioTechnicalLineage, TargetField
from app.services.governance.audit import record_audit
from app.services.llm.prompt_runtime import get_prompt_runtime,get_runtime_llm_service,prepare_model_input,record_model_call
from app.services.retrieval import HybridRetriever


async def generate_business_draft(db: Session, mapping_id: int) -> ScenarioBusinessMapping:
    mapping = db.get(ScenarioBusinessMapping, mapping_id)
    if mapping is None:
        raise ValueError("Scenario business mapping not found")
    field = db.get(TargetField, mapping.target_field_id)
    scenario = db.get(ProductScenario, mapping.scenario_id)
    other = list(db.scalars(select(ScenarioBusinessMapping).where(ScenarioBusinessMapping.target_field_id == mapping.target_field_id, ScenarioBusinessMapping.id != mapping.id)).all())
    runtime=get_prompt_runtime(db,"scenario_business_mapping");retrieval_log,knowledge=HybridRetriever(db).search(mapping.project_id,field.field_name if field else "",mapping.target_field_id,mapping.scenario_id,None,10);context=_context(field,scenario,mapping,"\n".join(f"[{item['knowledge_unit_id']}] {item['content']}" for item in knowledge), other);model_input=prepare_model_input(runtime,context,[item["confidentiality_level"] for item in knowledge]);output = await get_runtime_llm_service(runtime).chat_json(runtime.system_prompt, model_input);record_model_call(db,mapping.project_id,runtime,model_input,output,retrieval_log_id=retrieval_log.id)
    for key in [
        "business_definition", "source_system_screenshot_required", "source_system_change_required",
        "external_data_required", "manual_supplement_required", "business_owner", "remarks",
    ]:
        if output.get(key) is not None:
            setattr(mapping, key, output[key])
    mapping.open_questions = _text(output.get("open_questions")) or mapping.open_questions
    mapping.confidence_level = output.get("confidence_level") or mapping.confidence_level
    mapping.ai_generated_content = output.get("final_content_draft") or _business_content(mapping, scenario)
    record_audit(db, action="generate_business_draft", resource_type="scenario_business_mapping", resource_id=mapping.id, project_id=mapping.project_id, after={"confidence_level": mapping.confidence_level, "claim_type": output.get("claim_type", "evidence_supported" if knowledge else "inferred"), "citation_count": len(output.get("citations") or knowledge)})
    db.commit()
    db.refresh(mapping)
    return mapping


async def generate_technical_draft(db: Session, lineage_id: int) -> ScenarioTechnicalLineage:
    lineage = db.get(ScenarioTechnicalLineage, lineage_id)
    if lineage is None:
        raise ValueError("Scenario technical lineage not found")
    field = db.get(TargetField, lineage.target_field_id)
    scenario = db.get(ProductScenario, lineage.scenario_id)
    evidence = list(db.scalars(select(MappingEvidenceReference).where(
        MappingEvidenceReference.mapping_type == "scenario_technical",
        MappingEvidenceReference.mapping_id == lineage.id,
    ).order_by(MappingEvidenceReference.id)).all())
    evidence_text = "\n".join(item.evidence_summary or item.quoted_content or item.source_name for item in evidence)
    runtime=get_prompt_runtime(db,"scenario_technical_lineage");retrieval_log,knowledge=HybridRetriever(db).search(lineage.project_id,field.field_name if field else "",lineage.target_field_id,lineage.scenario_id,None,10);knowledge_text="\n".join(f"[{item['knowledge_unit_id']}] {item['content']}" for item in knowledge);context=_context(field,scenario,lineage,"\n".join(filter(None,[evidence_text,knowledge_text])));model_input=prepare_model_input(runtime,context,[item["confidentiality_level"] for item in knowledge]);output = await get_runtime_llm_service(runtime).chat_json(runtime.system_prompt, model_input);record_model_call(db,lineage.project_id,runtime,model_input,output,retrieval_log_id=retrieval_log.id)
    physical_keys = {"source_database_name", "source_schema_name", "source_table_english_name", "source_field_english_name"}
    for key in ["source_system_name", "source_database_name", "source_schema_name", "source_table_english_name", "source_table_chinese_name", "source_field_english_name", "source_field_chinese_name", "processing_logic", "processing_logic_type", "tech_owner", "remarks"]:
        if output.get(key) is not None:
            if key in physical_keys and not _physical_value_allowed(db, lineage, key, output[key], output):
                continue
            setattr(lineage, key, output[key])
    lineage.open_questions = _text(output.get("open_questions")) or lineage.open_questions
    lineage.confidence_level = output.get("confidence_level") or lineage.confidence_level
    lineage.ai_generated_content = output.get("final_content_draft") or _technical_content(lineage, scenario)
    if evidence_text:
        lineage.ai_generated_content = f"{lineage.ai_generated_content}\n\n目录字段与安全探查摘要：\n{evidence_text}"
    record_audit(db, action="generate_technical_draft", resource_type="scenario_technical_lineage", resource_id=lineage.id, project_id=lineage.project_id, after={"confidence_level": lineage.confidence_level, "claim_type": output.get("claim_type", "evidence_supported" if evidence else "inferred"), "citation_count": len(output.get("citations") or evidence), "physical_source_changed": False})
    db.commit()
    db.refresh(lineage)
    return lineage


def _context(field, scenario, model, evidence_text: str | None = None, other_scenarios=None) -> str:
    return (
        f"目标字段：{field.field_code if field else '-'} / {field.field_name if field else '-'}\n"
        f"监管原始定义：{(field.regulatory_original_definition or field.regulatory_description) if field else '-'}\n"
        f"监管定义细化：{field.regulatory_refined_definition if field else '-'}\n"
        f"EAST 映射：{field.east_definition if field else '-'}\n"
        f"产品场景：{scenario.scenario_name if scenario else '-'}\n"
        f"当前人工信息：{model.__dict__}\n"
        f"已绑定目录字段、数据探查、SQL 血缘、历史口径和人工证据（优先引用）：{evidence_text or '无'}\n"
        f"同字段其他场景口径：{[item.final_content or item.ai_generated_content for item in (other_scenarios or [])]}"
    )


def _business_content(mapping, scenario) -> str:
    return f"{scenario.scenario_name if scenario else '当前场景'}业务口径：{mapping.business_definition or '待确认'}"


def _technical_content(lineage, scenario) -> str:
    return (
        f"{scenario.scenario_name if scenario else '当前场景'}技术溯源：来源系统 {lineage.source_system_name or '待确认'}，"
        f"来源表 {lineage.source_table_english_name or '待确认'}，来源字段 {lineage.source_field_english_name or '待确认'}，"
        f"处理逻辑 {lineage.processing_logic or '待确认'}。"
    )


def _text(value) -> str | None:
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return value if isinstance(value, str) else None


def _physical_value_allowed(db, lineage, key: str, value: str, output: dict) -> bool:
    current = getattr(lineage, key, None)
    if current:
        return str(current).lower() == str(value).lower()
    candidates = {
        "source_schema_name": output.get("source_schema_name") or lineage.source_schema_name,
        "source_table_english_name": output.get("source_table_english_name") or lineage.source_table_english_name,
        "source_field_english_name": output.get("source_field_english_name") or lineage.source_field_english_name,
    }
    candidates[key] = value
    if not all(candidates.values()):
        return False
    query = select(CatalogColumn.id).where(
        CatalogColumn.project_id == lineage.project_id,
        CatalogColumn.enabled.is_(True),
        CatalogColumn.schema_name == candidates["source_schema_name"],
        CatalogColumn.table_name == candidates["source_table_english_name"],
        CatalogColumn.column_name == candidates["source_field_english_name"],
    )
    return db.scalar(query.limit(1)) is not None
