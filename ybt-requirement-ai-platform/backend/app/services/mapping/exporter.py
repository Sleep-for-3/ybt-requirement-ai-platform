from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    MappingEvidenceReference,
    MappingVersion,
    MartField,
    MartTable,
    MartToYbtMapping,
    Project,
    SourceToMartMapping,
    TargetField,
    TargetTable,
)


def export_project_mapping_document(db: Session, project_id: int) -> str:
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found")
    fields = db.scalars(select(TargetField).where(TargetField.project_id == project_id).order_by(TargetField.id)).all()
    lines = _document_header(project, "整个项目")
    for field in fields:
        table = db.get(TargetTable, field.target_table_id)
        lines.extend(_field_section(db, project, table, field))
    return "\n".join(lines)


def export_table_mapping_document(db: Session, table_id: int) -> str:
    table = db.get(TargetTable, table_id)
    if table is None:
        raise ValueError("Target table not found")
    project = db.get(Project, table.project_id)
    fields = db.scalars(select(TargetField).where(TargetField.target_table_id == table.id).order_by(TargetField.id)).all()
    lines = _document_header(project, f"一表通表 {table.table_code}") if project else ["# 一表通业务口径需求文档"]
    lines.extend(_table_info(table))
    for field in fields:
        lines.extend(_field_section(db, project, table, field))
    return "\n".join(lines)


def export_field_mapping_document(db: Session, field_id: int) -> str:
    field = db.get(TargetField, field_id)
    if field is None:
        raise ValueError("Target field not found")
    table = db.get(TargetTable, field.target_table_id)
    project = db.get(Project, field.project_id)
    lines = _document_header(project, f"一表通字段 {field.field_code}") if project else ["# 一表通业务口径需求文档"]
    if table:
        lines.extend(_table_info(table))
    lines.extend(_field_section(db, project, table, field))
    return "\n".join(lines)


def _document_header(project: Project, scope: str) -> list[str]:
    return [
        "# 一表通业务口径需求文档",
        "",
        "## 一、项目信息",
        "",
        f"- 项目名称：{project.name}",
        f"- 银行名称：{project.bank_name or '-'}",
        f"- 文档生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 生成范围：{scope}",
        "",
    ]


def _table_info(table: TargetTable) -> list[str]:
    return [
        "## 二、一表通目标表",
        "",
        "### 2.1 表信息",
        "",
        f"- 表代码：{table.table_code}",
        f"- 表名称：{table.table_name}",
        f"- 表说明：{table.description or '-'}",
        "",
    ]


def _field_section(db: Session, project: Project | None, table: TargetTable | None, field: TargetField) -> list[str]:
    ybt_mappings = db.scalars(
        select(MartToYbtMapping).where(MartToYbtMapping.target_field_id == field.id).order_by(MartToYbtMapping.id)
    ).all()
    if not ybt_mappings:
        ybt_mappings = [None]

    lines = [
        f"### 字段：{field.field_code} / {field.field_name}",
        "",
        "#### 一表通字段信息",
        "",
        f"- 一表通表：{table.table_code if table else '-'} / {table.table_name if table else '-'}",
        f"- 一表通字段代码：{field.field_code}",
        f"- 一表通字段名称：{field.field_name}",
        f"- 字段类型：{field.field_type or '-'}",
        f"- 是否必填：{'是' if field.required_flag else '否'}",
        f"- 监管定义：{field.regulatory_description or field.field_definition or '-'}",
        "",
    ]

    for index, ybt_mapping in enumerate(ybt_mappings, start=1):
        mart_field = db.get(MartField, ybt_mapping.mart_field_id) if ybt_mapping and ybt_mapping.mart_field_id else None
        mart_table = db.get(MartTable, mart_field.mart_table_id) if mart_field else None
        source_mappings = _source_mappings(db, field.project_id, mart_field.id if mart_field else None)

        lines.extend(
            [
                f"#### 监管集市字段设计 {index}",
                "",
                f"- 监管集市表：{mart_table.table_code if mart_table else ybt_mapping.mart_table_summary if ybt_mapping else '-'}",
                f"- 监管集市字段：{mart_field.field_code if mart_field else ybt_mapping.mart_field_summary if ybt_mapping else '-'}",
                f"- 字段中文名：{mart_field.field_name if mart_field else '-'}",
                f"- 字段类型：{mart_field.field_type if mart_field else '-'}",
                f"- 是否已有字段：{_yes_no(mart_field.is_existing) if mart_field else '-'}",
                f"- 设计说明：{mart_field.description or mart_field.field_comment if mart_field else '-'}",
                "",
                "#### 业务系统到监管集市取数口径",
                "",
            ]
        )
        if source_mappings:
            for source_mapping in source_mappings:
                lines.extend(_source_mapping_lines(source_mapping))
        else:
            lines.append("- 暂未维护业务系统到监管集市口径。")
            lines.append("")

        lines.extend(["#### 监管集市到一表通取数口径", ""])
        if ybt_mapping:
            lines.extend(_mart_to_ybt_lines(ybt_mapping))
        else:
            lines.append("- 暂未维护监管集市到一表通口径。")
            lines.append("")

        lines.extend(["#### 参考依据", ""])
        lines.extend(_evidence_lines(db, source_mappings, ybt_mapping))
        lines.extend(["", "#### 待确认问题", ""])
        questions = _questions(source_mappings, ybt_mapping)
        if questions:
            lines.extend(f"{idx}. {item}" for idx, item in enumerate(questions, start=1))
        else:
            lines.append("1. 暂无。")
        lines.extend(["", "#### 审核状态与版本", ""])
        lines.extend(_status_lines(db, source_mappings, ybt_mapping))
        lines.append("")
    return lines


def _source_mapping_lines(mapping: SourceToMartMapping) -> list[str]:
    return [
        f"- 口径名称：{mapping.mapping_name or mapping.id}",
        f"- 来源业务系统：{mapping.source_system_summary or '-'}",
        f"- 来源表：{mapping.source_tables_summary or '-'}",
        f"- 来源字段：{mapping.source_fields_summary or '-'}",
        f"- 业务规则：{mapping.business_rule or mapping.final_content or '-'}",
        f"- 过滤条件：{mapping.filter_condition or '-'}",
        f"- 关联条件：{mapping.join_condition or '-'}",
        f"- 多系统合并规则：{mapping.merge_rule or '-'}",
        f"- 优先级规则：{mapping.priority_rule or '-'}",
        f"- 码值转换：{mapping.code_mapping_rule or '-'}",
        f"- 空值处理：{mapping.null_handling_rule or '-'}",
        f"- 异常处理：{mapping.exception_rule or '-'}",
        f"- 质量校验规则：{mapping.quality_check_rule or '-'}",
        "",
    ]


def _mart_to_ybt_lines(mapping: MartToYbtMapping) -> list[str]:
    return [
        f"- 口径名称：{mapping.mapping_name or mapping.id}",
        f"- 集市来源表：{mapping.mart_table_summary or '-'}",
        f"- 集市来源字段：{mapping.mart_field_summary or '-'}",
        f"- 业务规则：{mapping.business_rule or mapping.final_content or '-'}",
        f"- 过滤条件：{mapping.filter_condition or '-'}",
        f"- 关联条件：{mapping.join_condition or '-'}",
        f"- 码值转换：{mapping.code_mapping_rule or '-'}",
        f"- 空值处理：{mapping.null_handling_rule or '-'}",
        f"- 报送限制条件：{mapping.reporting_condition or '-'}",
        f"- 校验规则：{mapping.validation_rule or '-'}",
        "",
    ]


def _source_mappings(db: Session, project_id: int, mart_field_id: int | None) -> list[SourceToMartMapping]:
    if mart_field_id is None:
        return []
    return list(
        db.scalars(
            select(SourceToMartMapping)
            .where(SourceToMartMapping.project_id == project_id, SourceToMartMapping.mart_field_id == mart_field_id)
            .order_by(SourceToMartMapping.id)
        ).all()
    )


def _evidence_lines(db: Session, source_mappings: list[SourceToMartMapping], ybt_mapping: MartToYbtMapping | None) -> list[str]:
    mapping_refs = [("source_to_mart", item.id) for item in source_mappings]
    if ybt_mapping:
        mapping_refs.append(("mart_to_ybt", ybt_mapping.id))
    lines: list[str] = []
    for mapping_type, mapping_id in mapping_refs:
        rows = db.scalars(
            select(MappingEvidenceReference)
            .where(MappingEvidenceReference.mapping_type == mapping_type, MappingEvidenceReference.mapping_id == mapping_id)
            .order_by(MappingEvidenceReference.id)
        ).all()
        for item in rows:
            lines.append(f"- {mapping_type} / {item.evidence_type} / {item.source_name} / {item.location_text or '-'}：{item.evidence_summary or item.quoted_content or '-'}")
    return lines or ["- 暂无绑定证据。"]


def _questions(source_mappings: list[SourceToMartMapping], ybt_mapping: MartToYbtMapping | None) -> list[str]:
    values: list[str] = []
    for mapping in source_mappings:
        values.extend(_split_questions(mapping.open_questions))
    if ybt_mapping:
        values.extend(_split_questions(ybt_mapping.open_questions))
    return values


def _split_questions(text: str | None) -> list[str]:
    if not text:
        return []
    return [item.strip(" -") for item in text.replace("\r", "\n").split("\n") if item.strip()]


def _status_lines(db: Session, source_mappings: list[SourceToMartMapping], ybt_mapping: MartToYbtMapping | None) -> list[str]:
    lines: list[str] = []
    for mapping in source_mappings:
        lines.append(f"- 业务系统到监管集市口径状态：{mapping.mapping_status}")
        lines.append(f"- 业务系统到监管集市当前版本：{_latest_version_no(db, 'source_to_mart', mapping.id)}")
        lines.append(f"- 业务系统到监管集市最近修改人：{mapping.reviewed_by or mapping.created_by or '-'}")
    if ybt_mapping:
        lines.append(f"- 监管集市到一表通口径状态：{ybt_mapping.mapping_status}")
        lines.append(f"- 监管集市到一表通当前版本：{_latest_version_no(db, 'mart_to_ybt', ybt_mapping.id)}")
        lines.append(f"- 监管集市到一表通最近修改人：{ybt_mapping.reviewed_by or ybt_mapping.created_by or '-'}")
    if not lines:
        lines.append("- 审核状态：暂未维护口径。")
    return lines


def _latest_version_no(db: Session, mapping_type: str, mapping_id: int) -> int:
    return db.scalar(
        select(func.max(MappingVersion.version_no)).where(
            MappingVersion.mapping_type == mapping_type,
            MappingVersion.mapping_id == mapping_id,
        )
    ) or 0


def _yes_no(value: bool | None) -> str:
    if value is None:
        return "-"
    return "是" if value else "否"
