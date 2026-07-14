from datetime import UTC, datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import CatalogColumn, CatalogSchema, CatalogTable, DataSource, MetadataSyncTask
from app.services.metadata.factory import create_metadata_adapter
from app.services.metadata.hashing import metadata_hash

VALID_MODES = {"full", "incremental", "selected_schemas"}

def synchronize_metadata(db: Session, datasource: DataSource, sync_mode="full", schema_names=None, include_views=True, created_by=None):
    if sync_mode not in VALID_MODES: raise ValueError("Invalid sync_mode")
    task = MetadataSyncTask(project_id=datasource.project_id, datasource_id=datasource.id, sync_mode=sync_mode, status="running", started_at=datetime.now(UTC), created_by=created_by)
    db.add(task); db.commit(); db.refresh(task)
    warnings = []; adapter = create_metadata_adapter(datasource)
    try:
        schemas = adapter.list_schemas()
        if schema_names: schemas = [item for item in schemas if item.schema_name in schema_names]
        seen_tables, seen_columns = set(), set()
        for schema_meta in schemas:
            schema = _upsert_schema(db, datasource, schema_meta, datetime.now(UTC))
            try: tables = adapter.list_tables([schema.schema_name], include_views=include_views)
            except Exception as exc:
                warnings.append(f"schema {schema.schema_name} 同步失败: {exc}"); continue
            for table_meta in tables:
                try:
                    table = _upsert_table(db, datasource, schema, table_meta, datetime.now(UTC)); seen_tables.add(table.id)
                    columns = adapter.list_columns(table.schema_name, table.table_name)
                    for column_meta in columns:
                        column = _upsert_column(db, datasource, table, column_meta, datetime.now(UTC)); seen_columns.add(column.id)
                    db.commit()
                except Exception as exc:
                    db.rollback(); warnings.append(f"{table_meta.schema_name}.{table_meta.table_name} 同步失败: {exc}")
        if sync_mode == "full": _disable_missing(db, datasource.id, seen_tables, seen_columns)
        task.schema_count = len(schemas); task.table_count = len(seen_tables); task.column_count = len(seen_columns)
        task.status = "partially_completed" if warnings else "completed"; task.warnings_json = warnings
    except Exception as exc:
        db.rollback(); task = db.get(MetadataSyncTask, task.id); task.status = "failed"; task.error_message = str(exc)
    task.finished_at = datetime.now(UTC); db.commit(); db.refresh(task); return task

def _upsert_schema(db, ds, item, now):
    model = db.scalar(select(CatalogSchema).where(CatalogSchema.datasource_id == ds.id, CatalogSchema.schema_name == item.schema_name))
    if model is None: model = CatalogSchema(project_id=ds.project_id, datasource_id=ds.id, schema_name=item.schema_name); db.add(model)
    model.schema_comment = item.schema_comment; model.enabled = True; model.last_synced_at = now; db.flush(); return model

def _upsert_table(db, ds, schema, item, now):
    digest = metadata_hash(item)
    model = db.scalar(select(CatalogTable).where(CatalogTable.datasource_id == ds.id, CatalogTable.schema_name == item.schema_name, CatalogTable.table_name == item.table_name))
    if model is None:
        model = CatalogTable(project_id=ds.project_id, datasource_id=ds.id, catalog_schema_id=schema.id, schema_name=item.schema_name, table_name=item.table_name); db.add(model)
    changed = model.metadata_hash != digest
    if changed:
        model.table_comment=item.table_comment; model.table_type=item.table_type; model.estimated_row_count=item.estimated_row_count; model.primary_key_columns_json=item.primary_key_columns; model.metadata_hash=digest
    if changed or not model.enabled: model.last_synced_at=now
    model.enabled=True; db.flush(); return model

def _upsert_column(db, ds, table, item, now):
    digest = metadata_hash(item)
    model = db.scalar(select(CatalogColumn).where(CatalogColumn.catalog_table_id == table.id, CatalogColumn.column_name == item.column_name))
    if model is None:
        model = CatalogColumn(project_id=ds.project_id, datasource_id=ds.id, catalog_table_id=table.id, schema_name=item.schema_name, table_name=item.table_name, column_name=item.column_name); db.add(model)
    changed = model.metadata_hash != digest
    if changed:
        for key in ["column_comment","data_type","database_native_type","nullable","ordinal_position","is_primary_key","default_value","character_max_length","numeric_precision","numeric_scale"]: setattr(model, key, getattr(item, key))
        model.metadata_hash=digest
    if changed or not model.enabled: model.last_synced_at=now
    model.enabled=True; db.flush(); return model

def _disable_missing(db, datasource_id, seen_tables, seen_columns):
    for item in db.scalars(select(CatalogTable).where(CatalogTable.datasource_id == datasource_id)).all():
        if item.id not in seen_tables: item.enabled=False
    for item in db.scalars(select(CatalogColumn).where(CatalogColumn.datasource_id == datasource_id)).all():
        if item.id not in seen_columns: item.enabled=False
