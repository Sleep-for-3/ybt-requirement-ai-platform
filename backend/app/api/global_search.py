from collections import Counter
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import (
    LineageNode,
    MartField,
    MartTable,
    MartToYbtMapping,
    RegulatoryKnowledgeItem,
    ScenarioBusinessMapping,
    ScriptFile,
    SemanticConcept,
    SourceField,
    SourceTable,
    SourceToMartMapping,
    TargetField,
    TargetTable,
)
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService


router = APIRouter(tags=["global search"])


class GlobalSearchItem(BaseModel):
    category: str
    entity_type: str
    entity_id: int
    title: str
    subtitle: str | None = None
    href: str


class GlobalSearchResponse(BaseModel):
    query: str
    items: list[GlobalSearchItem] = Field(default_factory=list)
    category_counts: dict[str, int] = Field(default_factory=dict)


@router.get("/projects/{project_id}/global-search", response_model=GlobalSearchResponse)
def global_search(
    project_id: int,
    principal: CurrentPrincipal,
    q: str = Query(min_length=2, max_length=100),
    limit: int = Query(default=40, ge=1, le=100),
    db: Session = Depends(get_db),
) -> GlobalSearchResponse:
    permission_service = PermissionService(db, principal)
    project = permission_service.require_project_permission(project_id, "project.view")
    permissions = permission_service.effective_project_permissions(project_id)
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="Search query must contain at least 2 non-whitespace characters")
    pattern = _pattern(query)
    per_type = min(8, max(3, limit // 6))
    items: list[GlobalSearchItem] = []

    def add(category: str, entity_type: str, entity_id: int, title: str, subtitle: str | None, href: str) -> None:
        items.append(GlobalSearchItem(
            category=category,
            entity_type=entity_type,
            entity_id=entity_id,
            title=_clip(title, 180),
            subtitle=_clip(subtitle, 240) if subtitle else None,
            href=href,
        ))

    target_tables = db.scalars(select(TargetTable).where(
        TargetTable.project_id == project_id,
        _matches(pattern, TargetTable.table_code, TargetTable.table_name, TargetTable.description),
    ).order_by(TargetTable.table_code).limit(per_type)).all()
    for row in target_tables:
        add("监管目标", "target_table", row.id, row.table_name, row.table_code, f"/fields?targetTableId={row.id}")

    target_fields = db.scalars(select(TargetField).where(
        TargetField.project_id == project_id,
        _matches(pattern, TargetField.field_code, TargetField.field_name, TargetField.field_definition, TargetField.regulatory_description),
    ).order_by(TargetField.field_code).limit(per_type)).all()
    for row in target_fields:
        add("监管目标", "target_field", row.id, row.field_name, row.field_code, f"/fields/{row.id}/scenarios")

    semantic_concepts = db.scalars(select(SemanticConcept).where(
        SemanticConcept.project_id == project_id,
        or_(SemanticConcept.institution_id.is_(None), SemanticConcept.institution_id == project.institution_id),
        _matches(pattern, SemanticConcept.concept_code, SemanticConcept.concept_name, SemanticConcept.definition, SemanticConcept.description),
    ).order_by(SemanticConcept.concept_name).limit(per_type)).all()
    for row in semantic_concepts:
        add("监管语义", "semantic_concept", row.id, row.concept_name, f"{row.concept_code} · {row.status}", f"/semantics/{row.id}")

    can_search_catalog = bool({"catalog.search", "catalog.manage", "technical.edit", "technical.review"} & permissions)
    if can_search_catalog:
        for row in db.scalars(select(SourceTable).where(SourceTable.project_id == project_id, _matches(pattern, SourceTable.table_code, SourceTable.table_name, SourceTable.table_comment, SourceTable.description)).order_by(SourceTable.table_code).limit(per_type)).all():
            add("来源数据", "source_table", row.id, row.table_name, row.table_code, f"/catalog?sourceTableId={row.id}")
        for row in db.scalars(select(SourceField).where(SourceField.project_id == project_id, _matches(pattern, SourceField.field_code, SourceField.field_name, SourceField.field_comment, SourceField.description)).order_by(SourceField.field_code).limit(per_type)).all():
            add("来源数据", "source_field", row.id, row.field_name, row.field_code, f"/catalog?sourceFieldId={row.id}")
        for row in db.scalars(select(MartTable).where(MartTable.project_id == project_id, _matches(pattern, MartTable.table_code, MartTable.table_name, MartTable.table_comment, MartTable.description)).order_by(MartTable.table_code).limit(per_type)).all():
            add("监管集市", "mart_table", row.id, row.table_name, row.table_code, f"/mart?martTableId={row.id}")
        for row in db.scalars(select(MartField).where(MartField.project_id == project_id, _matches(pattern, MartField.field_code, MartField.field_name, MartField.field_comment, MartField.description)).order_by(MartField.field_code).limit(per_type)).all():
            add("监管集市", "mart_field", row.id, row.field_name, row.field_code, f"/mart?martTableId={row.mart_table_id}&martFieldId={row.id}")

    can_search_mappings = bool({"technical.edit", "technical.review", "project.manage"} & permissions)
    if can_search_mappings:
        requirement_rows = db.execute(select(ScenarioBusinessMapping, TargetField).join(TargetField, TargetField.id == ScenarioBusinessMapping.target_field_id).where(
            ScenarioBusinessMapping.project_id == project_id,
            _matches(pattern, TargetField.field_code, TargetField.field_name, ScenarioBusinessMapping.business_definition, ScenarioBusinessMapping.final_content),
        ).order_by(TargetField.field_code).limit(per_type)).all()
        for row, field in requirement_rows:
            add("需求与映射", "requirement", row.id, field.field_name, f"业务口径 · {row.business_confirm_status}", f"/fields/{field.id}/scenarios")

        mart_mapping_rows = db.execute(select(MartToYbtMapping, TargetField).join(TargetField, TargetField.id == MartToYbtMapping.target_field_id).where(
            MartToYbtMapping.project_id == project_id,
            _matches(pattern, TargetField.field_code, TargetField.field_name, MartToYbtMapping.mapping_name, MartToYbtMapping.final_content),
        ).order_by(TargetField.field_code).limit(per_type)).all()
        for row, field in mart_mapping_rows:
            add("需求与映射", "mart_to_ybt_mapping", row.id, row.mapping_name or field.field_name, f"集市到目标 · {row.mapping_status}", f"/fields/{field.id}/scenarios")

        for row in db.scalars(select(SourceToMartMapping).where(
            SourceToMartMapping.project_id == project_id,
            _matches(pattern, SourceToMartMapping.mapping_name, SourceToMartMapping.source_system_summary, SourceToMartMapping.source_tables_summary, SourceToMartMapping.source_fields_summary, SourceToMartMapping.final_content),
        ).order_by(SourceToMartMapping.id.desc()).limit(per_type)).all():
            add("需求与映射", "source_to_mart_mapping", row.id, row.mapping_name or f"来源到集市映射 #{row.id}", row.mapping_status, f"/mart?sourceToMartMappingId={row.id}")

    if {"knowledge.search", "knowledge.manage"} & permissions:
        for row in db.scalars(select(RegulatoryKnowledgeItem).where(
            RegulatoryKnowledgeItem.project_id == project_id,
            _matches(pattern, RegulatoryKnowledgeItem.target_table_code, RegulatoryKnowledgeItem.target_field_code, RegulatoryKnowledgeItem.target_field_name, RegulatoryKnowledgeItem.question_text, RegulatoryKnowledgeItem.answer_text, RegulatoryKnowledgeItem.source_document_name),
        ).order_by(RegulatoryKnowledgeItem.id.desc()).limit(per_type)).all():
            title = row.target_field_name or row.question_text or row.source_document_name or f"知识条目 #{row.id}"
            add("知识与证据", "knowledge", row.id, title, row.knowledge_type, f"/knowledge/search?q={quote(query, safe='')}")

    if "lineage.view" in permissions:
        for row in db.scalars(select(ScriptFile).where(ScriptFile.project_id == project_id, _matches(pattern, ScriptFile.file_name, ScriptFile.relative_path, ScriptFile.logical_target_name)).order_by(ScriptFile.file_name).limit(per_type)).all():
            add("技术血缘", "script_file", row.id, row.file_name, row.relative_path, f"/lineage/scripts/{row.id}")
        for row in db.scalars(select(LineageNode).where(LineageNode.project_id == project_id, _matches(pattern, LineageNode.logical_name, LineageNode.database_name, LineageNode.schema_name, LineageNode.table_name, LineageNode.column_name)).order_by(LineageNode.logical_name).limit(per_type)).all():
            add("技术血缘", "lineage_node", row.id, row.logical_name, row.node_type, f"/lineage?node_id={row.id}")

    normalized = query.casefold()
    items.sort(key=lambda item: (_rank(item, normalized), item.category, item.title.casefold(), item.entity_id))
    returned = items[:limit]
    return GlobalSearchResponse(
        query=query,
        items=returned,
        category_counts=dict(Counter(item.category for item in returned)),
    )


def _pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _matches(pattern: str, *columns):
    return or_(*(column.ilike(pattern, escape="\\") for column in columns))


def _clip(value: str, limit: int) -> str:
    normalized = " ".join(str(value).split())
    return normalized if len(normalized) <= limit else f"{normalized[:limit - 1]}…"


def _rank(item: GlobalSearchItem, query: str) -> int:
    title = item.title.casefold()
    subtitle = (item.subtitle or "").casefold()
    if title == query:
        return 0
    if title.startswith(query):
        return 1
    if query in title:
        return 2
    if query in subtitle:
        return 3
    return 4
