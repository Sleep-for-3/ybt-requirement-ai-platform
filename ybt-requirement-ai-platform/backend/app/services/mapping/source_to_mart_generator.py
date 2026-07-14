from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MappingEvidenceReference, MartField, MartTable, SourceField, SourceTable, SourceToMartMapping
from app.services.llm.prompt_runtime import get_prompt_runtime,get_runtime_llm_service,prepare_model_input,record_model_call
from app.services.retrieval import HybridRetriever


async def generate_source_to_mart_draft(db: Session, mapping_id: int) -> SourceToMartMapping:
    mapping = db.get(SourceToMartMapping, mapping_id)
    if mapping is None:
        raise ValueError("Source-to-mart mapping not found")

    mart_field = db.get(MartField, mapping.mart_field_id)
    mart_table = db.get(MartTable, mart_field.mart_table_id) if mart_field else None
    evidence_rows = db.scalars(
        select(MappingEvidenceReference)
        .where(
            MappingEvidenceReference.mapping_type == "source_to_mart",
            MappingEvidenceReference.mapping_id == mapping.id,
        )
        .order_by(MappingEvidenceReference.id)
    ).all()
    source_candidates = _source_candidates(db, mapping.project_id)

    user_prompt = f"""
监管集市字段:
- 集市表: {mart_table.table_code if mart_table else "-"} / {mart_table.table_name if mart_table else "-"}
- 集市字段: {mart_field.field_code if mart_field else "-"} / {mart_field.field_name if mart_field else "-"}
- 字段类型: {mart_field.field_type if mart_field else "-"}
- 设计说明: {mart_field.field_comment if mart_field else "-"}

当前人工信息:
- 来源系统摘要: {mapping.source_system_summary or "-"}
- 来源表摘要: {mapping.source_tables_summary or "-"}
- 来源字段摘要: {mapping.source_fields_summary or "-"}
- 业务规则: {mapping.business_rule or "-"}
- 过滤条件: {mapping.filter_condition or "-"}
- 关联条件: {mapping.join_condition or "-"}
- 优先级: {mapping.priority_rule or "-"}
- 多系统合并: {mapping.merge_rule or "-"}

候选源字段:
{source_candidates}

证据:
{_evidence_text(evidence_rows)}
"""
    runtime=get_prompt_runtime(db,"source_to_mart_mapping");retrieval_log,knowledge=HybridRetriever(db).search(mapping.project_id,f"{mart_field.field_name if mart_field else ''} {mapping.source_fields_summary or ''}",None,None,None,10);user_prompt+=f"\n混合知识证据:\n"+"\n".join(f"[{item['knowledge_unit_id']}] {item['content']}" for item in knowledge);model_input=prepare_model_input(runtime,user_prompt,[item["confidentiality_level"] for item in knowledge]);output = await get_runtime_llm_service(runtime).chat_json(runtime.system_prompt, model_input);record_model_call(db,mapping.project_id,runtime,model_input,output,retrieval_log_id=retrieval_log.id)
    _apply_output(mapping, output)
    db.commit()
    db.refresh(mapping)
    return mapping


def _apply_output(mapping: SourceToMartMapping, output: dict) -> None:
    mapping.source_system_summary = output.get("source_system_summary") or mapping.source_system_summary
    mapping.source_tables_summary = output.get("source_tables_summary") or mapping.source_tables_summary
    mapping.source_fields_summary = output.get("source_fields_summary") or mapping.source_fields_summary
    mapping.business_rule = output.get("business_rule") or output.get("business_to_mart_rule") or mapping.business_rule
    mapping.filter_condition = output.get("filter_condition") or mapping.filter_condition
    mapping.join_condition = output.get("join_condition") or mapping.join_condition
    mapping.priority_rule = output.get("priority_rule") or mapping.priority_rule
    mapping.merge_rule = output.get("merge_rule") or mapping.merge_rule
    mapping.code_mapping_rule = output.get("code_mapping_rule") or mapping.code_mapping_rule
    mapping.null_handling_rule = output.get("null_handling_rule") or mapping.null_handling_rule
    mapping.exception_rule = output.get("exception_rule") or mapping.exception_rule
    mapping.quality_check_rule = output.get("quality_check_rule") or mapping.quality_check_rule
    mapping.open_questions = _questions_text(output.get("open_questions")) or mapping.open_questions
    mapping.confidence_level = output.get("confidence_level") or mapping.confidence_level
    mapping.ai_generated_content = _business_final_content(mapping, output)


def _business_final_content(mapping: SourceToMartMapping, output: dict) -> str:
    draft = output.get("final_content_draft")
    if draft and not _looks_like_raw_sql(draft):
        return f"业务系统到监管集市口径：\n{draft}"
    lines = [
        "业务系统到监管集市口径：",
        f"来源业务系统：{mapping.source_system_summary or '待确认'}",
        f"来源表：{mapping.source_tables_summary or '待确认'}",
        f"来源字段：{mapping.source_fields_summary or '待确认'}",
        f"业务规则：{mapping.business_rule or '待确认'}",
        f"过滤条件：{mapping.filter_condition or '待确认'}",
        f"关联条件：{mapping.join_condition or '待确认'}",
        f"优先级规则：{mapping.priority_rule or '待确认'}",
        f"多系统合并规则：{mapping.merge_rule or '待确认'}",
        f"码值转换：{mapping.code_mapping_rule or '待确认'}",
        f"空值处理：{mapping.null_handling_rule or '待确认'}",
        f"异常处理：{mapping.exception_rule or '待确认'}",
        f"质量校验规则：{mapping.quality_check_rule or '待确认'}",
        f"待确认问题：{mapping.open_questions or '暂无'}",
    ]
    return "\n".join(lines)


def _source_candidates(db: Session, project_id: int) -> str:
    rows = db.execute(
        select(SourceField, SourceTable)
        .join(SourceTable, SourceTable.id == SourceField.source_table_id)
        .where(SourceField.project_id == project_id)
        .limit(50)
    ).all()
    if not rows:
        return "暂无候选源字段。"
    return "\n".join(
        f"- {table.table_code}.{field.field_code} / {field.field_name} / {field.field_type or '-'}"
        for field, table in rows
    )


def _evidence_text(evidence_rows: list[MappingEvidenceReference]) -> str:
    if not evidence_rows:
        return "暂无绑定证据，生成内容必须标记待确认。"
    return "\n".join(
        f"- {item.evidence_type} / {item.source_name} / {item.location_text or '-'}: "
        f"{item.evidence_summary or item.quoted_content or '-'}"
        for item in evidence_rows
    )


def _questions_text(value: object) -> str | None:
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    if isinstance(value, str):
        return value
    return None


def _looks_like_raw_sql(text: str) -> bool:
    stripped = text.strip().lower()
    return stripped.startswith(("select ", "with ")) and (" from " in stripped or "\nfrom " in stripped)
