from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    CatalogColumn, CatalogTable, LineageNode, LineageResolutionCandidate,
    MartField, MartTable, SourceField, SourceTable, TargetField, TargetTable,
)


@dataclass(frozen=True)
class ResolutionResult:
    node: LineageNode
    candidates: tuple[LineageResolutionCandidate, ...]


def resolve_lineage_node(db: Session, node: LineageNode) -> ResolutionResult:
    """Resolve a node conservatively; ambiguity always requires a human."""

    db.query(LineageResolutionCandidate).filter(LineageResolutionCandidate.lineage_node_id == node.id).delete()
    candidate_groups = _candidate_groups(db, node)
    ambiguous: list[LineageResolutionCandidate] = []
    for candidate_type, values, attribute in candidate_groups:
        if len(values) == 1:
            setattr(node, attribute, values[0].id)
        elif len(values) > 1:
            for value in values:
                row = LineageResolutionCandidate(
                    project_id=node.project_id,
                    lineage_node_id=node.id,
                    candidate_type=candidate_type,
                    candidate_id=value.id,
                    score=_score(node, value),
                    match_reason=_match_reason(node),
                    selected_flag=False,
                )
                db.add(row)
                ambiguous.append(row)
    bound_attributes = (
        "catalog_table_id", "catalog_column_id", "source_table_id", "source_field_id",
        "mart_table_id", "mart_field_id", "target_table_id", "target_field_id",
    )
    node.unresolved_flag = bool(ambiguous) or not any(getattr(node, item) for item in bound_attributes)
    db.flush()
    return ResolutionResult(node, tuple(ambiguous))


def select_resolution_candidate(db: Session, node: LineageNode, candidate: LineageResolutionCandidate) -> LineageNode:
    if candidate.lineage_node_id != node.id or candidate.project_id != node.project_id:
        raise ValueError("Resolution candidate does not belong to this node")
    attribute = {
        "catalog_table": "catalog_table_id", "catalog_column": "catalog_column_id",
        "source_table": "source_table_id", "source_field": "source_field_id",
        "mart_table": "mart_table_id", "mart_field": "mart_field_id",
        "target_table": "target_table_id", "target_field": "target_field_id",
    }.get(candidate.candidate_type)
    if attribute is None:
        raise ValueError("Unsupported resolution candidate type")
    db.query(LineageResolutionCandidate).filter(
        LineageResolutionCandidate.lineage_node_id == node.id,
        LineageResolutionCandidate.candidate_type == candidate.candidate_type,
    ).update({LineageResolutionCandidate.selected_flag: False})
    setattr(node, attribute, candidate.candidate_id)
    candidate.selected_flag = True
    node.unresolved_flag = False
    db.flush()
    return node


def unbind_lineage_node(db: Session, node: LineageNode) -> LineageNode:
    for attribute in (
        "catalog_table_id", "catalog_column_id", "source_table_id", "source_field_id",
        "mart_table_id", "mart_field_id", "target_table_id", "target_field_id",
    ):
        setattr(node, attribute, None)
    db.query(LineageResolutionCandidate).filter(LineageResolutionCandidate.lineage_node_id == node.id).update({LineageResolutionCandidate.selected_flag: False})
    node.unresolved_flag = True
    db.flush()
    return node


def _candidate_groups(db: Session, node: LineageNode):
    table_name = (node.table_name or "").lower()
    column_name = (node.column_name or "").lower()
    schema_name = (node.schema_name or "").lower()
    if node.column_name:
        catalog = _scope(db.scalars(select(CatalogColumn).where(
            CatalogColumn.project_id == node.project_id,
            CatalogColumn.enabled.is_(True),
            func.lower(CatalogColumn.table_name) == table_name,
            func.lower(CatalogColumn.column_name) == column_name,
        )).all(), schema_name)
        source = _scope(db.scalars(select(SourceField).join(SourceTable, SourceTable.id == SourceField.source_table_id).where(
            SourceField.project_id == node.project_id,
            func.lower(func.coalesce(SourceTable.physical_table_name, SourceTable.table_code)) == table_name,
            func.lower(func.coalesce(SourceField.physical_column_name, SourceField.field_code)) == column_name,
        )).all(), schema_name, lambda item: item.source_table.schema_name)
        mart = _scope(db.scalars(select(MartField).join(MartTable, MartTable.id == MartField.mart_table_id).where(
            MartField.project_id == node.project_id,
            func.lower(func.coalesce(MartTable.physical_table_name, MartTable.table_code)) == table_name,
            func.lower(func.coalesce(MartField.physical_column_name, MartField.field_code)) == column_name,
        )).all(), schema_name, lambda item: item.mart_table.schema_name)
        target = list(db.scalars(select(TargetField).join(TargetTable, TargetTable.id == TargetField.target_table_id).where(
            TargetField.project_id == node.project_id,
            func.lower(TargetTable.table_code) == table_name,
            func.lower(TargetField.field_code) == column_name,
        )).all())
        return [
            ("catalog_column", catalog, "catalog_column_id"),
            ("source_field", source, "source_field_id"),
            ("mart_field", mart, "mart_field_id"),
            ("target_field", target, "target_field_id"),
        ]
    catalog_tables = _scope(db.scalars(select(CatalogTable).where(
        CatalogTable.project_id == node.project_id,
        CatalogTable.enabled.is_(True),
        func.lower(CatalogTable.table_name) == table_name,
    )).all(), schema_name)
    source_tables = _scope(db.scalars(select(SourceTable).where(
        SourceTable.project_id == node.project_id,
        func.lower(func.coalesce(SourceTable.physical_table_name, SourceTable.table_code)) == table_name,
    )).all(), schema_name, lambda item: item.schema_name)
    mart_tables = _scope(db.scalars(select(MartTable).where(
        MartTable.project_id == node.project_id,
        func.lower(func.coalesce(MartTable.physical_table_name, MartTable.table_code)) == table_name,
    )).all(), schema_name, lambda item: item.schema_name)
    target_tables = list(db.scalars(select(TargetTable).where(TargetTable.project_id == node.project_id, func.lower(TargetTable.table_code) == table_name)).all())
    return [
        ("catalog_table", catalog_tables, "catalog_table_id"),
        ("source_table", source_tables, "source_table_id"),
        ("mart_table", mart_tables, "mart_table_id"),
        ("target_table", target_tables, "target_table_id"),
    ]


def _scope(items, schema_name: str, schema_getter=lambda item: item.schema_name):
    values = list(items)
    if not schema_name:
        return values
    return [item for item in values if (schema_getter(item) or "").lower() == schema_name]


def _score(node: LineageNode, value) -> float:
    candidate_schema = getattr(value, "schema_name", None)
    return 0.99 if node.schema_name and candidate_schema and node.schema_name.lower() == candidate_schema.lower() else 0.9


def _match_reason(node: LineageNode) -> str:
    return "schema + table + column" if node.schema_name else "table + column; multiple candidates require manual selection"
