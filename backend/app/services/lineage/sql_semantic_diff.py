"""Interpretation-level SQL change candidates.

A thin, deliberately **non-authoritative** projection over the existing
deterministic ``compare_sql_versions``: it names each change category in business
language and flags the ones that can move a regulatory caliber. It never decides
business meaning and never claims compliance — every item it produces is an
*interpretation* that needs the SQL evidence plus human confirmation.

Text-only diffing is explicitly not the goal here; the underlying comparator is
already AST/semantic based (it parses both versions into lineage edges and
compares filters, joins, aggregations, code mappings and transformations).

``semantic_changes`` returns two strictly separated layers:

* ``facts`` — mechanical, verifiable statements about *what* changed (comparator
  category, before/after expression text, stable evidence locator).  A fact never
  states a business consequence.
* ``interpretations`` — business-language impact *candidates*, one per fact, each
  carrying ``requires_human_confirmation = true`` and its ``evidence_ref``.

``SEMANTIC_FAMILIES`` maps the product-spec change families onto the dimensions the
comparator can really see.  A family whose defining construct is not modelled by any
comparator dimension is marked ``unsupported`` and surfaced through
``unsupported_families`` instead of being silently claimed.

Two structural limits of the underlying comparator are preserved on purpose and
must never be papered over:

1. Only statements that produce lineage edges (INSERT/CREATE AS SELECT/MERGE/UPDATE)
   are compared dimension by dimension; a bare ``SELECT`` yields no edge, so any
   change there can only surface as an unattributed AST change.
2. When the AST differs but no dimension matches, ``compare_sql_versions`` emits a
   single script-level fallback item (``entity_type == "script"``).  Facts for that
   item are tagged ``attribution = "unattributed_ast_change"`` so a consumer can see
   that the change was *not* attributed to a structural dimension.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
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

DETECTION_COMPARATOR = "comparator"
DETECTION_UNSUPPORTED = "unsupported"
# ``entity_type`` of the comparator's script-level fallback item: the AST changed
# but nothing could be attributed to a structural dimension.
UNATTRIBUTED_ENTITY_TYPE = "script"
UNATTRIBUTED_ATTRIBUTION = "unattributed_ast_change"
STRUCTURAL_ATTRIBUTION = "structural"
# A ``semantic_fact`` may only carry these mechanical, evidence-bound fields; every
# business conclusion belongs to ``interpretations`` instead.
FACT_FIELDS: tuple[str, ...] = (
    "fact_id", "evidence_ref", "category", "entity_type", "severity",
    "attribution", "before", "after", "detail",
)


@dataclass(frozen=True)
class SemanticFamilySpec:
    """One product-spec change family and exactly what the comparator can see."""

    code: str
    label: str
    detection: str
    comparator_category: str | None
    caliber_impact: bool
    note: str


# Product-spec change families mapped onto real comparator capability.
# ``detection="comparator"`` requires a passing test with a real SQL pair whose
# changed construct is intrinsic to the family; anything else is ``unsupported``
# with the concrete reason, and is surfaced in ``unsupported_families``.
SEMANTIC_FAMILIES: dict[str, SemanticFamilySpec] = {
    "group_by_granularity": SemanticFamilySpec(
        "group_by_granularity", "GROUP BY 粒度", DETECTION_UNSUPPORTED, None, True,
        "comparator 不比较 GROUP BY 键：键变化不进入任何 lineage 属性，实测 group by dt → group by dt, branch 只产生无归因回退项。",
    ),
    "distinct_toggle": SemanticFamilySpec(
        "distinct_toggle", "DISTINCT 增删", DETECTION_UNSUPPORTED, None, True,
        "DISTINCT 不是 comparator 的比较维度：select distinct → select 的投影与边完全一致，只产生无归因回退项。",
    ),
    "union_vs_union_all": SemanticFamilySpec(
        "union_vs_union_all", "UNION ↔ UNION ALL", DETECTION_UNSUPPORTED, None, True,
        "UNION 去重语义未被建模：union all → union 的投影与来源边一致，只产生无归因回退项。",
    ),
    "having": SemanticFamilySpec(
        "having", "HAVING", DETECTION_UNSUPPORTED, None, True,
        "HAVING 不是 exp.Where，comparator 只采集 WHERE 文本：having 条件变化只产生无归因回退项。",
    ),
    "window_function": SemanticFamilySpec(
        "window_function", "Window Function", DETECTION_COMPARATOR, "transformation_changed", True,
        "窗口函数属于投影表达式，transformation_expression 携带整段 OVER 子句；comparator 不区分子句类型。",
    ),
    "partition_by": SemanticFamilySpec(
        "partition_by", "PARTITION BY", DETECTION_COMPARATOR, "transformation_changed", True,
        "PARTITION BY 键变化同时体现在投影表达式与来源列集合（source_column_added/removed）上，不单独分类。",
    ),
    "order_by": SemanticFamilySpec(
        "order_by", "ORDER BY", DETECTION_UNSUPPORTED, None, False,
        "语句级 ORDER BY 不改变任何 lineage 属性：order by dt → order by amt 只产生无归因回退项；窗口内 ORDER BY 属于 window_function 家族。",
    ),
    "row_number_order": SemanticFamilySpec(
        "row_number_order", "ROW_NUMBER 排序", DETECTION_COMPARATOR, "transformation_changed", True,
        "排序函数与窗口排序键变化进入 transformation_expression；row_number → rank 亦可能同时触发 aggregation_rule 变化。",
    ),
    "top_limit": SemanticFamilySpec(
        "top_limit", "TOP · LIMIT", DETECTION_UNSUPPORTED, None, True,
        "LIMIT/TOP 不进入任何 lineage 属性：limit 10 → limit 100 只产生无归因回退项，行数范围无法被机械定位。",
    ),
    "date_boundary": SemanticFamilySpec(
        "date_boundary", "日期边界", DETECTION_COMPARATOR, "filter_changed", True,
        "日期边界以整个 WHERE 谓词文本作为 before/after 证据，不单独解析边界字面量。",
    ),
    "gt_vs_ge": SemanticFamilySpec(
        "gt_vs_ge", "> ↔ >=", DETECTION_COMPARATOR, "filter_changed", True,
        "比较运算符变化由整体谓词文本捕获，comparator 不单独分类运算符。",
    ),
    "lt_vs_le": SemanticFamilySpec(
        "lt_vs_le", "< ↔ <=", DETECTION_COMPARATOR, "filter_changed", True,
        "同 gt_vs_ge：以整体谓词文本为证据，不单独分类运算符。",
    ),
    "between_boundary": SemanticFamilySpec(
        "between_boundary", "BETWEEN 边界", DETECTION_COMPARATOR, "filter_changed", True,
        "BETWEEN 上下界变化以整体谓词文本为证据。",
    ),
    "null_predicate": SemanticFamilySpec(
        "null_predicate", "NULL", DETECTION_COMPARATOR, "filter_changed", True,
        "IS NULL ↔ IS NOT NULL 由整体谓词文本捕获（sqlglot 归一为 not ... is null）。",
    ),
    "nvl": SemanticFamilySpec(
        "nvl", "NVL", DETECTION_COMPARATOR, "transformation_changed", True,
        "NVL 经 sqlglot 归一为 coalesce，证据中显示为 coalesce(...)。",
    ),
    "coalesce": SemanticFamilySpec(
        "coalesce", "COALESCE", DETECTION_COMPARATOR, "transformation_changed", True,
        "COALESCE 参数变化进入 transformation_expression；删去兜底来源列时同时产生 source_column_removed。",
    ),
    "cast": SemanticFamilySpec(
        "cast", "CAST", DETECTION_COMPARATOR, "transformation_changed", True,
        "CAST 作为投影表达式被比较，comparator 不单独解析目标类型。",
    ),
    "decimal_precision_scale": SemanticFamilySpec(
        "decimal_precision_scale", "DECIMAL 精度·标度", DETECTION_COMPARATOR, "transformation_changed", True,
        "精度/标度变化与 cast 家族同粒度（transformation_changed），comparator 不单独分类。",
    ),
    "case_when_order": SemanticFamilySpec(
        "case_when_order", "CASE WHEN 顺序", DETECTION_COMPARATOR, "code_mapping_changed", True,
        "CASE 投影产生 code_mapping_rule，WHEN 顺序变化即规则文本变化。",
    ),
    "case_else": SemanticFamilySpec(
        "case_else", "CASE ELSE", DETECTION_COMPARATOR, "code_mapping_changed", True,
        "ELSE 分支文本属于 code_mapping_rule，变化即被捕获。",
    ),
    "sign_flip": SemanticFamilySpec(
        "sign_flip", "符号翻转", DETECTION_COMPARATOR, "transformation_changed", True,
        "一元取负属于投影表达式，变化进入 transformation_expression。",
    ),
    "plus_minus": SemanticFamilySpec(
        "plus_minus", "+/-", DETECTION_COMPARATOR, "transformation_changed", True,
        "加减运算属于投影表达式，运算与来源列集合变化均被捕获。",
    ),
    "amount_unit": SemanticFamilySpec(
        "amount_unit", "金额单位", DETECTION_COMPARATOR, "transformation_changed", True,
        "单位换算（如 /10000）只能作为投影表达式变化被捕获，comparator 不建模单位语义。",
    ),
    "ratio_scale": SemanticFamilySpec(
        "ratio_scale", "比例 ×100·÷100", DETECTION_COMPARATOR, "transformation_changed", True,
        "比例放大/缩小属于投影表达式变化，comparator 不建模比例语义。",
    ),
    "currency": SemanticFamilySpec(
        "currency", "币种", DETECTION_COMPARATOR, "filter_changed", True,
        "币种仅作为谓词字面量被捕获（ccy='CNY' → ccy='USD'）；comparator 不建模币种语义。",
    ),
    "abs": SemanticFamilySpec(
        "abs", "ABS", DETECTION_COMPARATOR, "transformation_changed", True,
        "ABS 属于投影表达式，变化进入 transformation_expression。",
    ),
    "round": SemanticFamilySpec(
        "round", "ROUND", DETECTION_COMPARATOR, "transformation_changed", True,
        "ROUND 位数变化属于投影表达式变化。",
    ),
    "trunc": SemanticFamilySpec(
        "trunc", "TRUNC", DETECTION_COMPARATOR, "transformation_changed", True,
        "TRUNC 位数变化属于投影表达式变化。",
    ),
    "date_part": SemanticFamilySpec(
        "date_part", "日期取月·季·年", DETECTION_COMPARATOR, "transformation_changed", True,
        "日期粒度提取（如 date_trunc('month') → 'quarter'）属于投影表达式变化。",
    ),
    "subquery": SemanticFamilySpec(
        "subquery", "子查询", DETECTION_COMPARATOR, "filter_changed", True,
        "子查询文本作为谓词的一部分被捕获；子查询相关列变化会体现为来源列增删。",
    ),
    "cte": SemanticFamilySpec(
        "cte", "CTE", DETECTION_UNSUPPORTED, None, True,
        "comparator 不建模 CTE 结构：CTE 内部投影变化只产生无归因回退项；CTE 内谓词变化虽落到 filter_changed 但不携带 CTE 上下文，无法归因到 CTE 家族。",
    ),
    "exists": SemanticFamilySpec(
        "exists", "EXISTS", DETECTION_COMPARATOR, "filter_changed", True,
        "EXISTS 谓词文本进入 filter_condition，增删 EXISTS 子句即谓词变化。",
    ),
    "not_exists": SemanticFamilySpec(
        "not_exists", "NOT EXISTS", DETECTION_COMPARATOR, "filter_changed", True,
        "NOT EXISTS ↔ EXISTS 由整体谓词文本捕获。",
    ),
    "in_predicate": SemanticFamilySpec(
        "in_predicate", "IN", DETECTION_COMPARATOR, "filter_changed", True,
        "IN 列表变化以整体谓词文本为证据。",
    ),
    "not_in_predicate": SemanticFamilySpec(
        "not_in_predicate", "NOT IN", DETECTION_COMPARATOR, "filter_changed", True,
        "NOT IN ↔ IN 由整体谓词文本捕获。",
    ),
    "join_key": SemanticFamilySpec(
        "join_key", "JOIN key", DETECTION_COMPARATOR, "join_changed", True,
        "ON 子句文本进入 join_condition，关联键变化即 join_changed。",
    ),
    "left_vs_inner_join": SemanticFamilySpec(
        "left_vs_inner_join", "LEFT ↔ INNER", DETECTION_UNSUPPORTED, None, True,
        "comparator 只采集 JOIN ON 文本、不比较 JOIN 类型：left join → inner join（ON 不变）只产生无归因回退项。",
    ),
    "full_join": SemanticFamilySpec(
        "full_join", "FULL JOIN", DETECTION_UNSUPPORTED, None, True,
        "同 left_vs_inner_join：JOIN 类型不在比较维度内，实测 left join → full outer join 只产生无归因回退项。",
    ),
    "multi_table_aggregation_granularity": SemanticFamilySpec(
        "multi_table_aggregation_granularity", "多表聚合粒度", DETECTION_UNSUPPORTED, None, True,
        "多表聚合粒度由 GROUP BY 键决定，而 comparator 不比较 GROUP BY（实测只产生无归因回退项）。",
    ),
}


def unsupported_families() -> list[dict[str, Any]]:
    """Families the comparator cannot detect, each with its concrete reason."""

    return [
        {"code": spec.code, "label": spec.label, "reason": spec.note}
        for spec in SEMANTIC_FAMILIES.values()
        if spec.detection == DETECTION_UNSUPPORTED
    ]


def _text_parts(value: Any, limit: int) -> list[str]:
    """Readable excerpts from a comparator value leaf (string or list of strings)."""

    if isinstance(value, str):
        stripped = value.strip()[:limit]
        return [stripped] if stripped else []
    if isinstance(value, (list, tuple)):
        parts: list[str] = []
        for item in value:
            parts.extend(_text_parts(item, limit))
        return parts
    return []


def _first_text(value: Any, limit: int = 120) -> str:
    """Best-effort readable excerpt from a comparator value (never invented).

    The comparator stores condition/rule evidence as ``{attr: [values]}``, so list
    leaves must be read too — otherwise a fact would carry an empty before/after
    where the comparator did in fact provide the changed expression text.
    """

    if isinstance(value, str):
        return value.strip()[:limit]
    if isinstance(value, (list, tuple)):
        return " | ".join(_text_parts(value, limit))
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("expression", "filter_condition", "join_condition", "condition", "rule",
                    "name", "column", "table", "normalized", "sql"):
            parts.extend(_text_parts(value.get(key), limit))
        if not parts:
            for raw in value.values():
                parts.extend(_text_parts(raw, limit))
                if parts:
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


def _evidence_prefix(old_sql: str, new_sql: str) -> str:
    """Stable pair digest; same canonicalisation as the agent tool's ``sql_diff:`` id.

    The tool consumer keys its evidence record as
    ``sql_diff:<sha256 of sorted-key JSON of {"old", "new"}>[:16]``; keeping the
    same shape lets ``evidence_ref`` resolve against that evidence record.
    """

    payload = json.dumps({"old": old_sql, "new": new_sql}, ensure_ascii=False, sort_keys=True)
    return f"sql_diff:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def semantic_fact(item: dict[str, Any], *, index: int, evidence_prefix: str) -> dict[str, Any]:
    """Project one comparator change into a mechanical fact (no business conclusion)."""

    evidence_ref = f"{evidence_prefix}#{index}"
    fact = {
        "fact_id": evidence_ref,
        "evidence_ref": evidence_ref,
        "category": item["category"],
        "entity_type": item["entity_type"],
        "severity": item["severity"],
        "attribution": (
            UNATTRIBUTED_ATTRIBUTION
            if item["entity_type"] == UNATTRIBUTED_ENTITY_TYPE
            else STRUCTURAL_ATTRIBUTION
        ),
        "before": item["before"],
        "after": item["after"],
        "detail": item["detail"],
    }
    return {key: fact[key] for key in FACT_FIELDS}


def semantic_interpretation(item: dict[str, Any], fact: dict[str, Any]) -> dict[str, Any]:
    """Business-language impact *candidate* for one fact — always human-gated."""

    impact = CALIBER_IMPACT if item["affects_caliber"] else "该语义变化是否影响口径需人工判断"
    if fact["attribution"] == UNATTRIBUTED_ATTRIBUTION:
        impact = f"{impact}；comparator 未能把该变化归因到结构化维度"
    return {
        "category": item["category"],
        "statement": (
            f"{item['label']}：{item['detail']}；{impact}"
            f"（interpretation，需人工确认；evidence_ref={fact['evidence_ref']}）"
        ),
        "requires_human_confirmation": True,
        "evidence_ref": fact["evidence_ref"],
        "fact_id": fact["fact_id"],
    }


def semantic_changes(old_sql: str, new_sql: str, *, dialect: str = "") -> dict[str, Any]:
    """Structured, interpretation-level change set between two SQL versions.

    Legacy keys (consumed by the agent tool and its tests) are preserved verbatim;
    ``facts``/``interpretations``/``unsupported_families``/``family_coverage`` are
    additive.
    """

    diff = compare_sql_versions(old_sql, new_sql, dialect=dialect)
    items = [change_item(item) for item in diff.items]
    semantic_items = [item for item in items if item["semantic"]]
    evidence_prefix = _evidence_prefix(old_sql, new_sql)
    facts = [
        semantic_fact(item, index=index, evidence_prefix=evidence_prefix)
        for index, item in enumerate(semantic_items)
    ]
    interpretations = [
        semantic_interpretation(item, fact) for item, fact in zip(semantic_items, facts)
    ]
    detectable = [
        spec for spec in SEMANTIC_FAMILIES.values() if spec.detection == DETECTION_COMPARATOR
    ]
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
        "facts": facts,
        "interpretations": interpretations,
        "unsupported_families": unsupported_families(),
        "family_coverage": {"detected": len(detectable), "total": len(SEMANTIC_FAMILIES)},
    }
