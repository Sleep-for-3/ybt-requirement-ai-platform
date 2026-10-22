from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot

from app.services.lineage.preprocessing import preprocess_sql
from app.services.lineage.sql_parser import LineageEdgeSpec, parse_sql_lineage
from app.services.lineage.shell_parser import parse_shell_dependencies


@dataclass(frozen=True)
class ChangeItemSpec:
    change_category: str
    entity_type: str
    old_value: dict = field(default_factory=dict)
    new_value: dict = field(default_factory=dict)
    severity: str = "low"
    # ``False`` marks the comparator's whole-AST fallback bucket: the SQL text changed
    # but no structural dimension explains it.  Consumers must not read that bucket as a
    # caliber finding, otherwise an equivalent rewrite looks like a business change.
    attributed: bool = True


@dataclass(frozen=True)
class VersionDiffResult:
    semantic_changed: bool
    severity: str
    items: tuple[ChangeItemSpec, ...]
    summary: dict


def compare_sql_versions(old_sql: str, new_sql: str, *, dialect: str = "") -> VersionDiffResult:
    old_ast = _semantic_ast(old_sql, dialect)
    new_ast = _semantic_ast(new_sql, dialect)
    if old_ast == new_ast:
        item = ChangeItemSpec("non_semantic", "script", {"normalized": old_ast}, {"normalized": new_ast}, "low")
        return VersionDiffResult(False, "low", (item,), {"semantic_changed": False, "categories": ["non_semantic"]})

    old = parse_sql_lineage(old_sql, dialect=dialect)
    new = parse_sql_lineage(new_sql, dialect=dialect)
    items: list[ChangeItemSpec] = []
    old_edges = {_edge_key(item): item for item in old.edges if item.source.node_type in {"column", "unknown"}}
    new_edges = {_edge_key(item): item for item in new.edges if item.source.node_type in {"column", "unknown"}}
    for key in sorted(old_edges.keys() - new_edges.keys()):
        edge = old_edges[key]
        items.append(ChangeItemSpec("source_column_removed", "lineage_edge", _edge_value(edge), {}, "critical"))
    for key in sorted(new_edges.keys() - old_edges.keys()):
        edge = new_edges[key]
        items.append(ChangeItemSpec("source_column_added", "lineage_edge", {}, _edge_value(edge), "medium"))

    _condition_changes(items, old.edges, new.edges, "filter_condition", "filter_changed", "high")
    _condition_changes(items, old.edges, new.edges, "join_condition", "join_changed", "high")
    _condition_changes(items, old.edges, new.edges, "code_mapping_rule", "code_mapping_changed", "high")
    _condition_changes(items, old.edges, new.edges, "aggregation_rule", "aggregation_changed", "high")
    _condition_changes(items, old.edges, new.edges, "transformation_expression", "transformation_changed", "high")
    if old.parse_status != new.parse_status:
        items.append(ChangeItemSpec("parse_quality_changed", "script_version", {"status": old.parse_status}, {"status": new.parse_status}, "high"))
    _statement_semantic_changes(items, old, new)
    if not items:
        items.append(ChangeItemSpec(
            "transformation_changed", "script",
            {"normalized": old_ast}, {"normalized": new_ast}, "medium",
            attributed=False,
        ))
    items = _deduplicate(items)
    severity = max((item.severity for item in items), key=lambda value: _rank(value))
    return VersionDiffResult(True, severity, tuple(items), {
        "semantic_changed": True,
        "categories": sorted({item.change_category for item in items}),
        "old_parse_status": old.parse_status,
        "new_parse_status": new.parse_status,
    })


def compare_shell_versions(old_content: str, new_content: str) -> VersionDiffResult:
    old = parse_shell_dependencies(old_content)
    new = parse_shell_dependencies(new_content)
    old_calls = {_shell_dependency_value(item) for item in old.dependencies}
    new_calls = {_shell_dependency_value(item) for item in new.dependencies}
    if old_calls == new_calls:
        item = ChangeItemSpec("non_semantic", "script_dependency", {"dependencies": sorted(old_calls)}, {"dependencies": sorted(new_calls)}, "low")
        return VersionDiffResult(False, "low", (item,), {"semantic_changed": False, "categories": ["non_semantic"]})
    item = ChangeItemSpec(
        "script_dependency_changed", "script_dependency",
        {"dependencies": sorted(old_calls)}, {"dependencies": sorted(new_calls)}, "high",
    )
    return VersionDiffResult(True, "high", (item,), {"semantic_changed": True, "categories": ["script_dependency_changed"]})


def _semantic_ast(sql: str, dialect: str) -> str:
    prepared = preprocess_sql(sql)
    try:
        expressions = sqlglot.parse(prepared.parse_sql, read=dialect or None)
        return ";".join(expression.sql(dialect=dialect or None, pretty=False, normalize=True, comments=False) for expression in expressions if expression)
    except sqlglot.errors.ParseError:
        without_block = re.sub(r"/\*.*?\*/", "", prepared.parse_sql, flags=re.S)
        without_line = re.sub(r"(?m)--.*?$", "", without_block)
        return re.sub(r"\s+", " ", without_line).strip().lower()


def _edge_key(edge: LineageEdgeSpec) -> tuple[str, str, str]:
    return (edge.source.logical_name.lower(), edge.target.logical_name.lower(), edge.edge_type)


def _edge_value(edge: LineageEdgeSpec) -> dict:
    return {"source": edge.source.logical_name, "target": edge.target.logical_name, "edge_type": edge.edge_type}

def _condition_changes(items: list[ChangeItemSpec], old_edges, new_edges, attr: str, category: str, severity: str) -> None:
    old_values = {_normalize(getattr(item, attr)) for item in old_edges if getattr(item, attr)}
    new_values = {_normalize(getattr(item, attr)) for item in new_edges if getattr(item, attr)}
    if old_values != new_values:
        items.append(ChangeItemSpec(category, "lineage_edge", {attr: sorted(old_values)}, {attr: sorted(new_values)}, severity))


def _statement_semantic_changes(items: list[ChangeItemSpec], old_result, new_result) -> None:
    """Compare statement-level constructs that never reach a lineage edge.

    GROUP BY keys, DISTINCT, UNION de-duplication and JOIN kinds change what a query
    returns without changing which column feeds which target, so they are invisible to
    the edge comparator and have to be compared here.  Each family becomes its own
    ``entity_type`` so the fact is attributed to a structural dimension instead of
    falling back to ``unattributed_ast_change``.

    Nothing is emitted when the construct is absent on both sides: absence of evidence
    must never be reported as a change.
    """

    old_states = _semantic_states(old_result)
    new_states = _semantic_states(new_result)
    if not old_states and not new_states:
        return

    def collect(states, key):
        return {value for state in states for value in state.get(key, ()) if value}

    for key, category, family, severity in (
        ("group_by", "group_by_changed", "group_by", "high"),
        ("union_modes", "union_mode_changed", "union", "high"),
        ("join_types", "join_type_changed", "join_type", "high"),
        ("having", "having_changed", "having", "high"),
    ):
        old_values = collect(old_states, key)
        new_values = collect(new_states, key)
        if old_values != new_values:
            items.append(ChangeItemSpec(
                category, family,
                {key: sorted(old_values)}, {key: sorted(new_values)}, severity,
            ))

    # DISTINCT is a mode, not a list, and sqlglot marks a plain ``UNION`` query as
    # distinct internally.  Only a DISTINCT that is not explained by a UNION change is
    # reported, so a UNION rewrite cannot masquerade as a DISTINCT change.
    old_distinct = any(state.get("distinct") for state in old_states)
    new_distinct = any(state.get("distinct") for state in new_states)
    union_changed = collect(old_states, "union_modes") != collect(new_states, "union_modes")
    if old_distinct != new_distinct and not union_changed:
        items.append(ChangeItemSpec(
            "distinct_changed", "distinct",
            {"distinct": str(old_distinct).lower()}, {"distinct": str(new_distinct).lower()}, "high",
        ))

    # A statement-level WHERE change is a filter change even when it never reaches a
    # lineage edge (the edge carries no filter condition for a plain SELECT).  Without
    # this dimension the difference would land in the whole-AST fallback bucket, which is
    # reserved for changes no structural dimension explains.
    old_filters = collect(old_states, "filters")
    new_filters = collect(new_states, "filters")
    if old_filters != new_filters and not any(
        item.change_category == "filter_changed" for item in items
    ):
        items.append(ChangeItemSpec(
            "filter_changed", "filter",
            {"filter": sorted(old_filters)}, {"filter": sorted(new_filters)}, "high",
        ))

    # Row limits change which records the query produces, so they always need a human
    # read.  A statement-level ORDER BY only decides presentation *unless* a limit is
    # present, where the ordering picks which rows survive: that pair is reported as
    # one row-range change instead of inventing a separate caliber fact.
    old_limits = collect(old_states, "row_limit")
    new_limits = collect(new_states, "row_limit")
    old_order = collect(old_states, "order_by")
    new_order = collect(new_states, "order_by")
    limit_changed = old_limits != new_limits
    order_changed = old_order != new_order
    if limit_changed or (order_changed and (old_limits or new_limits)):
        items.append(ChangeItemSpec(
            "top_limit_changed", "top_limit",
            {"order_by": sorted(old_order), "row_limit": sorted(old_limits)},
            {"order_by": sorted(new_order), "row_limit": sorted(new_limits)}, "high",
        ))

    # A rewrite inside a CTE keeps the outer projection text identical, so the edge
    # comparator sees nothing.  The CTE signature (name + projection + predicate)
    # attributes it to the CTE family instead of an unattributed fallback.
    old_ctes = collect(old_states, "cte_signatures")
    new_ctes = collect(new_states, "cte_signatures")
    if old_ctes != new_ctes:
        items.append(ChangeItemSpec(
            "cte_changed", "cte",
            {"cte": sorted(old_ctes)}, {"cte": sorted(new_ctes)}, "high",
        ))


def _semantic_states(result) -> list[dict]:
    """Statement semantics as plain dicts, resilient to older parse results."""

    states: list[dict] = []
    for entry in getattr(result, "statement_semantics", ()) or ():
        states.append({
            "group_by": tuple(entry.group_by or ()),
            "distinct": bool(entry.distinct),
            "union_modes": tuple(entry.union_modes or ()),
            "join_types": tuple(entry.join_types or ()),
            "having": tuple(entry.having or ()),
            "row_limit": tuple(getattr(entry, "row_limit", ()) or ()),
            "order_by": tuple(getattr(entry, "order_by", ()) or ()),
            "cte_signatures": tuple(getattr(entry, "cte_signatures", ()) or ()),
            "filters": tuple(getattr(entry, "filters", ()) or ()),
        })
    return states

def _normalize(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _deduplicate(items: list[ChangeItemSpec]) -> list[ChangeItemSpec]:
    result: dict[tuple, ChangeItemSpec] = {}
    for item in items:
        key = (item.change_category, str(item.old_value), str(item.new_value))
        result.setdefault(key, item)
    return list(result.values())


def _rank(value: str) -> int:
    return {"low": 0, "medium": 1, "high": 2, "critical": 3}[value]


def _shell_dependency_value(item) -> tuple:
    return (item.dependency_type, item.target_path or "", tuple(item.arguments), item.condition_expression or "")
