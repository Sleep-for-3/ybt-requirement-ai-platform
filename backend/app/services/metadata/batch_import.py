"""Durable offline previews and explicit, conservative application to Catalog."""
from copy import deepcopy
import hashlib
import json
from pathlib import PurePosixPath

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.models import (BackgroundJob, BackgroundJobItem, BusinessSystem, CatalogColumn, CatalogSchema, CatalogTable, DataSource,
    Project, ResourceImportBatch, ResourceImportItem, ScriptFile, ScriptFileVersion, StoredFile)
from app.models.data_architecture import CatalogClassification
from app.services import data_architecture
from app.services.lineage.archive_ingestion import read_safe_script_archive
from app.services.lineage.ingestion import ScriptIngestionService, reresolve_lineage_version, validate_script_path
from app.services.lineage.revisions import LineageRevisionService
from app.services.metadata.batch_parser import parse_file
from app.services.storage import get_storage_service


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def items(db, batch):
    return list(db.scalars(select(ResourceImportItem).where(ResourceImportItem.batch_id == batch.id).order_by(ResourceImportItem.id)))


def load_batch(db, project_id, batch_id):
    batch = db.get(ResourceImportBatch, batch_id)
    if batch is None or batch.project_id != project_id:
        raise HTTPException(404, "Resource not found")
    return batch


def table_key(table):
    return digest([table.get(k) or "" for k in ("database_name", "schema_name", "table_name")])


def find_tables(db, project_id, table):
    exact = list(db.scalars(select(CatalogTable).where(CatalogTable.project_id == project_id,
        CatalogTable.database_name == table["database_name"], CatalogTable.schema_name == table["schema_name"],
        CatalogTable.table_name == table["table_name"]).order_by(CatalogTable.id)))
    if exact:
        return exact
    identity = [table.get(key) for key in ("database_name", "schema_name", "table_name")]
    if not all(identity):
        return []
    # DDL dialects such as Oracle/Hive commonly fold unquoted identifiers to a
    # different case than SQL references. Fall back to a full three-part
    # case-insensitive match only when database and schema still agree.
    return list(db.scalars(select(CatalogTable).where(
        CatalogTable.project_id == project_id,
        func.lower(CatalogTable.database_name) == str(identity[0]).lower(),
        func.lower(CatalogTable.schema_name) == str(identity[1]).lower(),
        func.lower(CatalogTable.table_name) == str(identity[2]).lower(),
    ).order_by(CatalogTable.id)))


def fingerprint(db, table):
    columns = list(db.scalars(select(CatalogColumn).where(CatalogColumn.catalog_table_id == table.id).order_by(CatalogColumn.id)))
    classification = db.scalar(select(CatalogClassification).where(CatalogClassification.catalog_table_id == table.id))
    return digest({"table": [table.id, table.database_name, table.schema_name, table.table_name, table.table_comment, table.enabled],
        "columns": [[x.column_name, x.data_type, x.column_comment, x.nullable, x.is_primary_key, x.enabled] for x in columns],
        "classification": classification.assignment_json if classification else None})


def create_batch(db, project, actor_id, key, files, options, storage=None):
    if project.institution_id is None:
        raise HTTPException(409, "请先为项目关联机构，再导入受控资料")
    storage = storage or get_storage_service()
    if not files or len(files) > 100 or sum(len(data) for _, data in files) > 40 * 1024 * 1024:
        raise HTTPException(422, "每批限 100 个文件、合计 40 MB")
    request_hash = digest({"files": [(name, hashlib.sha256(data).hexdigest()) for name, data in files], "options": options})
    existing = db.scalar(select(ResourceImportBatch).where(ResourceImportBatch.project_id == project.id,
        ResourceImportBatch.idempotency_key == key))
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(409, "同一提交标识不能用于不同文件或默认设置")
        return existing
    expanded = []
    for name, data in files:
        name = validate_script_path(name)
        if name.lower().endswith(".zip"):
            # Preserve the original archive guard; never extract onto the filesystem.
            try:
                members = read_safe_script_archive(data, max_file_count=100, max_total_bytes=40 * 1024 * 1024)
            except ValueError as exc:
                raise HTTPException(422, "ZIP 安全检查未通过") from exc
            for member in members:
                if not member.file_name.lower().endswith(".sql"):
                    raise HTTPException(422, "统一导入的 ZIP 首版仅接受 SQL 文件")
                expanded.append((name + "/" + member.relative_path, member.content))
        else:
            if PurePosixPath(name).suffix.lower() not in {".sql", ".ddl", ".xlsx"}:
                raise HTTPException(422, "请选择 SQL、DDL、Excel 或 ZIP")
            expanded.append((name, data))
    if not expanded or len(expanded) > 100 or len({name for name, _ in expanded}) != len(expanded):
        raise HTTPException(422, "批次为空、文件过多或相对路径重复")
    if sum(len(data) for _, data in expanded) > 40 * 1024 * 1024:
        raise HTTPException(422, "展开后的批次超过 40 MB")
    batch = ResourceImportBatch(project_id=project.id, created_by=actor_id, idempotency_key=key,
        request_hash=request_hash, options_json=options, status="preview", version=1)
    try:
        with db.begin_nested():
            db.add(batch); db.flush()
    except IntegrityError:
        winner = db.scalar(select(ResourceImportBatch).where(ResourceImportBatch.project_id == project.id,
            ResourceImportBatch.idempotency_key == key))
        if winner is None or winner.request_hash != request_hash:
            raise HTTPException(409, "提交标识已被其他请求使用")
        return winner
    for name, data in expanded:
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(422, "单文件大小不能超过 10 MB")
        stored = db.scalar(select(StoredFile).where(StoredFile.project_id == project.id,
            StoredFile.institution_id == project.institution_id, StoredFile.content_hash == hashlib.sha256(data).hexdigest(),
            StoredFile.enabled.is_(True)))
        if stored is None:
            saved = storage.save(data, file_name=PurePosixPath(name).name, project_id=project.id)
            stored = StoredFile(project_id=project.id, institution_id=project.institution_id, storage_key=saved.storage_key,
                original_file_name=PurePosixPath(name).name, content_type="application/octet-stream", byte_size=saved.byte_size,
                content_hash=saved.content_hash, classification=project.confidentiality_level, created_by=actor_id, enabled=True)
            db.add(stored); db.flush()
        kind = options.get("file_options", {}).get(name, {}).get("kind", "auto")
        try:
            kind, parsed = parse_file(data, name, kind, options.get("dialect", ""))
        except Exception:
            # Do not expose parser exceptions which can contain uploaded content.
            parsed = {"tables": [], "warnings": ["文件解析失败，请检查编码、方言与格式"], "error": "parse_failed", "complete": False}
        db.add(ResourceImportItem(batch_id=batch.id, relative_path=name, stored_file_id=stored.id,
            file_kind=kind, parsed_json=parsed, status="preview"))
    db.flush()
    batch.preview_json = preview(db, batch)
    db.commit()
    return batch


def options_for(batch, item, table=None):
    options = batch.options_json
    result = dict(options.get("defaults", {}))
    result.update(options.get("file_options", {}).get(item.relative_path, {}))
    if table:
        result.update(options.get("table_options", {}).get(table_key(table), {}))
    return result


def preview(db, batch):
    architecture = data_architecture.get_architecture(db, project_id=batch.project_id)
    active_layers = {x["key"] for x in architecture.definition_json["layers"] if x["active"]} if architecture else set()
    assignments = [batch.options_json.get("defaults", {}), *batch.options_json.get("file_options", {}).values(),
                   *batch.options_json.get("table_options", {}).values()]
    for assignment in assignments:
        if assignment.get("layer_key") is not None and assignment["layer_key"] not in active_layers:
            raise HTTPException(422, "归属层级不存在或已停用，请先配置项目架构")
        if assignment.get("business_system_id") is not None:
            system = db.get(BusinessSystem, assignment["business_system_id"])
            if system is None or system.project_id != batch.project_id:
                raise HTTPException(404, "Resource not found")
    projected = []
    seen = {}
    for item in items(db, batch):
        settings = options_for(batch, item)
        entry = {"id": item.id, "path": item.relative_path, "kind": item.file_kind,
            "warnings": item.parsed_json.get("warnings", []), "error": item.parsed_json.get("error"),
            "complete": item.parsed_json.get("complete", False), "decision": settings.get("decision", "preserve"),
            "tables": [], "references": []}
        for raw in item.parsed_json.get("tables", []):
            table = deepcopy(raw)
            table["database_name"] = table.get("database_name") or settings.get("database_name", "")
            table["schema_name"] = table.get("schema_name") or settings.get("schema_name") or "main"
            key = table_key(table)
            table_settings = options_for(batch, item, table)
            matches = find_tables(db, batch.project_id, table)
            target_id = table_settings.get("catalog_table_id")
            if target_id:
                matches = [x for x in matches if x.id == target_id]
                if not matches:
                    raise HTTPException(422, "指定资产不属于当前项目或物理表身份不一致")
            conflicts = []
            if len(matches) > 1:
                conflicts.append("物理身份对应多个目录资产，请明确选择资产 ID")
            target = matches[0] if len(matches) == 1 else None
            if not table["database_name"]:
                conflicts.append("缺少数据库标识，请设置离线库名")
            additions = []
            fills = False
            if target:
                fills = not target.table_comment and bool(table.get("table_comment"))
                existing_columns = {x.column_name: x for x in db.scalars(select(CatalogColumn).where(CatalogColumn.catalog_table_id == target.id))}
                if target.table_comment and table.get("table_comment") and target.table_comment != table["table_comment"]:
                    conflicts.append("表注释不同，保留现有注释")
                for column in table["columns"]:
                    old = existing_columns.get(column["column_name"])
                    if old is None:
                        additions.append(column["column_name"])
                    elif any(not getattr(old, attr) and column.get(attr) for attr in ("data_type", "column_comment")):
                        fills = True
                    if old is not None and any(getattr(old, attr) not in (None, "") and column.get(attr) not in (None, "") and
                             getattr(old, attr) != column.get(attr) for attr in ("data_type", "column_comment", "nullable", "is_primary_key")):
                        conflicts.append(f"字段 {column['column_name']} 定义不同，保留现有定义")
            within_batch = seen.get(key)
            if within_batch and within_batch != digest(table):
                conflicts.append("同批次其他文件包含不同定义，应用时保留先前确认的定义")
            seen[key] = digest(table)
            operation = "conflict" if conflicts else "new" if not target else "modify" if additions or fills else "duplicate"
            entry["tables"].append({"key": key, "metadata": table, "operation": operation, "conflicts": conflicts,
                "existing_ids": [x.id for x in matches], "catalog_table_id": target.id if target else None,
                "before_hash": fingerprint(db, target) if target else None,
                "layer_key": table_settings.get("layer_key"), "business_system_id": table_settings.get("business_system_id"),
                "decision": table_settings.get("decision", "preserve")})
        if item.file_kind == "sql":
            existing = db.scalar(select(ScriptFile).where(ScriptFile.project_id == batch.project_id,
                ScriptFile.code_repository_id.is_(None), ScriptFile.relative_path == item.relative_path))
            entry["script_before"] = {"id": existing.id, "version": existing.current_version_no} if existing else None
            stored = db.get(StoredFile, item.stored_file_id)
            duplicate = db.scalar(select(ScriptFileVersion).where(ScriptFileVersion.script_file_id == existing.id,
                ScriptFileVersion.file_hash == stored.content_hash)) if existing else None
            entry["operation"] = "duplicate" if duplicate else "modify" if existing else "new"
            entry["existing_script_version_id"] = duplicate.id if duplicate else None
            refs = {}
            for rule in item.parsed_json.get("rules", []):
                for side in ("source", "target"):
                    node = rule[side]
                    if not node.get("table_name"):
                        continue
                    ref = {k: node.get(k) or settings.get(k, "") for k in ("database_name", "schema_name")}
                    ref["table_name"] = node["table_name"]
                    key = table_key(ref)
                    matching = find_tables(db, batch.project_id, ref)
                    binding = db.scalar(select(CatalogClassification).where(CatalogClassification.catalog_table_id == matching[0].id)) if len(matching) == 1 else None
                    role = "write" if side == "target" else "read"
                    refs[(key, role)] = {**ref, "key": key, "role": role,
                        "catalog_table_id": matching[0].id if len(matching) == 1 else None,
                        "layer_key": binding.assignment_json.get("layer_key") if binding else None,
                        "proposed_layer_key": options_for(batch, item, ref).get("layer_key") if role == "write" else None}
            entry["references"] = list(refs.values())
        projected.append(entry)
    return {"architecture_version": architecture.version if architecture else 0, "items": projected}


def save_options(db, batch, version, options):
    changed = db.execute(update(ResourceImportBatch).where(ResourceImportBatch.id == batch.id,
        ResourceImportBatch.version == version, ResourceImportBatch.status == "preview")
        .values(options_json=options, version=version + 1))
    if changed.rowcount != 1:
        raise HTTPException(409, "预览已更新或已确认，请刷新批次")
    db.refresh(batch)
    # File kind / dialect are fixed at upload; changing these requires a new batch.
    batch.preview_json = preview(db, batch)
    db.commit()
    return batch


def _metadata_apply(db, project_id, table):
    data = table["metadata"]
    matches = find_tables(db, project_id, data)
    if table["catalog_table_id"]:
        matches = [x for x in matches if x.id == table["catalog_table_id"]]
    if len(matches) > 1:
        raise ValueError("ambiguous_identity")
    target = matches[0] if matches else None
    if target is None:
        source_name = "offline-" + digest(data["database_name"])[:40]
        source = db.scalar(select(DataSource).where(DataSource.project_id == project_id, DataSource.name == source_name))
        if source is None:
            source = DataSource(project_id=project_id, name=source_name, display_name="离线文件：" + data["database_name"],
                db_type="offline", database_name=data["database_name"], enabled=False, readonly_flag=True)
            db.add(source); db.flush()
        if source.db_type != "offline" or source.database_name != data["database_name"]:
            raise ValueError("offline_namespace_conflict")
        schema = db.scalar(select(CatalogSchema).where(CatalogSchema.datasource_id == source.id, CatalogSchema.schema_name == data["schema_name"]))
        if schema is None:
            schema = CatalogSchema(project_id=project_id, datasource_id=source.id, schema_name=data["schema_name"])
            db.add(schema); db.flush()
        target = CatalogTable(project_id=project_id, datasource_id=source.id, catalog_schema_id=schema.id,
            database_name=data["database_name"], schema_name=data["schema_name"], table_name=data["table_name"], table_type="table",
            primary_key_columns_json=[x["column_name"] for x in data["columns"] if x.get("is_primary_key")])
        db.add(target); db.flush()
    if not target.table_comment:
        target.table_comment = data.get("table_comment")
    for column in data["columns"]:
        old = db.scalar(select(CatalogColumn).where(CatalogColumn.catalog_table_id == target.id, CatalogColumn.column_name == column["column_name"]))
        if old is None:
            old = CatalogColumn(project_id=project_id, datasource_id=target.datasource_id, catalog_table_id=target.id,
                database_name=target.database_name, schema_name=target.schema_name, table_name=target.table_name,
                database_native_type=column["data_type"], **column)
            db.add(old)
        else:
            # Existing structure, annotations and bindings are human-owned by default.
            for attr in ("data_type", "column_comment"):
                if not getattr(old, attr):
                    setattr(old, attr, column.get(attr))
    db.flush()
    return target


def _classify_if_unassigned(db, batch, target, table):
    if table.get("layer_key") is None and table.get("business_system_id") is None:
        return
    binding = db.scalar(select(CatalogClassification).where(CatalogClassification.catalog_table_id == target.id))
    if binding and any(binding.assignment_json.get(k) is not None for k in ("layer_key", "business_system_id", "target_table_id")):
        return
    data_architecture.assign_table(db, batch.project_id, target.id,
        {"layer_key": table.get("layer_key"), "business_system_id": table.get("business_system_id")}, batch.preview_json["architecture_version"])


def batch_import_handler(db, job):
    batch = load_batch(db, job.project_id, int(job.payload_summary_json["batch_id"]))
    if (batch.created_by != job.created_by or batch.status == "preview" or
            job.payload_summary_json.get("preview_version") != batch.version):
        raise ValueError("批次尚未确认或执行人不一致")
    batch.status = "running"
    db.commit()
    project = db.get(Project, batch.project_id)
    previews = {x["id"]: x for x in batch.preview_json["items"]}
    storage = get_storage_service()
    own_hashes = {}
    for item in items(db, batch):
        if item.status == "completed":
            own_hashes.update(item.result_json.get("asset_hashes", {}))
    for item in items(db, batch):
        db.refresh(job)
        if job.status == "cancelled":
            break
        if item.status in {"completed", "skipped"}:
            continue
        item_id = item.id
        plan = previews[item_id]
        result = {}
        try:
            claimed = db.execute(update(ResourceImportItem).where(ResourceImportItem.id == item_id,
                ResourceImportItem.status.in_(("preview", "failed"))).values(status="applying"))
            if claimed.rowcount != 1:
                db.rollback()
                continue
            if plan["decision"] == "skip":
                item.status = "skipped"
            else:
                if plan.get("error"):
                    raise ValueError("parse_failed")
                if not plan["complete"] and not options_for(batch, item).get("accept_incomplete"):
                    raise ValueError("解析不完整，需要在新预览中明确接受缺口")
                stored = db.get(StoredFile, item.stored_file_id)
                if not stored or stored.project_id != batch.project_id or not stored.enabled:
                    raise ValueError("stored_file_unavailable")
                data = storage.read(stored.storage_key)
                if hashlib.sha256(data).hexdigest() != stored.content_hash:
                    raise ValueError("stored_file_changed")
                result = {"catalog_table_ids": [], "asset_hashes": {}}
                for table in plan["tables"]:
                    if table["decision"] == "skip":
                        continue
                    if not table["metadata"]["database_name"] or len(table["existing_ids"]) > 1:
                        raise ValueError("物理资产身份未确认")
                    if table["conflicts"] and table["decision"] != "merge":
                        raise ValueError("存在冲突，请在预览中明确保留现有定义后合并")
                    current = find_tables(db, batch.project_id, table["metadata"])
                    if table["catalog_table_id"]:
                        current = [x for x in current if x.id == table["catalog_table_id"]]
                    actual = fingerprint(db, current[0]) if len(current) == 1 else None
                    expected = result["asset_hashes"].get(table["key"], own_hashes.get(table["key"], table["before_hash"]))
                    if len(current) > 1 or actual != expected:
                        raise ValueError("目录已变化，请建立新的导入预览")
                    target = _metadata_apply(db, batch.project_id, table)
                    _classify_if_unassigned(db, batch, target, table)
                    result["catalog_table_ids"].append(target.id)
                    result["asset_hashes"][table["key"]] = fingerprint(db, target)
                if item.file_kind == "sql":
                    script = db.scalar(select(ScriptFile).where(ScriptFile.project_id == batch.project_id,
                        ScriptFile.code_repository_id.is_(None), ScriptFile.relative_path == item.relative_path))
                    before = {"id": script.id, "version": script.current_version_no} if script else None
                    if before != plan.get("script_before"):
                        raise ValueError("脚本版本已变化，请重新预览")
                    ingested = ScriptIngestionService(db, storage).ingest(project=project, data=data,
                        file_name=PurePosixPath(item.relative_path).name, relative_path=item.relative_path,
                        dialect=batch.options_json.get("dialect"), actor_user_id=batch.created_by, build_revision=False, commit=False)
                    result.update(script_file_id=ingested.script_file.id, script_version_id=ingested.version.id,
                                  parse_status=ingested.version.parse_status)
                    for ref in plan["references"]:
                        # Reads never inherit the batch layer. Only known write assets can be classified.
                        if ref["role"] == "write" and ref["catalog_table_id"] and ref.get("proposed_layer_key"):
                            target = db.get(CatalogTable, ref["catalog_table_id"])
                            _classify_if_unassigned(db, batch, target, {"layer_key": ref["proposed_layer_key"]})
                item.status = "completed"
                item.result_json = result
            progress = db.scalar(select(BackgroundJobItem).where(BackgroundJobItem.background_job_id == job.id,
                BackgroundJobItem.item_key == str(item_id)))
            if progress is None:
                progress = BackgroundJobItem(background_job_id=job.id, item_key=str(item_id)); db.add(progress)
            progress.status = item.status
            progress.result_summary_json = item.result_json
            progress.error_message = None
            db.commit()
            own_hashes.update(result.get("asset_hashes", {}))
        except Exception as exc:
            db.rollback()
            item = db.get(ResourceImportItem, item_id)
            item.status = "failed"
            item.result_json = {"error": "导入未应用；请检查解析缺口、冲突确认、归属或资产版本", "error_type": type(exc).__name__}
            progress = db.scalar(select(BackgroundJobItem).where(BackgroundJobItem.background_job_id == job.id,
                BackgroundJobItem.item_key == str(item_id)))
            if progress is None:
                progress = BackgroundJobItem(background_job_id=job.id, item_key=str(item_id)); db.add(progress)
            progress.status = "failed"; progress.result_summary_json = {}; progress.error_message = item.result_json["error"]
            db.commit()
    current = items(db, batch)
    script_version_ids = sorted({
        int(item.result_json["script_version_id"])
        for item in current
        if item.status == "completed" and item.result_json.get("script_version_id")
    })
    # Catalog and SQL files can be applied in separate attempts of the same
    # preview. Re-run binding for every completed script version after the
    # whole batch, not only for files handled in this pass.
    for version_id in script_version_ids:
        reresolve_lineage_version(db, version_id)
    # The editable preview is also the post-apply result view. Rebuild it after
    # catalog and script files have all been applied so references no longer
    # show pre-apply "missing catalog asset" warnings.
    batch.preview_json = preview(db, batch)
    succeeded = sum(x.status == "completed" for x in current)
    failed = sum(x.status not in {"completed", "skipped"} for x in current)
    skipped = sum(x.status == "skipped" for x in current)
    batch.status = "partial" if failed and succeeded else "failed" if failed else "completed"
    if any(x.result_json.get("script_version_id") for x in current):
        revision = LineageRevisionService(db).build(batch.project_id, created_by=batch.created_by,
            trigger_type="script_ingest", status="needs_review", publish=False)
        revision_id = revision.revision.id
    else:
        revision_id = None
    db.commit()
    return {"batch_id": batch.id, "success_count": succeeded, "failed_count": failed,
            "skipped_count": skipped, "lineage_revision_id": revision_id}


def summary(db, batch):
    status = batch.status
    job = db.get(BackgroundJob, batch.job_id) if batch.job_id else None
    if job and job.status in {"failed", "cancelled", "partially_completed"} and status in {"running", "queued"}:
        status = "partial" if any(x.status == "completed" for x in items(db, batch)) else "failed"
    return {"id": batch.id, "project_id": batch.project_id, "version": batch.version, "status": status,
        "job_id": batch.job_id, "options": batch.options_json, "preview": batch.preview_json,
        "items": [{"id": x.id, "path": x.relative_path, "status": x.status, "result": x.result_json} for x in items(db, batch)]}
