from sqlalchemy import select

from app.models import ScenarioBusinessMapping, ScenarioTechnicalLineage, SourceToMartMapping


def compile_source_to_mart(db, mapping_id: int) -> dict:
    mapping = db.get(SourceToMartMapping, mapping_id)
    if mapping is None: raise ValueError("Source-to-mart mapping not found")
    business = list(db.scalars(select(ScenarioBusinessMapping).where(ScenarioBusinessMapping.project_id == mapping.project_id)).all())
    technical = list(db.scalars(select(ScenarioTechnicalLineage).where(ScenarioTechnicalLineage.project_id == mapping.project_id)).all())
    systems = sorted({item.source_system_name for item in technical if item.source_system_name})
    sources = sorted({f"{item.source_schema_name or ''}.{item.source_table_english_name or ''}.{item.source_field_english_name or ''}".strip(".") for item in technical if item.source_field_english_name})
    questions = [item.open_questions for item in business + technical if item.open_questions]
    content = "\n".join([f"来源系统：{'、'.join(systems) or '待确认'}", f"来源表字段：{'；'.join(sources) or '待确认'}", "多场景按场景识别规则汇总；冲突时按已确认来源优先。", "仅形成业务开发需求，不生成或执行生产 SQL。", f"待确认问题：{'；'.join(questions) or '无'}"])
    mapping.ai_generated_content = content
    mapping.source_system_summary = "、".join(systems)
    mapping.source_fields_summary = "；".join(sources)
    mapping.open_questions = "；".join(questions)
    return {"mapping_id": mapping.id, "draft": content, "claim_type": "evidence_supported" if sources else "unverified", "open_questions": questions}
