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
    if not items:
        items.append(ChangeItemSpec("transformation_changed", "script", {"normalized": old_ast}, {"normalized": new_ast}, "medium"))
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
