import hashlib
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update

from app.core.settings import get_settings
from app.models import (
    BusinessSystem,
    CatalogColumn,
    CatalogTable,
    EmbeddingRecord,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeEntityLink,
    KnowledgeIngestionTask,
    KnowledgeKeywordIndex,
    KnowledgeUnit,
    MartField,
    MartTable,
    ProductScenario,
    SourceField,
    SourceTable,
    TargetField,
    TargetTable,
)
from app.services.embeddings import get_embedding_service
from app.services.embeddings.observability import (
    embed_with_observability,
    ensure_embedding_external_allowed,
)
from app.services.retrieval.keyword_index import weighted_tokens
from app.services.storage import get_storage_service
from app.services.vector import get_vector_store
from app.services.vector.knowledge_record import build_knowledge_vector_record

from .normalizer import normalize_content
from .parsers import parse_document


ProgressCallback = Callable[[int, int], None]


async def ingest_knowledge_document(
    db,
    project_id,
    upload,
    knowledge_type,
    knowledge_scope="project",
    institution_name=None,
    confidentiality_level="internal",
    created_by=None,
    change_note=None,
    *,
    batch_size: int | None = None,
    progress: ProgressCallback | None = None,
):
    """Parse and index a document without holding one database transaction for the whole file."""
    configured_batch_size = batch_size or get_settings().knowledge_ingestion_batch_size
    if configured_batch_size < 1:
        raise ValueError("Knowledge ingestion batch size must be positive")

    content = await upload.read()
    settings = get_settings()
    formal_versioned_index = settings.vector_store_provider == "milvus"
    embedding = None if formal_versioned_index else get_embedding_service()
    if embedding is not None:
        ensure_embedding_external_allowed(
            db,
            project_id,
            embedding,
            [confidentiality_level],
            persist_denial=True,
        )
    file_name = upload.filename or "knowledge.txt"
    digest = hashlib.sha256(content).hexdigest()
    document = db.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.project_id == project_id,
            KnowledgeDocument.file_name == file_name,
            KnowledgeDocument.knowledge_type == knowledge_type,
            KnowledgeDocument.knowledge_scope == knowledge_scope,
            KnowledgeDocument.institution_name == institution_name,
            KnowledgeDocument.document_status != "archived",
        )
    )
    if (
        document
        and document.file_hash == digest
        and document.document_status in {
            "indexed",
            "partially_indexed",
            "parsed",
            "parsed_with_warnings",
        }
    ):
        return document

    storage_key = get_storage_service().save(
        content,
        file_name=file_name,
        project_id=project_id,
    ).storage_key
    if document is None:
        document = KnowledgeDocument(
            project_id=project_id,
            file_name=file_name,
            file_type=Path(file_name).suffix.lstrip("."),
            source_type=knowledge_type,
            storage_path=storage_key,
            knowledge_type=knowledge_type,
            knowledge_scope=knowledge_scope,
            institution_name=institution_name,
            confidentiality_level=confidentiality_level,
            file_hash=digest,
            current_version_no=1,
            document_status="parsing",
            parse_status="parsing",
            created_by=created_by,
        )
        db.add(document)
        db.flush()
    else:
        document.current_version_no += 1
        document.storage_path = storage_key
        document.file_hash = digest
        document.document_status = "parsing"
        document.parse_status = "parsing"
        document.confidentiality_level = confidentiality_level
        document.error_message = None

    version = KnowledgeDocumentVersion(
        project_id=project_id,
        document_id=document.id,
        version_no=document.current_version_no,
        file_name=file_name,
        storage_path=storage_key,
        file_hash=digest,
        change_note=change_note,
        parse_status="parsing",
        created_by=created_by,
    )
    db.add(version)
    db.flush()
    task = KnowledgeIngestionTask(
        project_id=project_id,
        document_id=document.id,
        document_version_id=version.id,
        status="parsing",
        parser_name=Path(file_name).suffix.lower(),
        started_at=datetime.now(UTC),
        created_by=created_by,
    )
    db.add(task)
    db.commit()

    vector_store = None if formal_versioned_index else get_vector_store()
    new_vector_ids: list[str] = []
    try:
        drafts, warnings = parse_document(file_name, content, knowledge_type)
        total = len(drafts)
        resolver = _EntityResolver(db, project_id)
        created_count = 0
        indexed_count = 0
        seen_hashes: set[str] = set()

        for offset in range(0, total, configured_batch_size):
            draft_batch = drafts[offset : offset + configured_batch_size]
            prepared = _prepare_drafts(
                draft_batch,
                resolver,
                knowledge_scope,
                institution_name,
                knowledge_type,
            )
            candidate_hashes = {item["content_hash"] for item in prepared} - seen_hashes
            existing_hashes = set(
                db.scalars(
                    select(KnowledgeUnit.content_hash).where(
                        KnowledgeUnit.project_id == project_id,
                        KnowledgeUnit.document_id != document.id,
                        KnowledgeUnit.content_hash.in_(candidate_hashes),
                        KnowledgeUnit.enabled.is_(True),
                    )
                ).all()
            ) if candidate_hashes else set()

            units = []
            for item in prepared:
                content_hash = item["content_hash"]
                if content_hash in seen_hashes or content_hash in existing_hashes:
                    continue
                seen_hashes.add(content_hash)
                units.append(
                    _knowledge_unit(
                        item,
                        project_id=project_id,
                        document=document,
                        version=version,
                        knowledge_type=knowledge_type,
                        knowledge_scope=knowledge_scope,
                        institution_name=institution_name,
                        confidentiality_level=confidentiality_level,
                    )
                )

            if units:
                db.add_all(units)
                db.flush()
                keyword_rows = [
                    row
                    for unit in units
                    for row in _keyword_rows(unit)
                ]
                entity_links = [
                    link
                    for unit in units
                    for link in resolver.links_for(unit)
                ]
                vectors = []
                vector_records = []
                embedding_rows = []
                if embedding is not None and vector_store is not None:
                    vectors = embed_with_observability(
                        db,
                        project_id,
                        embedding,
                        [unit.content for unit in units],
                        [confidentiality_level] * len(units),
                    )
                    vector_records = [
                        build_knowledge_vector_record(unit, vector)
                        for unit, vector in zip(units, vectors, strict=True)
                    ]
                    embedding_rows = [
                        EmbeddingRecord(
                            project_id=project_id,
                            knowledge_unit_id=unit.id,
                            embedding_provider=settings.embedding_provider,
                            embedding_model=settings.embedding_model,
                            vector_store_provider=settings.vector_store_provider,
                            vector_record_id=record.id,
                            embedding_dimension=len(vector),
                            content_hash=unit.content_hash,
                            status="indexed",
                        )
                        for unit, vector, record in zip(
                            units,
                            vectors,
                            vector_records,
                            strict=True,
                        )
                    ]
                db.add_all(keyword_rows)
                db.add_all(entity_links)
                db.add_all(embedding_rows)
                if vector_store is not None:
                    vector_store.upsert(vector_records)
                new_vector_ids.extend(record.id for record in vector_records)
                created_count += len(units)
                indexed_count += len(vector_records)

            task.unit_count = created_count
            task.indexed_count = indexed_count
            db.commit()
            completed = min(offset + len(draft_batch), total)
            if progress:
                progress(completed, total)

        old_units = list(
            db.scalars(
                select(KnowledgeUnit).where(
                    KnowledgeUnit.document_id == document.id,
                    KnowledgeUnit.document_version_id != version.id,
                    KnowledgeUnit.enabled.is_(True),
                )
            ).all()
        )
        old_vector_ids = [f"knowledge-unit-{item.id}" for item in old_units]
        for item in old_units:
            item.enabled = False
        db.execute(
            update(KnowledgeUnit)
            .where(KnowledgeUnit.document_version_id == version.id)
            .values(enabled=True)
        )

        final_status = (
            ("parsed" if not warnings else "parsed_with_warnings")
            if formal_versioned_index
            else ("indexed" if not warnings else "partially_indexed")
        )
        version.parse_status = "parsed" if formal_versioned_index else "indexed"
        document.document_status = final_status
        document.parse_status = version.parse_status
        document.parse_summary_json = {
            "unit_count": created_count,
            "version_no": version.version_no,
            "semantic_index_status": "pending_reindex" if formal_versioned_index else "indexed",
        }
        document.warnings_json = warnings
        task.status = final_status
        task.unit_count = created_count
        task.indexed_count = indexed_count
        task.warnings_json = warnings
        task.finished_at = datetime.now(UTC)
        db.commit()
        if old_vector_ids and vector_store is not None:
            try:
                vector_store.delete(ids=old_vector_ids)
            except Exception as cleanup_error:
                cleanup_warning = f"旧版本向量清理失败：{cleanup_error}"[:1000]
                warnings = [*warnings, cleanup_warning]
                document.document_status = "partially_indexed"
                document.warnings_json = warnings
                task.status = "partially_indexed"
                task.warnings_json = warnings
                db.commit()
        db.refresh(document)
        if progress and total == 0:
            progress(0, 0)
        return document
    except Exception as exc:
        db.rollback()
        if new_vector_ids and vector_store is not None:
            vector_store.delete(ids=new_vector_ids)
        document = db.get(KnowledgeDocument, document.id)
        version = db.get(KnowledgeDocumentVersion, version.id)
        task = db.get(KnowledgeIngestionTask, task.id)
        document.document_status = "failed"
        document.parse_status = "failed"
        document.error_message = str(exc)[:2000]
        version.parse_status = "failed"
        task.status = "failed"
        task.failed_count = 1
        task.error_message = str(exc)[:2000]
        task.finished_at = datetime.now(UTC)
        db.commit()
        raise


def _prepare_drafts(
    drafts,
    resolver,
    knowledge_scope,
    institution_name,
    knowledge_type,
):
    prepared = []
    for draft in drafts:
        scenario_id = resolver.scenario_id(draft.scenario_name)
        normalized = normalize_content(draft.content)
        content_hash = hashlib.sha256(
            "|".join(
                [
                    knowledge_scope,
                    institution_name or "",
                    knowledge_type,
                    draft.target_field_code or "",
                    str(scenario_id or ""),
                    normalized,
                ]
            ).encode()
        ).hexdigest()
        prepared.append(
            {
                "draft": draft,
                "scenario_id": scenario_id,
                "business_system_id": resolver.business_system_id(
                    draft.metadata.get("business_system_name")
                ),
                "normalized": normalized,
                "content_hash": content_hash,
            }
        )
    return prepared


def _knowledge_unit(
    item,
    *,
    project_id,
    document,
    version,
    knowledge_type,
    knowledge_scope,
    institution_name,
    confidentiality_level,
):
    draft = item["draft"]
    return KnowledgeUnit(
        project_id=project_id,
        document_id=document.id,
        document_version_id=version.id,
        knowledge_type=knowledge_type,
        knowledge_scope=knowledge_scope,
        institution_name=institution_name,
        unit_type=draft.unit_type,
        title=draft.title,
        content=draft.content,
        normalized_content=item["normalized"],
        source_file_name=document.file_name,
        source_sheet_name=draft.source_sheet_name,
        source_page_no=draft.source_page_no,
        source_heading=draft.source_heading,
        source_cell_range=draft.source_cell_range,
        target_table_code=draft.target_table_code,
        target_field_code=draft.target_field_code,
        target_field_name=draft.target_field_name,
        scenario_id=item["scenario_id"],
        business_system_id=item["business_system_id"],
        source_table_name=draft.source_table_name,
        source_field_name=draft.source_field_name,
        mart_table_name=draft.metadata.get("mart_table_name"),
        mart_field_name=draft.metadata.get("mart_field_name"),
        tags_json=draft.tags,
        metadata_json=draft.metadata,
        confidentiality_level=confidentiality_level,
        enabled=False,
        content_hash=item["content_hash"],
    )


def _keyword_rows(unit) -> Iterable[KnowledgeKeywordIndex]:
    structured = " ".join(
        filter(
            None,
            [
                unit.target_table_code,
                unit.target_field_code,
                unit.target_field_name,
                unit.source_table_name,
                unit.source_field_name,
            ],
        )
    )
    return [
        KnowledgeKeywordIndex(
            project_id=unit.project_id,
            knowledge_unit_id=unit.id,
            token=token,
            weight=weight,
        )
        for token, weight in weighted_tokens(
            unit.title,
            unit.normalized_content,
            structured,
        ).items()
    ]


class _EntityResolver:
    def __init__(self, db, project_id):
        self.db = db
        self.project_id = project_id
        self.scenarios = _index(
            db.scalars(
                select(ProductScenario).where(ProductScenario.project_id == project_id)
            ).all(),
            "scenario_name",
        )
        systems = db.scalars(
            select(BusinessSystem).where(BusinessSystem.project_id == project_id)
        ).all()
        self.business_systems = _multi_index(systems, "system_name", "system_code")
        self.target_tables = _index(
            db.scalars(
                select(TargetTable).where(TargetTable.project_id == project_id)
            ).all(),
            "table_code",
        )
        self.target_fields = _index(
            db.scalars(
                select(TargetField).where(TargetField.project_id == project_id)
            ).all(),
            "field_code",
        )
        source_tables = db.scalars(
            select(SourceTable).where(SourceTable.project_id == project_id)
        ).all()
        self.source_tables = _multi_index(
            source_tables,
            "table_code",
            "physical_table_name",
            "table_name",
        )
        self.catalog_tables = _index(
            db.scalars(
                select(CatalogTable).where(CatalogTable.project_id == project_id)
            ).all(),
            "table_name",
        )
        source_fields = db.scalars(
            select(SourceField).where(SourceField.project_id == project_id)
        ).all()
        self.source_fields = {}
        for field in source_fields:
            for name in (
                field.field_code,
                field.physical_column_name,
                field.field_name,
            ):
                if name:
                    self.source_fields.setdefault((field.source_table_id, name), field)
                    self.source_fields.setdefault((None, name), field)
        self.catalog_columns = _index(
            db.scalars(
                select(CatalogColumn).where(CatalogColumn.project_id == project_id)
            ).all(),
            "column_name",
        )
        mart_tables = db.scalars(
            select(MartTable).where(MartTable.project_id == project_id)
        ).all()
        self.mart_tables = _multi_index(mart_tables, "table_code", "table_name")
        mart_fields = db.scalars(
            select(MartField).where(MartField.project_id == project_id)
        ).all()
        self.mart_fields = _multi_index(mart_fields, "field_code", "field_name")

    def scenario_id(self, name):
        scenario = self.scenarios.get(name)
        return scenario.id if scenario else None

    def business_system_id(self, name):
        system = self.business_systems.get(name)
        return system.id if system else None

    def links_for(self, unit) -> list[KnowledgeEntityLink]:
        links = []
        target_table = self.target_tables.get(unit.target_table_code)
        _append_link(
            links,
            unit,
            "target_table",
            target_table,
            unit.target_table_code,
            None,
            "references",
            1 if target_table else 0.7,
        )
        target_field = self.target_fields.get(unit.target_field_code)
        _append_link(
            links,
            unit,
            "target_field",
            target_field,
            unit.target_field_code,
            unit.target_field_name,
            "explains",
            1 if target_field else 0.7,
        )
        scenario = self.scenarios.get(next(
            (name for name, item in self.scenarios.items() if item.id == unit.scenario_id),
            None,
        ))
        _append_link(
            links,
            unit,
            "product_scenario",
            scenario,
            scenario.scenario_code if scenario else None,
            scenario.scenario_name if scenario else None,
            "applies_to",
            1,
        )
        system = next(
            (
                item
                for item in self.business_systems.values()
                if item.id == unit.business_system_id
            ),
            None,
        )
        _append_link(
            links,
            unit,
            "business_system",
            system,
            system.system_code if system else None,
            system.system_name if system else None,
            "references",
            1,
        )
        source_table = self.source_tables.get(unit.source_table_name)
        _append_link(
            links,
            unit,
            "source_table",
            source_table,
            unit.source_table_name,
            source_table.table_name if source_table else None,
            "historical_source",
            1 if source_table else 0.7,
        )
        catalog_table = self.catalog_tables.get(unit.source_table_name)
        _append_link(
            links,
            unit,
            "catalog_table",
            catalog_table,
            unit.source_table_name,
            catalog_table.table_comment if catalog_table else None,
            "technical_basis",
            1 if catalog_table else 0.7,
        )
        source_field = self.source_fields.get(
            (
                source_table.id if source_table else None,
                unit.source_field_name,
            )
        ) or self.source_fields.get((None, unit.source_field_name))
        _append_link(
            links,
            unit,
            "source_field",
            source_field,
            unit.source_field_name,
            source_field.field_name if source_field else None,
            "historical_source",
            1 if source_field else 0.7,
        )
        catalog_column = self.catalog_columns.get(unit.source_field_name)
        _append_link(
            links,
            unit,
            "catalog_column",
            catalog_column,
            unit.source_field_name,
            catalog_column.column_comment if catalog_column else None,
            "technical_basis",
            1 if catalog_column else 0.7,
        )
        mart_table = self.mart_tables.get(unit.mart_table_name)
        _append_link(
            links,
            unit,
            "mart_table",
            mart_table,
            unit.mart_table_name,
            mart_table.table_name if mart_table else None,
            "maps_to",
            1 if mart_table else 0.7,
        )
        mart_field = self.mart_fields.get(unit.mart_field_name)
        _append_link(
            links,
            unit,
            "mart_field",
            mart_field,
            unit.mart_field_name,
            mart_field.field_name if mart_field else None,
            "maps_to",
            1 if mart_field else 0.7,
        )
        return links


def _append_link(
    links,
    unit,
    entity_type,
    entity,
    code,
    name,
    relation,
    confidence,
):
    if not code and entity is None:
        return
    links.append(
        KnowledgeEntityLink(
            project_id=unit.project_id,
            knowledge_unit_id=unit.id,
            entity_type=entity_type,
            entity_id=entity.id if entity else None,
            entity_code=code,
            entity_name=name,
            relation_type=relation,
            confidence=confidence,
        )
    )


def _index(items, attribute):
    result = {}
    for item in items:
        value = getattr(item, attribute)
        if value:
            result.setdefault(value, item)
    return result


def _multi_index(items, *attributes):
    result = {}
    for item in items:
        for attribute in attributes:
            value = getattr(item, attribute)
            if value:
                result.setdefault(value, item)
    return result
