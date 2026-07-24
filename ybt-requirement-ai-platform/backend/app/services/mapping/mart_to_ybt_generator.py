from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    MappingEvidenceReference,
    MartField,
    MartTable,
    MartToYbtMapping,
    SourceToMartMapping,
    TargetField,
    TargetTable,
)
from app.services.llm.prompt_runtime import execute_runtime_chat,get_prompt_runtime,prepare_model_input
from app.services.llm.structured_outputs import MartToYbtOutput
from app.services.retrieval import HybridRetriever


async def generate_mart_to_ybt_draft(db: Session, mapping_id: int) -> MartToYbtMapping:
    mapping = db.get(MartToYbtMapping, mapping_id)
    if mapping is None:
        raise ValueError("Mart-to-YBT mapping not found")

    target_field = db.get(TargetField, mapping.target_field_id)
    target_table = db.get(TargetTable, target_field.target_table_id) if target_field else None
    mart_field = db.get(MartField, mapping.mart_field_id) if mapping.mart_field_id else None
    mart_table = db.get(MartTable, mart_field.mart_table_id) if mart_field else None
    source_summary = _source_to_mart_summary(db, mapping.project_id, mapping.mart_field_id)
    evidence_rows = db.scalars(
        select(MappingEvidenceReference)
        .where(
            MappingEvidenceReference.mapping_type == "mart_to_ybt",
            MappingEvidenceReference.mapping_id == mapping.id,
        )
        .order_by(MappingEvidenceReference.id)
    ).all()

    user_prompt = f"""
一表通目标字段:
- 一表通表: {target_table.table_code if target_table else "-"} / {target_table.table_name if target_table else "-"}
- 字段: {target_field.field_code if target_field else "-"} / {target_field.field_name if target_field else "-"}
- 字段类型: {target_field.field_type if target_field else "-"}
- 是否必填: {target_field.required_flag if target_field else "-"}
- 监管定义: {target_field.regulatory_description if target_field else "-"}

监管集市来源:
- 集市表: {mart_table.table_code if mart_table else mapping.mart_table_summary or "-"} / {mart_table.table_name if mart_table else "-"}
- 集市字段: {mart_field.field_code if mart_field else mapping.mart_field_summary or "-"} / {mart_field.field_name if mart_field else "-"}
- 集市字段类型: {mart_field.field_type if mart_field else "-"}

业务系统到监管集市口径摘要:
{source_summary}

当前人工信息:
- 业务规则: {mapping.business_rule or "-"}
- 过滤条件: {mapping.filter_condition or "-"}
- 关联条件: {mapping.join_condition or "-"}
- 码值转换: {mapping.code_mapping_rule or "-"}
- 报送限制: {mapping.reporting_condition or "-"}
- 校验规则: {mapping.validation_rule or "-"}

证据:
{_evidence_text(evidence_rows)}
"""
    runtime=get_prompt_runtime(db,"mart_to_ybt_mapping");retrieval_log,knowledge=HybridRetriever(db).search(mapping.project_id,target_field.field_name if target_field else "",mapping.target_field_id,None,None,10);user_prompt+=f"\n混合知识证据:\n"+"\n".join(f"[{item['knowledge_unit_id']}] {item['content']}" for item in knowledge);model_input=prepare_model_input(runtime,user_prompt,[item["confidentiality_level"] for item in knowledge],db=db,project_id=mapping.project_id);output = await execute_runtime_chat(db,mapping.project_id,runtime,model_input,MartToYbtOutput,retrieval_log_id=retrieval_log.id)
    _apply_output(mapping, output)
    db.commit()
    db.refresh(mapping)
    return mapping


def _apply_output(mapping: MartToYbtMapping, output: dict) -> None:
    mapping.mart_table_summary = output.get("mart_table_summary") or mapping.mart_table_summary
    mapping.mart_field_summary = output.get("mart_field_summary") or mapping.mart_field_summary
    mapping.business_rule = output.get("business_rule") or output.get("mart_to_ybt_rule") or mapping.business_rule
    mapping.filter_condition = output.get("filter_condition") or mapping.filter_condition
    mapping.join_condition = output.get("join_condition") or mapping.join_condition
    mapping.code_mapping_rule = output.get("code_mapping_rule") or mapping.code_mapping_rule
    mapping.null_handling_rule = output.get("null_handling_rule") or mapping.null_handling_rule
    mapping.reporting_condition = output.get("reporting_condition") or mapping.reporting_condition
    mapping.validation_rule = output.get("validation_rule") or mapping.validation_rule
    mapping.open_questions = _questions_text(output.get("open_questions")) or mapping.open_questions
    mapping.confidence_level = output.get("confidence_level") or mapping.confidence_level
    mapping.ai_generated_content = _business_final_content(mapping, output)


def _business_final_content(mapping: MartToYbtMapping, output: dict) -> str:
    draft = output.get("final_content_draft")
    if draft and not _looks_like_raw_sql(draft):
        return f"监管集市到一表通口径：\n{draft}"
    lines = [
        "监管集市到一表通口径：",
        f"监管集市表：{mapping.mart_table_summary or '待确认'}",
        f"监管集市字段：{mapping.mart_field_summary or '待确认'}",
        f"业务规则：{mapping.business_rule or '待确认'}",
        f"过滤条件：{mapping.filter_condition or '待确认'}",
        f"关联条件：{mapping.join_condition or '待确认'}",
        f"码值转换：{mapping.code_mapping_rule or '待确认'}",
        f"空值处理：{mapping.null_handling_rule or '待确认'}",
        f"报送限制条件：{mapping.reporting_condition or '待确认'}",
        f"校验规则：{mapping.validation_rule or '待确认'}",
        f"待确认问题：{mapping.open_questions or '暂无'}",
    ]
    return "\n".join(lines)


def _source_to_mart_summary(db: Session, project_id: int, mart_field_id: int | None) -> str:
    if not mart_field_id:
        return "暂未绑定监管集市字段。"
    mappings = db.scalars(
        select(SourceToMartMapping)
        .where(SourceToMartMapping.project_id == project_id, SourceToMartMapping.mart_field_id == mart_field_id)
        .order_by(SourceToMartMapping.id)
    ).all()
    if not mappings:
        return "暂未维护业务系统到监管集市口径。"
    return "\n".join(
        f"- {item.mapping_name or item.id}: {item.final_content or item.business_rule or item.ai_generated_content or '待确认'}"
        for item in mappings
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
