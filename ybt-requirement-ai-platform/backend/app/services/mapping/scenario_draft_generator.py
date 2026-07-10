from sqlalchemy.orm import Session

from app.models import ProductScenario, ScenarioBusinessMapping, ScenarioTechnicalLineage, TargetField
from app.services.llm import get_llm_service

BUSINESS_PROMPT = """你是银行一表通业务需求分析专家。请生成场景业务口径草稿，输出 JSON：
business_definition, source_system_screenshot_required, source_system_change_required, external_data_required,
manual_supplement_required, business_owner, remarks, open_questions, confidence_level, final_content_draft。
只描述业务含义和待确认事项，不输出 SQL。"""

TECHNICAL_PROMPT = """你是银行一表通技术溯源需求分析专家。请生成场景技术溯源草稿，输出 JSON：
source_system_name, source_database_name, source_schema_name, source_table_english_name,
source_table_chinese_name, source_field_english_name, source_field_chinese_name, processing_logic,
processing_logic_type, tech_owner, remarks, open_questions, confidence_level, final_content_draft。
只描述来源和处理规则，不输出可执行 SQL。"""


async def generate_business_draft(db: Session, mapping_id: int) -> ScenarioBusinessMapping:
    mapping = db.get(ScenarioBusinessMapping, mapping_id)
    if mapping is None:
        raise ValueError("Scenario business mapping not found")
    field = db.get(TargetField, mapping.target_field_id)
    scenario = db.get(ProductScenario, mapping.scenario_id)
    output = await get_llm_service().chat_json(BUSINESS_PROMPT, _context(field, scenario, mapping))
    for key in [
        "business_definition", "source_system_screenshot_required", "source_system_change_required",
        "external_data_required", "manual_supplement_required", "business_owner", "remarks",
    ]:
        if output.get(key) is not None:
            setattr(mapping, key, output[key])
    mapping.open_questions = _text(output.get("open_questions")) or mapping.open_questions
    mapping.confidence_level = output.get("confidence_level") or mapping.confidence_level
    mapping.ai_generated_content = output.get("final_content_draft") or _business_content(mapping, scenario)
    db.commit()
    db.refresh(mapping)
    return mapping


async def generate_technical_draft(db: Session, lineage_id: int) -> ScenarioTechnicalLineage:
    lineage = db.get(ScenarioTechnicalLineage, lineage_id)
    if lineage is None:
        raise ValueError("Scenario technical lineage not found")
    field = db.get(TargetField, lineage.target_field_id)
    scenario = db.get(ProductScenario, lineage.scenario_id)
    output = await get_llm_service().chat_json(TECHNICAL_PROMPT, _context(field, scenario, lineage))
    for key in [
        "source_system_name", "source_database_name", "source_schema_name", "source_table_english_name",
        "source_table_chinese_name", "source_field_english_name", "source_field_chinese_name",
        "processing_logic", "processing_logic_type", "tech_owner", "remarks",
    ]:
        if output.get(key) is not None:
            setattr(lineage, key, output[key])
    lineage.open_questions = _text(output.get("open_questions")) or lineage.open_questions
    lineage.confidence_level = output.get("confidence_level") or lineage.confidence_level
    lineage.ai_generated_content = output.get("final_content_draft") or _technical_content(lineage, scenario)
    db.commit()
    db.refresh(lineage)
    return lineage


def _context(field, scenario, model) -> str:
    return (
        f"目标字段：{field.field_code if field else '-'} / {field.field_name if field else '-'}\n"
        f"字段定义：{field.field_definition if field else '-'}\n"
        f"产品场景：{scenario.scenario_name if scenario else '-'}\n"
        f"当前人工信息：{model.__dict__}"
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
