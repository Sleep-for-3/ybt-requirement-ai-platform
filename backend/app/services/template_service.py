import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ScenarioBusinessMapping, ScenarioTechnicalLineage, TargetField, TargetTable,
    TemplateApplication, TemplateDocument, TemplateParseResult, TemplateVersion,
)
from app.schemas import TemplatePreviewItem, TemplateUploadResponse
from app.services.storage import get_storage_service
from app.services.template_parser import ExcelTemplateParser


@dataclass
class TemplateApplySummary:
    template_id: int
    created_tables: int = 0
    updated_tables: int = 0
    created_fields: int = 0
    updated_fields: int = 0
    skipped_rows: int = 0
    warnings: list[str] | None = None
    template_version_id: int | None = None
    application_id: int | None = None
    change_set: list[dict] | None = None

    def __post_init__(self) -> None:
        self.warnings = self.warnings or []
        self.change_set = self.change_set or []


def stable_template_code(value: str) -> str:
    stem = Path(value or "template").stem.strip().upper()
    return re.sub(r"[^0-9A-Z\u4e00-\u9fff]+", "_", stem).strip("_")[:160] or "TEMPLATE"


async def ingest_template(
    db: Session, project_id: int, upload_file: UploadFile, *, template_code: str | None = None,
    display_name: str | None = None, regulatory_version: str | None = None,
    release_batch: str | None = None, publisher: str | None = None, published_at=None,
    effective_at=None, expires_at=None, change_note: str | None = None,
    uploaded_by: str | None = None,
) -> TemplateUploadResponse:
    suffix = Path(upload_file.filename or "").suffix.lower()
    if suffix == ".xls": raise ValueError("暂不支持 .xls，请另存为 .xlsx 后上传。")
    if suffix != ".xlsx": raise ValueError("只支持 .xlsx 一表通模板。")
    content = await upload_file.read()
    digest, file_name = hashlib.sha256(content).hexdigest(), upload_file.filename or "template.xlsx"
    code = stable_template_code(template_code or file_name)
    document = db.scalar(select(TemplateDocument).where(
        TemplateDocument.project_id == project_id, TemplateDocument.template_code == code))
    if document is None:
        document = TemplateDocument(project_id=project_id, file_name=file_name, file_type="xlsx",
            storage_path="pending", sheet_names_json=[], parse_status="pending", template_code=code,
            display_name=display_name or Path(file_name).stem)
        db.add(document); db.flush()
    duplicate = db.scalar(select(TemplateVersion).where(
        TemplateVersion.template_document_id == document.id, TemplateVersion.file_hash == digest))
    if duplicate: raise ValueError(f"该文件与内部版本 {duplicate.version_no} 完全相同，无需重复上传。")
    version_no = (db.scalar(select(func.max(TemplateVersion.version_no)).where(
        TemplateVersion.template_document_id == document.id)) or 0) + 1
    storage_path = get_storage_service().save(content, file_name=file_name, project_id=project_id).storage_key
    version = TemplateVersion(template_document_id=document.id, project_id=project_id,
        version_no=version_no, regulatory_version=regulatory_version, release_batch=release_batch,
        template_code=code, publisher=publisher, published_at=published_at, effective_at=effective_at,
        expires_at=expires_at, status="draft", replaces_version_id=document.current_version_id,
        change_note=change_note, file_name=file_name, file_type="xlsx", storage_path=storage_path,
        file_hash=digest, sheet_names_json=[], parsed_snapshot_json=[], parse_status="pending",
        uploaded_by=uploaded_by)
    db.add(version); db.flush()
    try:
        output = ExcelTemplateParser().parse(BytesIO(content))
        version.sheet_names_json, version.parse_status, version.status = output.sheet_names, "success", "pending_review"
        snapshot = []
        for result in output.results:
            snapshot.append({"sheet_name": result.sheet_name, "table_code": result.table_code,
                "table_name": result.table_name, "rows": result.parsed_rows})
            db.add(TemplateParseResult(template_document_id=document.id, template_version_id=version.id,
                project_id=project_id, sheet_name=result.sheet_name, table_code=result.table_code,
                table_name=result.table_name, field_count=result.field_count,
                raw_header_json=result.raw_header, parsed_rows_json=result.parsed_rows,
                warnings_json=result.warnings))
        version.parsed_snapshot_json = snapshot
        # Keep legacy summary columns without changing the active version pointer.
        document.file_name, document.file_type, document.storage_path = file_name, "xlsx", storage_path
        document.sheet_names_json, document.parse_status, document.error_message = output.sheet_names, "success", None
        document.display_name = display_name or document.display_name
        db.commit()
        return TemplateUploadResponse(template_id=document.id, version_id=version.id,
            version_no=version.version_no, file_name=file_name, parse_status=version.parse_status,
            sheet_count=output.sheet_count, table_count=output.table_count,
            field_count=output.field_count, warnings=output.warnings,
            preview=[TemplatePreviewItem(sheet_name=item.sheet_name, table_code=item.table_code,
                table_name=item.table_name, field_count=item.field_count) for item in output.results])
    except Exception as exc:
        version.parse_status, version.status, version.error_message = "failed", "draft", type(exc).__name__
        document.parse_status, document.error_message = "failed", "模板解析失败，请检查文件格式。"
        db.commit()
        raise ValueError("模板解析失败，请检查工作表和表头格式。") from exc


def review_template_version(db: Session, version_id: int, reviewer: str | None = None) -> TemplateVersion:
    version = db.get(TemplateVersion, version_id)
    if not version: raise ValueError("Template version not found")
    if version.parse_status != "success" or version.status not in {"pending_review", "draft"}:
        raise ValueError("只有解析成功的待审核版本可以审核")
    version.status, version.reviewed_by, version.reviewed_at = "approved", reviewer, datetime.now(UTC)
    db.commit(); db.refresh(version); return version


def activate_template_version(db: Session, version_id: int) -> TemplateVersion:
    version = db.get(TemplateVersion, version_id)
    if not version: raise ValueError("Template version not found")
    if version.status != "approved" or version.parse_status != "success":
        raise ValueError("版本必须解析成功并审核通过后才能激活")
    document = db.get(TemplateDocument, version.template_document_id)
    if not document: raise ValueError("Template document not found")
    previous = db.get(TemplateVersion, document.current_version_id) if document.current_version_id else None
    if previous and previous.id != version.id and previous.status == "active": previous.status = "superseded"
    version.replaces_version_id = version.replaces_version_id or (previous.id if previous else None)
    version.status, version.activated_at = "active", datetime.now(UTC)
    document.current_version_id = version.id
    db.commit(); db.refresh(version); return version


def template_version_diff(db: Session, version_id: int, compare_to_id: int | None = None) -> dict:
    version = db.get(TemplateVersion, version_id)
    if not version: raise ValueError("Template version not found")
    previous = db.get(TemplateVersion, compare_to_id) if compare_to_id else (
        db.get(TemplateVersion, version.replaces_version_id) if version.replaces_version_id else
        db.scalar(select(TemplateVersion).where(TemplateVersion.template_document_id == version.template_document_id,
            TemplateVersion.version_no < version.version_no).order_by(TemplateVersion.version_no.desc())))
    before, after = _flatten_snapshot(previous.parsed_snapshot_json if previous else []), _flatten_snapshot(version.parsed_snapshot_json or [])
    added = [_change("added", key, None, after[key]) for key in sorted(after.keys() - before.keys())]
    removed = [_change("removed", key, before[key], None) for key in sorted(before.keys() - after.keys())]
    modified = []
    for key in sorted(before.keys() & after.keys()):
        fields = {name: {"before": before[key].get(name), "after": after[key].get(name)}
            for name in sorted(set(before[key]) | set(after[key]))
            if before[key].get(name) != after[key].get(name) and name != "row_number"}
        if fields: modified.append({**_change("modified", key, before[key], after[key]), "changed_values": fields})
    codes = {item["field_code"] for item in [*added, *removed, *modified] if item.get("field_code")}
    fields = list(db.scalars(select(TargetField).where(TargetField.project_id == version.project_id,
        TargetField.field_code.in_(codes))).all()) if codes else []
    field_ids = [item.id for item in fields]
    business = db.scalar(select(func.count()).select_from(ScenarioBusinessMapping).where(
        ScenarioBusinessMapping.target_field_id.in_(field_ids))) if field_ids else 0
    technical = db.scalar(select(func.count()).select_from(ScenarioTechnicalLineage).where(
        ScenarioTechnicalLineage.target_field_id.in_(field_ids))) if field_ids else 0
    return {"version_id": version.id, "compare_to_version_id": previous.id if previous else None,
        "added": added, "removed": removed, "modified": modified,
        "summary": {"added": len(added), "removed": len(removed), "modified": len(modified)},
        "impact": {"target_fields": len(fields), "scenarios": int(business or 0),
                   "mappings": int((business or 0) + (technical or 0))}}


def apply_template(db: Session, template_id: int, *, applied_by: str | None = None) -> TemplateApplySummary:
    document = db.get(TemplateDocument, template_id)
    if document is None: raise ValueError("Template document not found")
    version = db.get(TemplateVersion, document.current_version_id) if document.current_version_id else None
    any_version = db.scalar(select(TemplateVersion.id).where(TemplateVersion.template_document_id == template_id))
    if any_version and (not version or version.status != "active"):
        raise ValueError("请先审核并激活模板版本，再执行 Apply")
    query = select(TemplateParseResult).where(TemplateParseResult.template_document_id == template_id)
    query = query.where(TemplateParseResult.template_version_id == version.id) if version else query.where(TemplateParseResult.template_version_id.is_(None))
    results = list(db.scalars(query.order_by(TemplateParseResult.id)).all())
    summary = TemplateApplySummary(template_id=template_id, template_version_id=version.id if version else None)
    before_snapshot, after_snapshot, change_set = [], [], []
    for result in results:
        table_code, table_name = result.table_code or result.sheet_name, result.table_name or result.sheet_name
        table = db.scalar(select(TargetTable).where(TargetTable.project_id == document.project_id,
            TargetTable.table_code == table_code))
        if table:
            old = {"table_code": table.table_code, "table_name": table.table_name, "description": table.description}
            table.table_name, table.description = table_name, table.description or f"由模板 {document.file_name} / {result.sheet_name} 导入"
            summary.updated_tables += 1
            if old["table_name"] != table.table_name:
                change_set.append({"entity": "table", "key": table_code, "operation": "update", "before": old,
                    "after": {"table_code": table.table_code, "table_name": table.table_name, "description": table.description}})
        else:
            table = TargetTable(project_id=document.project_id, table_code=table_code, table_name=table_name,
                description=f"由模板 {document.file_name} / {result.sheet_name} 导入")
            db.add(table); db.flush(); summary.created_tables += 1
            change_set.append({"entity": "table", "key": table_code, "operation": "create", "before": None,
                "after": {"table_code": table_code, "table_name": table_name}})
        for row in result.parsed_rows_json or []:
            field_code, field_name = (row.get("field_code") or "").strip(), (row.get("field_name") or "").strip()
            if not field_code or not field_name:
                summary.skipped_rows += 1; summary.warnings.append(f"{result.sheet_name} 第 {row.get('row_number', '?')} 行缺少字段代码或字段名称，已跳过"); continue
            field = db.scalar(select(TargetField).where(TargetField.target_table_id == table.id,
                TargetField.field_code == field_code))
            payload = {"project_id": document.project_id, "target_table_id": table.id, "field_code": field_code,
                "field_name": field_name, "field_type": row.get("field_type") or None,
                "required_flag": bool(row.get("required_flag")), "field_definition": row.get("field_definition") or None,
                "regulatory_description": row.get("regulatory_description") or None}
            before = _field_snapshot(field) if field else None
            if field:
                for key, value in payload.items(): setattr(field, key, value)
                summary.updated_fields += 1
            else:
                field = TargetField(**payload); db.add(field); db.flush(); summary.created_fields += 1
            after = _field_snapshot(field)
            if before: before_snapshot.append(before)
            after_snapshot.append(after)
            if before != after: change_set.append({"entity": "field", "key": f"{table_code}.{field_code}",
                "operation": "update" if before else "create", "before": before, "after": after})
    application = TemplateApplication(project_id=document.project_id, template_document_id=document.id,
        template_version_id=version.id if version else None, change_set_json=change_set,
        before_snapshot_json=before_snapshot, after_snapshot_json=after_snapshot,
        impact_json={"tables": summary.created_tables + summary.updated_tables,
                     "fields": summary.created_fields + summary.updated_fields}, applied_by=applied_by)
    db.add(application); db.commit(); db.refresh(application)
    summary.application_id, summary.change_set = application.id, change_set
    return summary


def _flatten_snapshot(snapshot: list) -> dict[tuple[str, str, str], dict]:
    result = {}
    for sheet in snapshot or []:
        sheet_name, table_code = str(sheet.get("sheet_name") or ""), str(sheet.get("table_code") or sheet.get("sheet_name") or "")
        for row in sheet.get("rows") or []:
            field_code = str(row.get("field_code") or "").strip()
            if field_code: result[(sheet_name, table_code, field_code)] = dict(row)
    return result


def _change(kind, key, before, after):
    return {"change_type": kind, "sheet_name": key[0], "table_code": key[1], "field_code": key[2], "before": before, "after": after}


def _field_snapshot(field):
    if not field: return None
    return {name: getattr(field, name) for name in ("id", "project_id", "target_table_id", "field_code",
        "field_name", "field_type", "required_flag", "field_definition", "regulatory_description")}
