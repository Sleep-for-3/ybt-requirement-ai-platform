from datetime import UTC, datetime
from difflib import SequenceMatcher
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import CatalogColumn, CatalogSchema, CatalogTable, DataSource, MetadataDriftEvent, MetadataSyncTask
from app.services.metadata.factory import create_metadata_adapter
from app.services.metadata.hashing import metadata_hash
from app.services.datasource_service import ensure_readonly_datasource

VALID_MODES = {"full", "incremental", "selected_schemas"}

def synchronize_metadata(db: Session, datasource: DataSource, sync_mode="full", schema_names=None, include_views=True, created_by=None):
    ensure_readonly_datasource(datasource)
    if sync_mode not in VALID_MODES: raise ValueError("Invalid sync_mode")
    task = MetadataSyncTask(project_id=datasource.project_id, datasource_id=datasource.id, sync_mode=sync_mode, status="pending", created_by=created_by)
    db.add(task); db.commit(); db.refresh(task)
    task.status="running";task.started_at=datetime.now(UTC);db.commit()
    warnings = []; adapter = create_metadata_adapter(datasource)
    try:
        schemas = adapter.list_schemas()
        if schema_names: schemas = [item for item in schemas if item.schema_name in schema_names]
        seen_tables, seen_columns = set(), set();failed_schemas=set();failed_tables=set()
        for schema_meta in schemas:
            schema = _upsert_schema(db, datasource, schema_meta, datetime.now(UTC))
            try: tables = adapter.list_tables([schema.schema_name], include_views=include_views)
            except Exception as exc:
                failed_schemas.add(schema.schema_name);warnings.append(f"schema {schema.schema_name} 同步失败: {exc}"); continue
            for table_meta in tables:
                try:
                    table = _upsert_table(db, datasource, schema, table_meta, datetime.now(UTC), task)
                    columns = adapter.list_columns(table.schema_name, table.table_name)
                    for column_meta in columns:
                        column = _upsert_column(db, datasource, table, column_meta, datetime.now(UTC), task); seen_columns.add(column.id)
                    db.commit();seen_tables.add(table.id)
                except Exception as exc:
                    db.rollback();failed_tables.add((table_meta.schema_name,table_meta.table_name));warnings.append(f"{table_meta.schema_name}.{table_meta.table_name} 同步失败: {exc}")
        if sync_mode == "full": _disable_missing(db, datasource, task, seen_tables, seen_columns, failed_schemas, failed_tables)
        _link_rename_candidates(db, task.id)
        task.schema_count = len(schemas); task.table_count = len(seen_tables); task.column_count = len(seen_columns)
        task.status = "partially_completed" if warnings else "completed"; task.warnings_json = warnings
    except Exception as exc:
        db.rollback(); task = db.get(MetadataSyncTask, task.id); task.status = "failed"; task.error_message = str(exc)
    finally:
        close=getattr(adapter,"close",None)
        if close:close()
    task.finished_at = datetime.now(UTC); db.commit(); db.refresh(task); return task

def _upsert_schema(db, ds, item, now):
    model = db.scalar(select(CatalogSchema).where(CatalogSchema.datasource_id == ds.id, CatalogSchema.schema_name == item.schema_name))
    if model is None: model = CatalogSchema(project_id=ds.project_id, datasource_id=ds.id, schema_name=item.schema_name); db.add(model)
    model.schema_comment = item.schema_comment; model.enabled = True; model.last_synced_at = now; db.flush(); return model

def _upsert_table(db, ds, schema, item, now, task):
    digest = metadata_hash(item)
    model = db.scalar(select(CatalogTable).where(CatalogTable.datasource_id == ds.id, CatalogTable.schema_name == item.schema_name, CatalogTable.table_name == item.table_name))
    is_new = model is None
    previous = {} if is_new else _table_snapshot(model)
    was_enabled = False if is_new else model.enabled
    if is_new:
        model = CatalogTable(project_id=ds.project_id, datasource_id=ds.id, catalog_schema_id=schema.id, database_name=ds.database_name, schema_name=item.schema_name, table_name=item.table_name); db.add(model)
    model.database_name=ds.database_name
    changed = model.metadata_hash != digest
    if changed:
        model.table_comment=item.table_comment; model.table_type=item.table_type; model.estimated_row_count=item.estimated_row_count; model.primary_key_columns_json=item.primary_key_columns; model.metadata_hash=digest
    if changed or not model.enabled: model.last_synced_at=now
    model.enabled=True; db.flush()
    if is_new or not was_enabled or changed:
        current = _table_snapshot(model)
        _record_drift(db, ds, task, "table", model.schema_name, model.table_name, None, "added" if is_new or not was_enabled else "modified", previous, current)
    return model

def _upsert_column(db, ds, table, item, now, task):
    digest = metadata_hash(item)
    model = db.scalar(select(CatalogColumn).where(CatalogColumn.catalog_table_id == table.id, CatalogColumn.column_name == item.column_name))
    is_new = model is None
    previous = {} if is_new else _column_snapshot(model)
    was_enabled = False if is_new else model.enabled
    if is_new:
        model = CatalogColumn(project_id=ds.project_id, datasource_id=ds.id, catalog_table_id=table.id, database_name=ds.database_name, schema_name=item.schema_name, table_name=item.table_name, column_name=item.column_name); db.add(model)
    model.database_name=ds.database_name
    changed = model.metadata_hash != digest
    if changed:
        for key in ["column_comment","data_type","database_native_type","nullable","ordinal_position","is_primary_key","default_value","character_max_length","numeric_precision","numeric_scale"]: setattr(model, key, getattr(item, key))
        model.metadata_hash=digest
    if changed or not model.enabled: model.last_synced_at=now
    model.enabled=True; db.flush()
    if is_new or not was_enabled or changed:
        current = _column_snapshot(model)
        _record_drift(db, ds, task, "column", model.schema_name, model.table_name, model.column_name, "added" if is_new or not was_enabled else "modified", previous, current)
    return model

def _disable_missing(db, datasource, task, seen_tables, seen_columns, failed_schemas, failed_tables):
    for item in db.scalars(select(CatalogTable).where(CatalogTable.datasource_id == datasource.id)).all():
        if item.schema_name in failed_schemas or (item.schema_name,item.table_name) in failed_tables:continue
        if item.id not in seen_tables and item.enabled:
            previous = _table_snapshot(item); item.enabled=False
            _record_drift(db, datasource, task, "table", item.schema_name, item.table_name, None, "removed", previous, {})
    for item in db.scalars(select(CatalogColumn).where(CatalogColumn.datasource_id == datasource.id)).all():
        if item.schema_name in failed_schemas or (item.schema_name,item.table_name) in failed_tables:continue
        if item.id not in seen_columns and item.enabled:
            previous = _column_snapshot(item); item.enabled=False
            _record_drift(db, datasource, task, "column", item.schema_name, item.table_name, item.column_name, "removed", previous, {})


TABLE_ATTRIBUTES = ("table_comment", "table_type", "estimated_row_count", "primary_key_columns_json")
COLUMN_ATTRIBUTES = ("column_comment", "data_type", "database_native_type", "nullable", "ordinal_position", "is_primary_key", "default_value", "character_max_length", "numeric_precision", "numeric_scale")


def _table_snapshot(item):
    return {key: getattr(item, key) for key in TABLE_ATTRIBUTES}


def _column_snapshot(item):
    return {key: getattr(item, key) for key in COLUMN_ATTRIBUTES}


def _record_drift(db, datasource, task, entity_type, schema_name, table_name, column_name, change_type, previous, current):
    changed = sorted(key for key in set(previous) | set(current) if previous.get(key) != current.get(key))
    entity_key = ".".join(value for value in (schema_name, table_name, column_name) if value)
    db.add(MetadataDriftEvent(
        project_id=datasource.project_id, datasource_id=datasource.id, sync_task_id=task.id,
        entity_type=entity_type, entity_key=entity_key, change_type=change_type,
        schema_name=schema_name, table_name=table_name, column_name=column_name,
        changed_attributes_json=changed, previous_snapshot_json=previous, current_snapshot_json=current,
    ))


def _link_rename_candidates(db, task_id):
    db.flush()
    events = list(db.scalars(select(MetadataDriftEvent).where(
        MetadataDriftEvent.sync_task_id == task_id,
        MetadataDriftEvent.entity_type == "column",
        MetadataDriftEvent.change_type.in_(("added", "removed")),
    )).all())
    added = [item for item in events if item.change_type == "added"]
    removed = [item for item in events if item.change_type == "removed"]
    for current in added:
        candidates = [previous for previous in removed if previous.schema_name == current.schema_name and previous.table_name == current.table_name and _column_signature(previous.previous_snapshot_json) == _column_signature(current.current_snapshot_json)]
        if not candidates: continue
        previous = max(candidates, key=lambda item: SequenceMatcher(None, item.column_name or "", current.column_name or "").ratio())
        score = SequenceMatcher(None, previous.column_name or "", current.column_name or "").ratio()
        if score < 0.55: continue
        previous.rename_candidate_key = current.entity_key
        current.rename_candidate_key = previous.entity_key


def _column_signature(snapshot):
    return tuple(snapshot.get(key) for key in ("data_type", "database_native_type", "nullable", "character_max_length", "numeric_precision", "numeric_scale"))
