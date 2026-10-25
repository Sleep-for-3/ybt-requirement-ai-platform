"""标准模板列填充率（项目级）：把"文档里的空列"分清楚是模板没给、还是平台没填。

真实问题：导出的需求文档里有空列，评审问"为什么数据格式是空的"。真实数据里 2422 个字段的
`data_format` 全为空，因为调研表这一列本身整列没填（不是我方丢字段）；而 `data_category`
只填了 396 行；集市映射 1297 行有值。这些"缺口归属"不同，处置也完全不同：
模板没给 → 找业务要资料；资料或脚本缺 → 补映射/补脚本；需求侧空 → 待业务补充。

因此这里按列统计，并给每列标明缺口归属，只陈述可核实的计数，不推断原因。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    LineageEdge,
    LineageNode,
    MartToYbtMapping,
    Requirement,
    RequirementRevision,
    TargetField,
    TargetTable,
)

TEMPLATE_COVERAGE_VERSION = "requirement-template-coverage-v1"

# 每列：key、中文名、缺口归属（template=模板本身没给 / mapping=集市映射缺 / script=脚本缺 /
# requirement=需求侧待补）
COLUMN_SPECS: tuple[dict[str, str], ...] = (
    {"key": "regulatory_definition", "label": "监管原始口径", "source": "template"},
    {"key": "data_category", "label": "数据类别", "source": "template"},
    {"key": "data_format", "label": "数据格式", "source": "template"},
    {"key": "report_name", "label": "报表名称", "source": "template"},
    {"key": "mart_mapping", "label": "集市表/字段映射", "source": "mapping"},
    {"key": "script_rule", "label": "跑批脚本取数逻辑", "source": "script"},
    {"key": "business_definition", "label": "业务口径正文（需求）", "source": "requirement"},
)

SOURCE_LABELS = {
    "template": "模板未提供该列数据（需向业务要资料）",
    "mapping": "集市映射缺口（需补映射或确认无集市来源）",
    "script": "脚本缺口（需补跑批脚本或确认只写临时表）",
    "requirement": "需求侧待补（需业务确认口径）",
}


def _non_empty(column):
    return func.coalesce(func.nullif(func.trim(column), ""), None).is_not(None)


def _count_fields(db: Session, project_id: int, *conditions) -> int:
    statement = select(func.count(TargetField.id)).where(TargetField.project_id == project_id)
    for condition in conditions:
        statement = statement.where(condition)
    return int(db.execute(statement).scalar() or 0)


def _mapping_count(db: Session, project_id: int) -> int:
    return int(db.execute(
        select(func.count(func.distinct(MartToYbtMapping.target_field_id)))
        .where(MartToYbtMapping.project_id == project_id)
    ).scalar() or 0)


def _script_count(db: Session, project_id: int) -> int:
    """有多少字段至少被一个脚本血缘写入（按 表编号 + 字段编码 对齐）。"""
    return int(db.execute(
        select(func.count(func.distinct(TargetField.id)))
        .select_from(TargetField)
        .join(TargetTable, TargetTable.id == TargetField.target_table_id)
        .join(LineageNode, func.upper(LineageNode.table_name) == func.upper(TargetTable.table_code))
        .join(LineageEdge, LineageEdge.target_node_id == LineageNode.id)
        .where(TargetField.project_id == project_id)
        .where(LineageEdge.project_id == project_id)
        .where(func.upper(LineageNode.column_name) == func.upper(TargetField.field_code))
    ).scalar() or 0)


def _business_count(db: Session, project_id: int) -> int:
    """需求侧有多少字段已经写出业务口径正文（取每条需求的最新修订内容）。"""
    rows = db.execute(
        select(Requirement.id, RequirementRevision.content_version, RequirementRevision.content_json)
        .join(RequirementRevision, RequirementRevision.requirement_id == Requirement.id)
        .where(Requirement.project_id == project_id)
        .order_by(Requirement.id, RequirementRevision.content_version)
    ).all()
    latest: dict[int, dict] = {}
    for requirement_id, _version, content in rows:
        if content:
            latest[int(requirement_id)] = content  # 后出现的 content_version 更大
    field_ids: set[int] = set()
    for content in latest.values():
        for record in content.get("fields") or []:
            if not isinstance(record, dict):
                continue
            field = record.get("field") or record.get("target") or {}
            field_id = field.get("id") or field.get("field_id") or record.get("field_id")
            business = record.get("business") or {}
            text = business.get("business_definition") or business.get("final_content")
            if not field_id:
                continue
            if str(text or "").strip():
                field_ids.add(int(field_id))
    return len(field_ids)


def build_template_coverage(db: Session, project_id: int) -> dict:
    """按标准模板的列统计填充率，并标明缺口归属；只读，不写库。"""
    field_count = _count_fields(db, project_id)
    filled = {
        "regulatory_definition": _count_fields(
            db,
            project_id,
            _non_empty(TargetField.regulatory_original_definition) | _non_empty(TargetField.field_definition),
        ),
        "data_category": _count_fields(db, project_id, _non_empty(TargetField.data_category)),
        "data_format": _count_fields(db, project_id, _non_empty(TargetField.data_format)),
        "report_name": _count_fields(db, project_id, _non_empty(TargetField.report_name)),
        "mart_mapping": _mapping_count(db, project_id),
        "script_rule": _script_count(db, project_id),
        "business_definition": _business_count(db, project_id),
    }

    columns = []
    for spec in COLUMN_SPECS:
        count = min(int(filled.get(spec["key"]) or 0), field_count)
        columns.append({
            "key": spec["key"],
            "label": spec["label"],
            "source": spec["source"],
            "source_label": SOURCE_LABELS[spec["source"]],
            "filled": count,
            "missing": max(field_count - count, 0),
            "fill_rate": round(count / field_count, 4) if field_count else None,
        })
    return {
        "coverage_version": TEMPLATE_COVERAGE_VERSION,
        "project_id": project_id,
        "field_count": field_count,
        "columns": columns,
        "note": "填充率按「该列非空字段数 / 字段总数」统计；缺口归属只说明该列数据由谁提供，不代表业务结论。",
    }


TEMPLATE_COVERAGE_GAP_VERSION = "requirement-template-coverage-gaps-v1"
MAX_GAP_ROWS = 5000

COLUMN_BY_KEY = {spec["key"]: spec for spec in COLUMN_SPECS}


def _business_filled_ids(db: Session, project_id: int) -> set[int]:
    rows = db.execute(
        select(Requirement.id, RequirementRevision.content_version, RequirementRevision.content_json)
        .join(RequirementRevision, RequirementRevision.requirement_id == Requirement.id)
        .where(Requirement.project_id == project_id)
        .order_by(Requirement.id, RequirementRevision.content_version)
    ).all()
    latest: dict[int, dict] = {}
    for requirement_id, _version, content in rows:
        if content:
            latest[int(requirement_id)] = content
    filled: set[int] = set()
    for content in latest.values():
        for record in content.get("fields") or []:
            if not isinstance(record, dict):
                continue
            field = record.get("field") or record.get("target") or {}
            field_id = field.get("id") or field.get("field_id") or record.get("field_id")
            business = record.get("business") or {}
            text = business.get("business_definition") or business.get("final_content")
            if field_id and str(text or "").strip():
                filled.add(int(field_id))
    return filled


def _missing_condition(db: Session, project_id: int, column_key: str):
    """返回"该列缺数据"的 SQL 条件；列名必须是 COLUMN_SPECS 里的 key。"""
    if column_key == "regulatory_definition":
        return ~(_non_empty(TargetField.regulatory_original_definition) | _non_empty(TargetField.field_definition))
    if column_key == "data_category":
        return ~_non_empty(TargetField.data_category)
    if column_key == "data_format":
        return ~_non_empty(TargetField.data_format)
    if column_key == "report_name":
        return ~_non_empty(TargetField.report_name)
    if column_key == "mart_mapping":
        mapped = select(MartToYbtMapping.target_field_id).where(MartToYbtMapping.project_id == project_id)
        return ~TargetField.id.in_(mapped)
    if column_key == "script_rule":
        scripted = (
            select(TargetField.id)
            .select_from(TargetField)
            .join(TargetTable, TargetTable.id == TargetField.target_table_id)
            .join(LineageNode, func.upper(LineageNode.table_name) == func.upper(TargetTable.table_code))
            .join(LineageEdge, LineageEdge.target_node_id == LineageNode.id)
            .where(TargetField.project_id == project_id)
            .where(LineageEdge.project_id == project_id)
            .where(func.upper(LineageNode.column_name) == func.upper(TargetField.field_code))
        )
        return ~TargetField.id.in_(scripted)
    if column_key == "business_definition":
        filled = _business_filled_ids(db, project_id)
        if not filled:
            return TargetField.id.is_not(None)
        return ~TargetField.id.in_(sorted(filled))
    raise ValueError(f"未知的模板列：{column_key}")


def _escape_like(value: str) -> str:
    """表编号里有下划线（T_8_1），LIKE 里 "_" 是通配符：不转义会让 T_8_1 匹配到 T_981。"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _table_condition(filter_value: str):
    """按监管表过滤：默认**完全匹配**，只有以 `*` 结尾才当前缀匹配。

    真实事故：一开始用 `ILIKE %T_8_1%`，结果 `T_8_10`、`T_8_11`… 一起被筛进来，
    弹层却写着"筛选「T_8_1」：164 个字段"——派工的人会以为 T_8_1 有 164 个字段。
    表编号是精确标识，前缀只是少数场景的便利，所以必须显式写 `*`。
    """
    if filter_value.endswith("*"):
        prefix = filter_value[:-1].strip()
        if not prefix:
            return None
        return TargetTable.table_code.ilike(f"{_escape_like(prefix)}%", escape="\\")
    return func.lower(TargetTable.table_code) == filter_value.lower()


def gaps_for_column(
    db: Session,
    project_id: int,
    column_key: str,
    *,
    limit: int = 500,
    table_code: str | None = None,
) -> dict:
    """某一列缺数据的字段清单（可派工），返回截断标记而不是静默截断。

    `table_code` 是"按监管表缩小范围"：2422 个字段的数据格式都为空时，用户想派的往往是
    某一张表（T_8_1）的那几个字段，而不是整项目。过滤只影响本次返回与 CSV，`total` 仍
    报整列总数，避免把"筛出来的 8 条"误当成整列缺口只有 8 条。
    """
    if column_key not in COLUMN_BY_KEY:
        raise ValueError(f"未知的模板列：{column_key}")
    spec = COLUMN_BY_KEY[column_key]
    limit = max(1, min(int(limit), MAX_GAP_ROWS))
    condition = _missing_condition(db, project_id, column_key)
    filter_value = (table_code or "").strip()
    # 只输入 `*` 等于"没筛"；否则 table_filter 会回显 `*`，弹层写着"筛选「*」"却没缩小范围。
    if filter_value == "*":
        filter_value = ""

    total = int(db.execute(
        select(func.count(TargetField.id))
        .where(TargetField.project_id == project_id)
        .where(condition)
    ).scalar() or 0)

    filtered_total = total
    query = (
        select(TargetField, TargetTable)
        .join(TargetTable, TargetTable.id == TargetField.target_table_id)
        .where(TargetField.project_id == project_id)
        .where(condition)
    )
    table_condition = _table_condition(filter_value) if filter_value else None
    if table_condition is not None:
        query = query.where(table_condition)
        filtered_total = int(db.execute(
            select(func.count(TargetField.id))
            .join(TargetTable, TargetTable.id == TargetField.target_table_id)
            .where(TargetField.project_id == project_id)
            .where(condition)
            .where(table_condition)
        ).scalar() or 0)

    rows = db.execute(
        query.order_by(TargetTable.table_code, TargetField.field_code).limit(limit)
    ).all()

    items = []
    for field, table in rows:
        items.append({
            "field_id": int(field.id),
            "field_code": field.field_code,
            "field_name": field.field_name,
            "table_code": table.table_code,
            "table_name": table.table_name,
            "value": _current_value(field, column_key),
        })
    return {
        "gap_version": TEMPLATE_COVERAGE_GAP_VERSION,
        "project_id": project_id,
        "column_key": column_key,
        "column_label": spec["label"],
        "source": spec["source"],
        "source_label": SOURCE_LABELS[spec["source"]],
        "total": total,
        "filtered_total": filtered_total,
        "table_filter": filter_value or None,
        "returned": len(items),
        "truncated": filtered_total > len(items),
        "limit": limit,
        "items": items,
    }


def _current_value(field: TargetField, column_key: str) -> str | None:
    if column_key == "regulatory_definition":
        value = field.regulatory_original_definition or field.field_definition
    elif column_key == "data_category":
        value = field.data_category
    elif column_key == "data_format":
        value = field.data_format
    elif column_key == "report_name":
        value = field.report_name
    else:
        value = None
    text = str(value or "").strip()
    return text or None
