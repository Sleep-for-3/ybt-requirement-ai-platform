"""Deterministic structuring of the join conditions stored on mappings.

Phase F of the lineage/requirement upgrade needs requirement documents that
state *which* tables and *which* keys are joined, not only a free-text
condition.  This module turns the join text that already exists on
``SourceToMartMapping`` and ``MartToYbtMapping`` into a structured plan.

Hard rules:

* it never invents a table, key, join type, cardinality or time alignment;
* every token that cannot be resolved inside the project is reported through
  ``unresolved_references`` so the caller can raise a reviewable gap.  The key
  deliberately avoids the word "token": the platform's recursive redaction
  policy drops any key containing a sensitive fragment such as ``token``, and
  requirement snapshots are redacted before they are hashed and persisted;
* ``structured`` is only true when every parsed clause resolved to project
  assets, so downstream consumers can treat it as a fact instead of a guess.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    CatalogColumn,
    CatalogTable,
    MartField,
    MartTable,
    SourceField,
    SourceTable,
    TargetField,
    TargetTable,
)
from app.services.asset_display import AssetDisplayResolver


_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_QUOTED = r'(?:"[^"]+"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][\w$#]*|[\u4e00-\u9fff][\w\u4e00-\u9fff]*)'
_IDENTIFIER = re.compile(rf"^{_QUOTED}(?:\s*\.\s*{_QUOTED}){{0,2}}$")
_LITERAL = re.compile(r"^(?:'[^']*'|\"[^\"]*\"|[-+]?\d+(?:\.\d+)?|\?|:\w+)$")
_OPERATORS = ("<=", ">=", "<>", "!=", "=", "<", ">")
_TEMPORAL = re.compile(
    r"(?:^|_)(?:dt|date|day|time|ts|timestamp|month|period|batch|stat|snap)(?:$|_)"
    r"|日期|时间|账期|批次|月份|年月|截止",
    re.IGNORECASE,
)
_JOIN_TYPES = (
    ("left", re.compile(r"\bleft\s+(?:outer\s+)?join\b", re.IGNORECASE)),
    ("right", re.compile(r"\bright\s+(?:outer\s+)?join\b", re.IGNORECASE)),
    ("full", re.compile(r"\bfull\s+(?:outer\s+)?join\b", re.IGNORECASE)),
    ("inner", re.compile(r"\binner\s+join\b", re.IGNORECASE)),
    ("inner", re.compile(r"\bjoin\b", re.IGNORECASE)),
)

MAX_TOKEN_TEXT = 200
MAX_CLAUSES = 40


def strip_sql_comments(value: str) -> str:
    """Remove SQL comments without touching quoted content."""

    return _LINE_COMMENT.sub(" ", _BLOCK_COMMENT.sub(" ", value))


def is_temporal_name(value: str | None) -> bool:
    """Return True when a column name looks like a date/time/period column."""

    if not value:
        return False
    return bool(_TEMPORAL.search(str(value)))


def detect_join_type(value: str | None) -> str:
    if not value:
        return "unknown"
    for name, pattern in _JOIN_TYPES:
        if pattern.search(value):
            return name
    return "unknown"


def split_top_level(text: str, keyword: str = "and") -> list[str]:
    """Split on a bare keyword at bracket depth 0, respecting quotes."""

    parts: list[str] = []
    buffer: list[str] = []
    depth = 0
    quote: str | None = None
    lowered = text.lower()
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if quote:
            buffer.append(char)
            if char == quote:
                quote = None
            index += 1
            continue
        if char in "'\"`":
            quote = char
            buffer.append(char)
            index += 1
            continue
        if char == "[":
            end = text.find("]", index)
            end = length - 1 if end == -1 else end
            buffer.append(text[index:end + 1])
            index = end + 1
            continue
        if char == "(":
            depth += 1
            buffer.append(char)
            index += 1
            continue
        if char == ")":
            depth = max(0, depth - 1)
            buffer.append(char)
            index += 1
            continue
        if depth == 0 and lowered.startswith(keyword, index):
            before = text[index - 1] if index > 0 else " "
            after_index = index + len(keyword)
            after = text[after_index] if after_index < length else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                parts.append("".join(buffer).strip())
                buffer = []
                index = after_index
                continue
        buffer.append(char)
        index += 1
    parts.append("".join(buffer).strip())
    return [part for part in parts if part]


def split_condition(clause: str) -> tuple[str, str, str] | None:
    """Return ``(left, operator, right)`` for a single comparison clause."""

    depth = 0
    quote: str | None = None
    index = 0
    while index < len(clause):
        char = clause[index]
        if quote:
            if char == quote:
                quote = None
            index += 1
            continue
        if char in "'\"`":
            quote = char
            index += 1
            continue
        if char == "[":
            end = clause.find("]", index)
            index = (len(clause) - 1 if end == -1 else end) + 1
            continue
        if char == "(":
            depth += 1
            index += 1
            continue
        if char == ")":
            depth = max(0, depth - 1)
            index += 1
            continue
        if depth == 0:
            for operator in _OPERATORS:
                if clause.startswith(operator, index):
                    left = clause[:index].strip()
                    right = clause[index + len(operator):].strip()
                    if left and right:
                        return left, operator, right
                    return None
        index += 1
    return None


def parse_side(token: str) -> dict[str, Any]:
    """Classify one side of a comparison as identifier, literal or unknown."""

    cleaned = token.strip().strip("()").strip()
    if _LITERAL.match(cleaned):
        return {"raw": cleaned, "kind": "literal", "qualifier": None, "column": None}
    if _IDENTIFIER.match(cleaned):
        parts = [part.strip().strip('"`[]') for part in re.split(r"\s*\.\s*", cleaned)]
        return {
            "raw": cleaned,
            "kind": "identifier",
            "qualifier": ".".join(part for part in parts[:-1] if part) or None,
            "column": parts[-1] or None,
        }
    return {"raw": cleaned[:MAX_TOKEN_TEXT], "kind": "unknown", "qualifier": None, "column": None}


class JoinPlanStructurer:
    """Resolve join tokens against the project's own governed assets."""

    _TABLE_SOURCES = (
        (CatalogTable, "catalog_table", ("table_name",)),
        (MartTable, "mart_table", ("physical_table_name", "table_code", "table_name")),
        (SourceTable, "source_table", ("physical_table_name", "table_code", "table_name")),
        (TargetTable, "target_table", ("physical_table_name", "table_code", "table_name")),
    )
    _COLUMN_SOURCES = (
        ("catalog_table", CatalogColumn, "catalog_table_id", ("column_name",), "catalog_column"),
        ("mart_table", MartField, "mart_table_id", ("field_code", "physical_column_name"), "mart_field"),
        ("source_table", SourceField, "source_table_id", ("field_code", "physical_column_name"), "source_field"),
        ("target_table", TargetField, "target_table_id", ("field_code",), "target_field"),
    )

    def __init__(self, db: Session, project_id: int):
        self.db = db
        self.project_id = int(project_id)
        self.display = AssetDisplayResolver(db)
        self._table_cache: dict[str, tuple[str, Any] | None] = {}
        self._column_cache: dict[tuple[str, int, str], dict[str, Any]] = {}

    # ------------------------------------------------------------------ tables
    def find_table(self, qualifier: str | None) -> tuple[str, Any] | None:
        if not qualifier:
            return None
        key = qualifier.strip().strip('"`[]').upper()
        if not key:
            return None
        if key in self._table_cache:
            return self._table_cache[key]
        candidates = [key]
        if "." in key:
            candidates.append(key.rsplit(".", 1)[-1])
        found: tuple[str, Any] | None = None
        for candidate in candidates:
            for model, entity_type, attrs in self._TABLE_SOURCES:
                clauses = [
                    func.upper(getattr(model, attr)) == candidate
                    for attr in attrs
                    if hasattr(model, attr)
                ]
                if not clauses:
                    continue
                row = self.db.scalars(
                    select(model)
                    .where(model.project_id == self.project_id, or_(*clauses))
                    .order_by(model.id)
                    .limit(1)
                ).first()
                if row is not None:
                    found = (entity_type, row)
                    break
            if found is not None:
                break
        self._table_cache[key] = found
        return found

    # ----------------------------------------------------------- column lookup
    def _lookup(self, entity_type: str, model, table_fk: str, table_id: int, attrs: tuple[str, ...], column_upper: str):
        clauses = [func.upper(getattr(model, attr)) == column_upper for attr in attrs]
        return self.db.scalars(
            select(model)
            .where(
                model.project_id == self.project_id,
                getattr(model, table_fk) == table_id,
                or_(*clauses),
            )
            .order_by(model.id)
            .limit(1)
        ).first()

    def resolve_column(self, table_ref: tuple[str, Any] | None, column: str | None) -> dict[str, Any]:
        if not column:
            return {"resolved": False, "ambiguous": False, "entity": None, "table_ref": None}
        column = str(column)
        table_key = (table_ref[0], int(table_ref[1].id)) if table_ref else ("", 0)
        cache_key = (table_key[0], table_key[1], column.upper())
        if cache_key in self._column_cache:
            return self._column_cache[cache_key]
        result = {"resolved": False, "ambiguous": False, "entity": None, "table_ref": table_ref}
        if table_ref is not None:
            table_entity_type, table_entity = table_ref
            for expected_table, model, table_fk, attrs, entity_type in self._COLUMN_SOURCES:
                if expected_table != table_entity_type:
                    continue
                row = self._lookup(entity_type, model, table_fk, int(table_entity.id), attrs, column.upper())
                if row is not None:
                    result = {"resolved": True, "ambiguous": False, "entity": (entity_type, row), "table_ref": table_ref}
                break
        else:
            matches: list[tuple[str, Any, tuple[str, Any]]] = []
            for expected_table, model, table_fk, attrs, entity_type in self._COLUMN_SOURCES:
                clauses = [func.upper(getattr(model, attr)) == column.upper() for attr in attrs]
                rows = list(self.db.scalars(
                    select(model)
                    .where(model.project_id == self.project_id, or_(*clauses))
                    .order_by(model.id)
                    .limit(2)
                ).all())
                for row in rows:
                    parent = self.db.get(
                        {"catalog_table": CatalogTable, "mart_table": MartTable, "source_table": SourceTable, "target_table": TargetTable}[expected_table],
                        int(getattr(row, table_fk)),
                    )
                    if parent is not None and int(getattr(parent, "project_id", -1)) == self.project_id:
                        matches.append((entity_type, row, (expected_table, parent)))
            if len(matches) == 1:
                entity_type, row, table = matches[0]
                result = {"resolved": True, "ambiguous": False, "entity": (entity_type, row), "table_ref": table}
            elif len(matches) > 1:
                result = {"resolved": False, "ambiguous": True, "entity": None, "table_ref": None}
        self._column_cache[cache_key] = result
        return result

    def is_primary_key(self, table_ref: tuple[str, Any] | None, entity: Any, column: str | None) -> bool | None:
        if not column or entity is None:
            return None
        if getattr(entity, "is_primary_key", None) is not None:
            return bool(getattr(entity, "is_primary_key"))
        if table_ref is None or table_ref[0] != "catalog_table":
            return None
        declared = getattr(table_ref[1], "primary_key_columns_json", None) or []
        if isinstance(declared, (list, tuple, set)):
            return any(str(item).strip().strip('"`[]').upper() == column.upper() for item in declared)
        return None

    # ------------------------------------------------------------- describing
    def _table_asset(self, table_ref: tuple[str, Any] | None) -> dict[str, Any] | None:
        if table_ref is None:
            return None
        entity_type, entity = table_ref
        return self.display.describe(entity_type, entity)

    def _side_payload(self, side: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "raw": side["raw"],
            "kind": side["kind"],
            "qualifier": side["qualifier"],
            "column": side["column"],
            "resolved": False,
            "ambiguous": False,
            "unresolved_reason": None,
            "is_time_condition": bool(side["kind"] == "identifier" and is_temporal_name(side["column"])),
            "is_primary_key": None,
            "entity_type": None,
            "entity_id": None,
            "display": None,
            "table": None,
        }
        if side["kind"] != "identifier":
            payload["unresolved_reason"] = "not_an_identifier"
            return payload
        table_ref = None
        if side["qualifier"]:
            # A qualifier that does not resolve to a project table must stay
            # unresolved: falling back to a global column match would claim a
            # join the project cannot actually prove.
            table_ref = self.find_table(side["qualifier"])
            if table_ref is None:
                payload["ambiguous"] = True
                payload["unresolved_reason"] = "qualifier_not_found"
                return payload
        resolution = self.resolve_column(table_ref, side["column"])
        if resolution["resolved"]:
            entity_type, entity = resolution["entity"]
            payload["resolved"] = True
            payload["entity_type"] = entity_type
            payload["entity_id"] = int(entity.id)
            payload["display"] = self.display.describe(entity_type, entity)
            payload["table"] = self._table_asset(resolution["table_ref"])
            payload["is_primary_key"] = self.is_primary_key(resolution["table_ref"], entity, side["column"])
        elif resolution["ambiguous"]:
            payload["ambiguous"] = True
            payload["unresolved_reason"] = "column_ambiguous"
        else:
            payload["unresolved_reason"] = "column_not_found"
        return payload

    # ---------------------------------------------------------------- public
    def structure(
        self,
        *,
        mapping_type: str,
        mapping_id: int,
        raw_condition: str | None,
        null_handling: str | None = None,
        left_hint: dict[str, Any] | None = None,
        right_hint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raw = (raw_condition or "").strip()
        plan: dict[str, Any] = {
            "mapping_type": mapping_type,
            "mapping_id": int(mapping_id),
            "raw_condition": raw or None,
            "status": "provided" if raw else "missing",
            "parse_status": "missing",
            "structured": False,
            "fully_resolved": False,
            "review_required": True,
            "join_type": "unknown",
            "cardinality": "unknown",
            "cardinality_basis": "none",
            "null_handling": null_handling or None,
            "left_entity": left_hint,
            "right_entity": right_hint,
            "left_keys": [],
            "right_keys": [],
            "key_pairs": [],
            "time_conditions": [],
            "range_conditions": [],
            "unresolved_references": [],
            "evidence_refs": [],
            "confidence_level": "low",
            "note": "未填写关联条件，不自动推断左右表、关联键和基数",
        }
        if not raw:
            return plan

        plan["join_type"] = detect_join_type(raw)
        clauses = split_top_level(strip_sql_comments(raw))[:MAX_CLAUSES]
        for clause in clauses:
            comparison = split_condition(clause)
            if comparison is None:
                plan["unresolved_references"].append(clause.strip()[:MAX_TOKEN_TEXT])
                continue
            left_raw, operator, right_raw = comparison
            left = self._side_payload(parse_side(left_raw))
            right = self._side_payload(parse_side(right_raw))
            pair = {
                "left": left,
                "right": right,
                "operator": operator,
                "resolved": bool(left["resolved"] and right["resolved"]),
            }
            if left["kind"] == "identifier" and right["kind"] == "identifier":
                if operator == "=":
                    plan["key_pairs"].append(pair)
                elif left["is_time_condition"] or right["is_time_condition"]:
                    plan["time_conditions"].append(pair)
                else:
                    plan["range_conditions"].append(pair)
                if left["is_time_condition"] or right["is_time_condition"]:
                    if pair not in plan["time_conditions"]:
                        plan["time_conditions"].append(pair)
                for side in (left, right):
                    if not side["resolved"]:
                        plan["unresolved_references"].append(side["raw"][:MAX_TOKEN_TEXT])
            else:
                plan["unresolved_references"].append(clause.strip()[:MAX_TOKEN_TEXT])

        plan["left_keys"] = [pair["left"]["column"] for pair in plan["key_pairs"] if pair["left"]["column"]]
        plan["right_keys"] = [pair["right"]["column"] for pair in plan["key_pairs"] if pair["right"]["column"]]
        plan["unresolved_references"] = list(dict.fromkeys(plan["unresolved_references"]))

        parsed_clauses = len(plan["key_pairs"]) + len(plan["range_conditions"]) + len(plan["time_conditions"])
        if not parsed_clauses:
            plan["parse_status"] = "unresolved"
        elif plan["unresolved_references"]:
            plan["parse_status"] = "partial"
        else:
            plan["parse_status"] = "structured"
        plan["structured"] = plan["parse_status"] == "structured"

        for pair in plan["key_pairs"]:
            left_pk = pair["left"]["is_primary_key"]
            right_pk = pair["right"]["is_primary_key"]
            if not left_pk and not right_pk:
                continue
            if left_pk and right_pk:
                plan["cardinality"] = "1:1"
                plan["cardinality_basis"] = "both_sides_declared"
            elif left_pk:
                plan["cardinality"] = "1:N"
                plan["cardinality_basis"] = "left_primary_key_only"
            elif right_pk:
                plan["cardinality"] = "N:1"
                plan["cardinality_basis"] = "right_primary_key_only"
            else:
                continue
            break

        resolved_pairs = [pair for pair in plan["key_pairs"] if pair["resolved"]]
        if resolved_pairs:
            first = resolved_pairs[0]
            plan["left_entity"] = first["left"]["table"] or plan["left_entity"]
            plan["right_entity"] = first["right"]["table"] or plan["right_entity"]

        plan["fully_resolved"] = bool(plan["key_pairs"]) and all(pair["resolved"] for pair in plan["key_pairs"]) and not plan["unresolved_references"]
        plan["review_required"] = not (plan["structured"] and plan["cardinality"] != "unknown")
        plan["confidence_level"] = {"structured": "high", "partial": "medium"}.get(plan["parse_status"], "low")
        plan["note"] = {
            "structured": "关联键已解析到项目内资产，可写入需求文档",
            "partial": "部分关联 token 无法在项目内解析，需人工确认后再写入需求文档",
            "unresolved": "关联条件无法解析为项目内资产，保留原文并等待人工确认",
            "missing": "未填写关联条件，不自动推断左右表、关联键和基数",
        }[plan["parse_status"]]
        return plan


__all__ = [
    "JoinPlanStructurer",
    "detect_join_type",
    "is_temporal_name",
    "parse_side",
    "split_condition",
    "split_top_level",
    "strip_sql_comments",
]
