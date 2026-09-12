"""Business-first, technical-preserving asset display contracts.

This module is deliberately a projection layer.  It does not rename physical
columns or create a second asset catalog; it turns the existing governed
entities into one stable DTO for APIs, exports and UI consumers.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    CatalogColumn,
    CatalogTable,
    LineageNode,
    MartField,
    MartTable,
    SourceField,
    SourceTable,
    TargetField,
    TargetTable,
)


ENTITY_MODELS: dict[str, type[Any]] = {
    "target_table": TargetTable,
    "target_field": TargetField,
    "mart_table": MartTable,
    "mart_field": MartField,
    "source_table": SourceTable,
    "source_field": SourceField,
    "catalog_table": CatalogTable,
    "catalog_column": CatalogColumn,
}

LAYER_NAMES = {
    "SOURCE": "源系统",
    "ODS": "操作数据层",
    "DWD": "明细数据层",
    "DWS": "汇总数据层",
    "MART": "监管集市",
    "TARGET": "监管输出",
    "CATALOG": "数据目录",
    "SCRIPT": "处理脚本",
    "UNKNOWN": "未识别层级",
}

_MAX_TEXT = 500


def _text(value: Any, *, limit: int = _MAX_TEXT) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result[:limit] if result else None


def _first(values: Iterable[Any]) -> tuple[str | None, int | None]:
    for index, value in enumerate(values):
        cleaned = _text(value)
        if cleaned:
            return cleaned, index
    return None, None


def _metadata_value(metadata: Any, *keys: str) -> Any:
    if not isinstance(metadata, dict):
        return None
    for key in keys:
        if metadata.get(key) not in (None, "", []):
            return metadata[key]
    return None


def _aliases(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item for item in (_text(part) for part in value.split(",")) if item]
    if isinstance(value, (list, tuple, set)):
        return [item for item in (_text(part) for part in value) if item]
    return []


def _qualified(*parts: Any) -> str | None:
    values = [item for item in (_text(part, limit=255) for part in parts) if item]
    return ".".join(values) if values else None


def _table_technical(table: Any | None, fallback: Any = None) -> Any:
    if table is None:
        return fallback
    return getattr(table, "physical_table_name", None) or getattr(table, "table_code", None) or getattr(table, "table_name", None) or fallback


def _layer_for(entity_type: str, entity: Any | None = None, metadata: dict[str, Any] | None = None) -> tuple[str, str]:
    metadata = metadata or {}
    explicit = _text(_metadata_value(metadata, "layer_code", "layer"))
    if explicit:
        code = explicit.upper()
    elif entity_type.startswith("source_"):
        code = _text(_metadata_value(metadata, "source_layer", "layer_code")) or "SOURCE"
        code = code.upper()
    elif entity_type.startswith("mart_"):
        code = "MART"
    elif entity_type.startswith("target_"):
        code = "TARGET"
    elif entity_type.startswith("catalog_"):
        code = "CATALOG"
    elif entity_type == "lineage":
        code = "UNKNOWN"
    else:
        code = "UNKNOWN"
    return code, LAYER_NAMES.get(code, code)


class AssetDisplayResolver:
    """Resolve existing entities into a business-first display DTO."""

    def __init__(self, db: Session):
        self.db = db
        # A graph response can resolve the same canonical entity from many
        # nodes.  Keep the cache scoped to this request/service instance so we
        # avoid an N+1 query pattern without allowing stale process-global
        # metadata to leak between requests.
        self._cache: dict[tuple[str, int, int | None], dict[str, Any] | None] = {}

    def resolve(self, entity_type: str, entity_id: int, *, project_id: int | None = None) -> dict[str, Any] | None:
        key = (entity_type, int(entity_id), int(project_id) if project_id is not None else None)
        if key in self._cache:
            return self._cache[key]
        model = ENTITY_MODELS.get(entity_type)
        if model is None:
            self._cache[key] = None
            return None
        entity = self.db.get(model, int(entity_id))
        if entity is None:
            self._cache[key] = None
            return None
        if project_id is not None and int(getattr(entity, "project_id", -1)) != int(project_id):
            self._cache[key] = None
            return None
        result = self.describe(entity_type, entity)
        self._cache[key] = result
        return result

    def resolve_many(self, refs: Iterable[tuple[str, int]], *, project_id: int | None = None) -> list[dict[str, Any]]:
        result = []
        for entity_type, entity_id in refs:
            item = self.resolve(entity_type, entity_id, project_id=project_id)
            if item is not None:
                result.append(item)
        return result

    def describe(self, entity_type: str, entity: Any) -> dict[str, Any]:
        metadata = entity.metadata_json if isinstance(getattr(entity, "metadata_json", None), dict) else {}
        parent = None
        system_name = _text(_metadata_value(metadata, "system_name", "business_system_name"))

        if isinstance(entity, TargetField):
            business_name = _text(_metadata_value(metadata, "confirmed_business_name", "business_name", "display_name")) or _text(entity.field_name)
            comment = _first((entity.regulatory_refined_definition, entity.regulatory_description, entity.remarks, entity.field_definition))[0]
            aliases = _aliases(_metadata_value(metadata, "aliases", "business_aliases"))
            aliases.extend(item for item in (_text(entity.report_field_name),) if item and item not in aliases)
            technical = _text(entity.field_code)
            parent = self.db.get(TargetTable, entity.target_table_id)
            table_code = getattr(parent, "table_code", None) if parent else entity.target_table_id
            qualified = _qualified(table_code, technical)
            description = _text(entity.internal_definition)
            layer_code, layer_name = _layer_for(entity_type, entity, metadata)
        elif isinstance(entity, MartField):
            business_name = _text(_metadata_value(metadata, "confirmed_business_name", "business_name", "display_name")) or _text(entity.field_name)
            comment = _first((entity.field_comment, entity.description))[0]
            aliases = _aliases(_metadata_value(metadata, "aliases", "business_aliases"))
            technical = _text(entity.physical_column_name) or _text(entity.field_code)
            parent = self.db.get(MartTable, entity.mart_table_id)
            qualified = _qualified(
                getattr(parent, "database_name", None) if parent else None,
                getattr(parent, "schema_name", None) if parent else None,
                _table_technical(parent, entity.mart_table_id),
                technical,
            )
            description = _text(entity.description)
            layer_code, layer_name = _layer_for(entity_type, entity, metadata)
        elif isinstance(entity, SourceField):
            business_name = _text(_metadata_value(metadata, "confirmed_business_name", "business_name", "display_name")) or _text(entity.field_name)
            comment = _first((entity.field_comment, entity.description))[0]
            aliases = _aliases(_metadata_value(metadata, "aliases", "business_aliases"))
            technical = _text(entity.physical_column_name) or _text(entity.field_code)
            parent = self.db.get(SourceTable, entity.source_table_id)
            from app.models import BusinessSystem
            system = self.db.get(BusinessSystem, parent.business_system_id) if parent and getattr(parent, "business_system_id", None) else None
            system_name = system_name or _text(getattr(system, "system_name", None))
            qualified = _qualified(
                getattr(parent, "database_name", None) if parent else None,
                getattr(parent, "schema_name", None) if parent else None,
                _table_technical(parent, entity.source_table_id),
                technical,
            )
            description = _text(entity.description)
            layer_code, layer_name = _layer_for(entity_type, entity, metadata)
        elif isinstance(entity, CatalogColumn):
            business_name = _text(_metadata_value(metadata, "confirmed_business_name", "business_name", "display_name"))
            comment = _text(entity.column_comment)
            aliases = _aliases(_metadata_value(metadata, "aliases", "business_aliases"))
            technical = _text(entity.column_name)
            parent = self.db.get(CatalogTable, entity.catalog_table_id)
            qualified = _qualified(entity.database_name, entity.schema_name, entity.table_name, technical)
            description = None
            layer_code, layer_name = _layer_for(entity_type, entity, metadata)
        elif isinstance(entity, (TargetTable, MartTable, SourceTable, CatalogTable)):
            business_name = _text(_metadata_value(metadata, "confirmed_business_name", "business_name", "display_name")) or _text(getattr(entity, "table_name", None))
            comment = _first((getattr(entity, "table_comment", None), getattr(entity, "description", None)))[0]
            aliases = _aliases(_metadata_value(metadata, "aliases", "business_aliases"))
            technical = _text(getattr(entity, "physical_table_name", None)) or _text(getattr(entity, "table_code", None)) or _text(getattr(entity, "table_name", None))
            qualified = _qualified(
                getattr(entity, "database_name", None),
                getattr(entity, "schema_name", None),
                technical,
            )
            description = _text(getattr(entity, "description", None))
            layer_code, layer_name = _layer_for(entity_type, entity, metadata)
            if isinstance(entity, SourceTable) and getattr(entity, "business_system_id", None):
                from app.models import BusinessSystem
                system = self.db.get(BusinessSystem, entity.business_system_id)
                system_name = system_name or _text(getattr(system, "system_name", None))
        else:
            return self._fallback(entity_type, entity)

        confirmed = _text(_metadata_value(metadata, "confirmed_business_name", "confirmed_display_name"))
        candidates: list[tuple[str, str | None]] = [
            ("confirmed_business_name", confirmed),
            ("business_name", business_name),
            ("comment", comment),
        ]
        candidates.extend(("alias", alias) for alias in aliases)
        candidates.extend((("description", description), ("technical_name", technical)))
        source, selected = next(((name, value) for name, value in candidates if value), ("missing", None))
        if selected is None:
            selected = "缺少业务备注"
        quality = "confirmed" if source == "confirmed_business_name" else "available" if source != "technical_name" and source != "missing" else "missing"
        entity_id = int(entity.id)
        return {
            "id": entity_id,
            "canonical_entity_id": entity_id,
            "entity_type": entity_type,
            "display_name": selected,
            "business_name": business_name,
            "comment": comment,
            "aliases": aliases,
            "description": description,
            "technical_name": technical,
            "technical_identifier": qualified or technical,
            "qualified_technical_name": qualified or technical,
            "display_name_source": source,
            "label_quality": quality,
            "layer_code": layer_code,
            "layer_name": layer_name,
            "system_name": system_name,
        }

    def describe_lineage_node(self, node: LineageNode) -> dict[str, Any]:
        candidates = (
            ("target_field", node.target_field_id),
            ("mart_field", node.mart_field_id),
            ("source_field", node.source_field_id),
            ("catalog_column", node.catalog_column_id),
            ("target_table", getattr(node, "target_table_id", None)),
            ("mart_table", getattr(node, "mart_table_id", None)),
            ("source_table", getattr(node, "source_table_id", None)),
            ("catalog_table", node.catalog_table_id),
        )
        for entity_type, entity_id in candidates:
            if entity_id is None:
                continue
            resolved = self.resolve(entity_type, int(entity_id), project_id=node.project_id)
            if resolved is not None:
                return resolved
        metadata = node.metadata_json if isinstance(node.metadata_json, dict) else {}
        layer_code, layer_name = _layer_for("lineage", node, metadata)
        technical = _qualified(node.database_name, node.schema_name, node.table_name, node.column_name) or _text(node.logical_name)
        display = _text(_metadata_value(metadata, "confirmed_business_name", "business_name", "display_name", "label"))
        comment = _text(_metadata_value(metadata, "comment", "description", "field_comment"))
        selected, index = _first((display, comment, technical))
        source = ("business_name", "comment", "technical_name")[index] if index is not None else "missing"
        return {
            "id": int(node.id),
            "canonical_entity_id": None,
            "entity_type": "lineage",
            "display_name": selected or "缺少业务备注",
            "business_name": display,
            "comment": comment,
            "aliases": _aliases(_metadata_value(metadata, "aliases", "business_aliases")),
            "description": comment,
            "technical_name": _text(node.column_name) or _text(node.logical_name),
            "technical_identifier": technical,
            "qualified_technical_name": technical,
            "display_name_source": source,
            "label_quality": "available" if source != "technical_name" else "missing",
            "layer_code": layer_code,
            "layer_name": layer_name,
            "system_name": _text(_metadata_value(metadata, "system_name", "business_system_name")),
        }

    @staticmethod
    def _fallback(entity_type: str, entity: Any) -> dict[str, Any]:
        technical = _text(getattr(entity, "logical_name", None) or getattr(entity, "name", None))
        return {
            "id": int(entity.id),
            "canonical_entity_id": int(entity.id),
            "entity_type": entity_type,
            "display_name": technical or "缺少业务备注",
            "business_name": None,
            "comment": None,
            "aliases": [],
            "description": None,
            "technical_name": technical,
            "technical_identifier": technical,
            "qualified_technical_name": technical,
            "display_name_source": "technical_name" if technical else "missing",
            "label_quality": "missing",
            "layer_code": "UNKNOWN",
            "layer_name": LAYER_NAMES["UNKNOWN"],
            "system_name": None,
        }


def describe_asset(db: Session, entity_type: str, entity: Any) -> dict[str, Any]:
    """Convenience wrapper for callers that already loaded an entity."""
    return AssetDisplayResolver(db).describe(entity_type, entity)


__all__ = ["AssetDisplayResolver", "ENTITY_MODELS", "LAYER_NAMES", "describe_asset"]
