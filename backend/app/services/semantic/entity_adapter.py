"""Explicit, bounded projections for semantic binding targets.

The resolver must not learn the shape of every ORM entity.  This module is the
single allow-listed projection boundary: each supported target has a concrete
handler and the result is a frozen, non-ORM descriptor safe for ranking and
provenance serialization.
"""

from dataclasses import dataclass
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Project
from app.services.semantic.binding_service import ENTITY_MODELS, get_project_entity


MAX_DESCRIPTOR_TEXT = 4000
MAX_METADATA_ITEMS = 16
MAX_METADATA_VALUE = 500
MAX_SOURCE_REFS = 8


@dataclass(frozen=True)
class SemanticSourceReference:
    source_type: str
    source_id: int | None
    label: str | None = None


@dataclass(frozen=True)
class SemanticEntityDescriptor:
    entity_type: str
    entity_id: int
    project_id: int
    institution_id: int | None
    code: str | None
    name: str | None
    aliases: tuple[str, ...]
    semantic_text: str
    metadata: dict[str, object]
    source_refs: tuple[SemanticSourceReference, ...]
    text_fields: tuple[tuple[str, str], ...] = ()


def _clean(value: object | None, limit: int = MAX_METADATA_VALUE) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value[:limit] if value else None


def _texts(*fields: tuple[str, object | None]) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for name, value in fields:
        cleaned = _clean(value)
        if cleaned and (name, cleaned) not in seen:
            seen.add((name, cleaned))
            result.append((name, cleaned))
    return tuple(result)


def _semantic_text(code: str | None, name: str | None, fields: tuple[tuple[str, str], ...]) -> str:
    values = [value for value in (code, name) if value]
    values.extend(value for _, value in fields)
    return " | ".join(dict.fromkeys(values))[:MAX_DESCRIPTOR_TEXT]


def _metadata(**values: object | None) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            bounded: object = _clean(value) if isinstance(value, str) else value
        else:
            bounded = _clean(value)
        if bounded is not None:
            result[key] = bounded
        if len(result) >= MAX_METADATA_ITEMS:
            break
    return result


def _refs(entity_type: str, entity_id: int, *extra: SemanticSourceReference) -> tuple[SemanticSourceReference, ...]:
    refs = [SemanticSourceReference(entity_type, entity_id, "semantic entity"), *extra]
    return tuple(refs[:MAX_SOURCE_REFS])


def _descriptor(
    *,
    entity_type: str,
    entity: object,
    institution_id: int | None,
    code: str | None,
    name: str | None,
    aliases: tuple[str, ...] = (),
    fields: tuple[tuple[str, object | None], ...] = (),
    metadata: dict[str, object] | None = None,
    refs: tuple[SemanticSourceReference, ...] = (),
) -> SemanticEntityDescriptor:
    text_fields = _texts(*fields)
    entity_id = int(entity.id)
    return SemanticEntityDescriptor(
        entity_type=entity_type,
        entity_id=entity_id,
        project_id=int(entity.project_id),
        institution_id=institution_id,
        code=_clean(code),
        name=_clean(name),
        aliases=tuple(value for value in (_clean(item) for item in aliases) if value),
        semantic_text=_semantic_text(_clean(code), _clean(name), text_fields),
        metadata=dict(metadata or {}),
        source_refs=_refs(entity_type, entity_id, *refs),
        text_fields=text_fields,
    )


def _target_table(entity: Any, institution_id: int | None) -> SemanticEntityDescriptor:
    return _descriptor(
        entity_type="target_table", entity=entity, institution_id=institution_id,
        code=entity.table_code, name=entity.table_name,
        fields=(("description", entity.description),),
    )


def _target_field(entity: Any, institution_id: int | None) -> SemanticEntityDescriptor:
    return _descriptor(
        entity_type="target_field", entity=entity, institution_id=institution_id,
        code=entity.field_code, name=entity.field_name,
        fields=(
            ("field_definition", entity.field_definition),
            ("regulatory_description", entity.regulatory_description),
            ("regulatory_original_definition", entity.regulatory_original_definition),
            ("regulatory_refined_definition", entity.regulatory_refined_definition),
            ("east_definition", entity.east_definition),
            ("internal_definition", entity.internal_definition),
            ("remarks", entity.remarks),
        ),
        metadata=_metadata(
            target_table_id=entity.target_table_id, field_type=entity.field_type,
            data_category=entity.data_category, data_format=entity.data_format,
            report_name=entity.report_name, report_field_name=entity.report_field_name,
        ),
    )


def _mart_table(entity: Any, institution_id: int | None) -> SemanticEntityDescriptor:
    return _descriptor(
        entity_type="mart_table", entity=entity, institution_id=institution_id,
        code=entity.table_code, name=entity.table_name,
        fields=(("table_comment", entity.table_comment), ("description", entity.description), ("subject_area", entity.subject_area)),
        metadata=_metadata(
            database_name=entity.database_name, schema_name=entity.schema_name,
            physical_table_name=entity.physical_table_name, is_existing=entity.is_existing,
        ),
    )


def _mart_field(entity: Any, institution_id: int | None) -> SemanticEntityDescriptor:
    return _descriptor(
        entity_type="mart_field", entity=entity, institution_id=institution_id,
        code=entity.field_code, name=entity.field_name,
        fields=(("field_comment", entity.field_comment), ("description", entity.description)),
        metadata=_metadata(
            mart_table_id=entity.mart_table_id, field_type=entity.field_type,
            physical_column_name=entity.physical_column_name, is_existing=entity.is_existing,
        ),
    )


def _source_table(entity: Any, institution_id: int | None) -> SemanticEntityDescriptor:
    return _descriptor(
        entity_type="source_table", entity=entity, institution_id=institution_id,
        code=entity.table_code, name=entity.table_name,
        fields=(("table_comment", entity.table_comment), ("description", entity.description)),
        metadata=_metadata(
            business_system_id=entity.business_system_id, database_name=entity.database_name,
            schema_name=entity.schema_name, physical_table_name=entity.physical_table_name,
        ),
    )


def _source_field(entity: Any, institution_id: int | None) -> SemanticEntityDescriptor:
    return _descriptor(
        entity_type="source_field", entity=entity, institution_id=institution_id,
        code=entity.field_code, name=entity.field_name,
        fields=(("field_comment", entity.field_comment), ("description", entity.description)),
        metadata=_metadata(
            source_table_id=entity.source_table_id, field_type=entity.field_type,
            physical_column_name=entity.physical_column_name,
        ),
    )


def _scenario(entity: Any, institution_id: int | None) -> SemanticEntityDescriptor:
    return _descriptor(
        entity_type="scenario", entity=entity, institution_id=institution_id,
        code=entity.scenario_code, name=entity.scenario_name,
        fields=(("description", entity.description), ("business_owner", entity.business_owner), ("tech_owner", entity.tech_owner)),
        metadata=_metadata(scenario_type=entity.scenario_type, enabled=entity.enabled, sort_order=entity.sort_order),
    )


def _knowledge_unit(entity: Any, institution_id: int | None) -> SemanticEntityDescriptor:
    refs = (
        SemanticSourceReference("knowledge_document", int(entity.document_id), "source document"),
        SemanticSourceReference("knowledge_document_version", int(entity.document_version_id), "source version"),
    )
    return _descriptor(
        entity_type="knowledge_unit", entity=entity, institution_id=institution_id,
        code=entity.target_field_code or entity.target_table_code or entity.source_field_name or entity.source_table_name,
        name=entity.title or entity.target_field_name or entity.mart_field_name,
        fields=(
            ("content", entity.content), ("normalized_content", entity.normalized_content),
            ("source_heading", entity.source_heading), ("source_file_name", entity.source_file_name),
            ("source_table_name", entity.source_table_name), ("source_field_name", entity.source_field_name),
            ("mart_table_name", entity.mart_table_name), ("mart_field_name", entity.mart_field_name),
        ),
        metadata=_metadata(
            knowledge_type=entity.knowledge_type, knowledge_scope=entity.knowledge_scope,
            institution_name=entity.institution_name, target_table_code=entity.target_table_code,
            target_field_code=entity.target_field_code, target_field_name=entity.target_field_name,
            scenario_id=entity.scenario_id, confidentiality_level=entity.confidentiality_level,
            enabled=entity.enabled,
        ),
        refs=refs,
    )


def _source_to_mart_mapping(entity: Any, institution_id: int | None) -> SemanticEntityDescriptor:
    return _descriptor(
        entity_type="source_to_mart_mapping", entity=entity, institution_id=institution_id,
        code=entity.mapping_name, name=entity.source_system_summary or entity.source_tables_summary,
        fields=(
            ("business_rule", entity.business_rule), ("filter_condition", entity.filter_condition),
            ("join_condition", entity.join_condition), ("priority_rule", entity.priority_rule),
            ("merge_rule", entity.merge_rule), ("code_mapping_rule", entity.code_mapping_rule),
            ("null_handling_rule", entity.null_handling_rule), ("exception_rule", entity.exception_rule),
            ("quality_check_rule", entity.quality_check_rule), ("open_questions", entity.open_questions),
            ("final_content", entity.final_content), ("ai_generated_content", entity.ai_generated_content),
        ),
        metadata=_metadata(
            mapping_status=entity.mapping_status, mart_field_id=entity.mart_field_id,
            confidence_level=entity.confidence_level, lineage_status=entity.lineage_status,
            lineage_last_verified_at=str(entity.lineage_last_verified_at) if entity.lineage_last_verified_at else None,
            lineage_change_set_id=entity.lineage_change_set_id,
        ),
    )


def _mart_to_ybt_mapping(entity: Any, institution_id: int | None) -> SemanticEntityDescriptor:
    return _descriptor(
        entity_type="mart_to_ybt_mapping", entity=entity, institution_id=institution_id,
        code=entity.mapping_name, name=entity.mart_table_summary or entity.mart_field_summary,
        fields=(
            ("business_rule", entity.business_rule), ("filter_condition", entity.filter_condition),
            ("join_condition", entity.join_condition), ("code_mapping_rule", entity.code_mapping_rule),
            ("null_handling_rule", entity.null_handling_rule), ("reporting_condition", entity.reporting_condition),
            ("validation_rule", entity.validation_rule), ("open_questions", entity.open_questions),
            ("final_content", entity.final_content), ("ai_generated_content", entity.ai_generated_content),
        ),
        metadata=_metadata(
            mapping_status=entity.mapping_status, target_field_id=entity.target_field_id,
            mart_field_id=entity.mart_field_id, confidence_level=entity.confidence_level,
            lineage_status=entity.lineage_status,
            lineage_last_verified_at=str(entity.lineage_last_verified_at) if entity.lineage_last_verified_at else None,
            lineage_change_set_id=entity.lineage_change_set_id,
        ),
    )


def _scenario_business_mapping(entity: Any, institution_id: int | None) -> SemanticEntityDescriptor:
    return _descriptor(
        entity_type="scenario_business_mapping", entity=entity, institution_id=institution_id,
        code=f"TARGET_FIELD:{entity.target_field_id}/SCENARIO:{entity.scenario_id}",
        name=entity.business_owner,
        fields=(
            ("business_definition", entity.business_definition), ("remarks", entity.remarks),
            ("final_content", entity.final_content), ("ai_generated_content", entity.ai_generated_content),
            ("open_questions", entity.open_questions),
        ),
        metadata=_metadata(
            target_field_id=entity.target_field_id, scenario_id=entity.scenario_id,
            business_confirm_status=entity.business_confirm_status,
            confidence_level=entity.confidence_level,
        ),
    )


def _scenario_technical_lineage(entity: Any, institution_id: int | None) -> SemanticEntityDescriptor:
    return _descriptor(
        entity_type="scenario_technical_lineage", entity=entity, institution_id=institution_id,
        code=f"TARGET_FIELD:{entity.target_field_id}/SCENARIO:{entity.scenario_id}",
        name=entity.source_field_chinese_name or entity.source_field_english_name,
        fields=(
            ("source_system_name", entity.source_system_name), ("source_database_name", entity.source_database_name),
            ("source_schema_name", entity.source_schema_name), ("source_table_english_name", entity.source_table_english_name),
            ("source_table_chinese_name", entity.source_table_chinese_name),
            ("source_field_english_name", entity.source_field_english_name),
            ("source_field_chinese_name", entity.source_field_chinese_name),
            ("processing_logic", entity.processing_logic), ("remarks", entity.remarks),
            ("final_content", entity.final_content), ("ai_generated_content", entity.ai_generated_content),
            ("open_questions", entity.open_questions),
        ),
        metadata=_metadata(
            target_field_id=entity.target_field_id, scenario_id=entity.scenario_id,
            processing_logic_type=entity.processing_logic_type, tech_confirm_status=entity.tech_confirm_status,
            lineage_status=entity.lineage_status,
            lineage_last_verified_at=str(entity.lineage_last_verified_at) if entity.lineage_last_verified_at else None,
            business_mapping_id=entity.business_mapping_id, confidence_level=entity.confidence_level,
        ),
    )


_HANDLERS: dict[str, Callable[[Any, int | None], SemanticEntityDescriptor]] = {
    "target_table": _target_table,
    "target_field": _target_field,
    "mart_table": _mart_table,
    "mart_field": _mart_field,
    "source_table": _source_table,
    "source_field": _source_field,
    "scenario": _scenario,
    "knowledge_unit": _knowledge_unit,
    "source_to_mart_mapping": _source_to_mart_mapping,
    "mart_to_ybt_mapping": _mart_to_ybt_mapping,
    "scenario_business_mapping": _scenario_business_mapping,
    "scenario_technical_lineage": _scenario_technical_lineage,
}


class SemanticEntityAdapter:
    """Build a deterministic, project-scoped descriptor for one allow-listed entity."""

    @staticmethod
    def describe(db: Session, project_id: int, entity_type: str, entity_id: int) -> SemanticEntityDescriptor:
        if entity_type not in ENTITY_MODELS or entity_type not in _HANDLERS:
            raise HTTPException(status_code=400, detail="Unsupported semantic binding entity_type")
        project = db.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        entity = get_project_entity(db, project_id, entity_type, entity_id)
        descriptor = _HANDLERS[entity_type](entity, project.institution_id)
        if descriptor.project_id != project_id:
            raise HTTPException(status_code=400, detail="Semantic binding target belongs to another project")
        return descriptor


__all__ = [
    "SemanticEntityAdapter",
    "SemanticEntityDescriptor",
    "SemanticSourceReference",
]
