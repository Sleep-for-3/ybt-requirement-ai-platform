from sqlalchemy import select

from app.models import MartField, MartTable, MartToYbtMapping, SourceToMartMapping, TargetField


def compile_mart_to_ybt(db, mapping_id: int) -> dict:
    mapping = db.get(MartToYbtMapping, mapping_id)
    if mapping is None: raise ValueError("Mart-to-YBT mapping not found")
    field, mart_field = db.get(TargetField, mapping.target_field_id), db.get(MartField, mapping.mart_field_id)
    mart_table = db.get(MartTable, mart_field.mart_table_id) if mart_field else None
    upstream = list(db.scalars(select(SourceToMartMapping).where(
        SourceToMartMapping.project_id == mapping.project_id,
        SourceToMartMapping.mart_field_id == mapping.mart_field_id,
    )).all())
    source = f"{mart_table.schema_name + '.' if mart_table and mart_table.schema_name else ''}{mart_table.physical_table_name or mart_table.table_code}.{mart_field.physical_column_name or mart_field.field_code}" if mart_table and mart_field else "待确认"
    content = "\n".join([f"一表通字段：{field.field_code} {field.field_name}", f"监管集市来源：{source}", "按监管时点、机构范围和已审核码值规则取值；异常和空值进入待确认清单。", "仅形成业务开发需求，不生成或执行生产 SQL。"])
    mapping.ai_generated_content = content
    return {"mapping_id": mapping.id, "draft": content, "claim_type": "evidence_supported" if upstream else "inferred", "open_questions": [] if upstream else ["业务系统到集市口径尚未确认"]}
