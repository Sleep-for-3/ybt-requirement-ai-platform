"""Interpretation-level SQL change candidates.

A thin, deliberately **non-authoritative** projection over the existing
deterministic ``compare_sql_versions``: it names each change category in business
language and flags the ones that can move a regulatory caliber. It never decides
business meaning and never claims compliance — every item it produces is an
*interpretation* that needs the SQL evidence plus human confirmation.

Text-only diffing is explicitly not the goal here; the underlying comparator is
already AST/semantic based (it parses both versions into lineage edges and
compares filters, joins, aggregations, code mappings and transformations).
"""
from __future__ import annotations

from typing import Any

from app.services.lineage.version_diff import ChangeItemSpec, compare_sql_versions

SEMANTIC_LABELS: dict[str, str] = {
    "filter_changed": "过滤范围（WHERE/条件）发生变化",
    "join_changed": "关联对象或 JOIN 条件发生变化",
    "join_type_changed": "JOIN 类型发生变化",
    "aggregation_changed": "聚合逻辑发生变化",
    "code_mapping_changed": "代码映射（CASE WHEN 等）发生变化",
    "transformation_changed": "取值/加工规则发生变化",
    "source_column_removed": "来源字段被移除",
    "source_column_added": "新增来源字段",
    "source_table_changed": "来源表发生变化",
    "target_column_changed": "目标字段发生变化",
    "parse_quality_changed": "解析质量发生变化",
    "script_dependency_changed": "脚本依赖发生变化",
    "non_semantic": "非语义变化（格式/注释）",
}
# Categories that can move a regulatory caliber and therefore need a human read.
CALIBER_AFFECTING: frozenset[str] = frozenset({
    "filter_changed", "join_changed", "join_type_changed", "aggregation_changed",
    "code_mapping_changed", "transformation_changed", "source_column_removed",
    "source_table_changed", "target_column_changed",
})
CALIBER_IMPACT = "可能改变该监管字段的统计口径或取值范围"


def _first_text(value: Any, limit: int = 120) -> str:
    """Best-effort readable excerpt from a comparator value dict (never invented)."""

    if isinstance(value, str):
        return value.strip()[:limit]
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("expression", "filter_condition", "join_condition", "condition", "rule",
                    "name", "column", "table", "normalized", "sql"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                parts.append(raw.strip()[:limit])
        if not parts:
            for raw in value.values():
                if isinstance(raw, str) and raw.strip():
                    parts.append(raw.strip()[:limit])
                    break
        return " | ".join(parts)
    return ""


def change_item(item: ChangeItemSpec) -> dict[str, Any]:
    category = item.change_category
    label = SEMANTIC_LABELS.get(category, category)
    before = _first_text(item.old_value)
    after = _first_text(item.new_value)
    if before and after and before != after:
        detail = f"{before} → {after}"
    elif before:
        detail = before
    elif after:
        detail = after
    else:
        detail = "（无文本表达式，需结合 SQL 原文确认）"
    semantic = category != "non_semantic"
    affects_caliber = category in CALIBER_AFFECTING
    return {
        "category": category,
        "label": label,
        "entity_type": item.entity_type,
        "severity": item.severity,
        "semantic": semantic,
        "affects_caliber": affects_caliber,
        "before": before,
        "after": after,
        "detail": detail,
        "statement": (
            f"{label}：{detail}；{CALIBER_IMPACT}（interpretation，需 Evidence 与人工确认）"
            if affects_caliber else f"{label}：{detail}"
        ),
    }


def semantic_changes(old_sql: str, new_sql: str, *, dialect: str = "") -> dict[str, Any]:
    """Structured, interpretation-level change set between two SQL versions."""

    diff = compare_sql_versions(old_sql, new_sql, dialect=dialect)
    items = [change_item(item) for item in diff.items]
    semantic_items = [item for item in items if item["semantic"]]
    return {
        "semantic_changed": diff.semantic_changed,
        "severity": diff.severity,
        "items": items,
        "semantic_items": semantic_items,
        "caliber_affecting_count": len([item for item in items if item["affects_caliber"]]),
        "categories": sorted({item["category"] for item in items}),
        "summary": dict(diff.summary or {}),
        "authority": "interpretation",
        "requires_human_confirmation": True,
    }
