import hashlib
import re
from typing import Any
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    MartField, MartTable, MartToYbtMapping, ScenarioBusinessMapping, ScenarioTechnicalLineage,
    TargetField, TargetTable, TemplateApplication, TemplateDocument, TemplateParseResult, TemplateVersion,
)
from app.schemas import TemplatePreviewItem, TemplateUploadResponse
from app.services.storage import get_storage_service
from app.services.template_parser import ExcelTemplateParser, SurveyTemplateParser, is_survey_workbook


@dataclass
class TemplateApplySummary:
    template_id: int
    created_tables: int = 0
    updated_tables: int = 0
    created_fields: int = 0
    updated_fields: int = 0
    created_mart_tables: int = 0
    created_mart_fields: int = 0
    created_mart_mappings: int = 0
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
        # 真实客户模板（一表通调研表）版式与早期单行表头模板不同，按版式分派解析器；
        # 两者产出同一 ExcelTemplateParseOutput 结构，落库与审核流程保持一致。
        survey = is_survey_workbook(BytesIO(content))
        output = (SurveyTemplateParser() if survey else ExcelTemplateParser()).parse(BytesIO(content))
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
        # 表级口径（主题/填报说明/报送数据域）：调研表里已有的事实，落库供导出文档引用。
        version.table_meta_json = getattr(output, "table_meta", {}) or {}
        version.parse_report_json = output.parse_report or {}
        # Keep legacy summary columns without changing the active version pointer.
        document.file_name, document.file_type, document.storage_path = file_name, "xlsx", storage_path
        document.sheet_names_json, document.parse_status, document.error_message = output.sheet_names, "success", None
        document.display_name = display_name or document.display_name
        db.commit()
        return TemplateUploadResponse(template_id=document.id, version_id=version.id,
            version_no=version.version_no, file_name=file_name, parse_status=version.parse_status,
            sheet_count=output.sheet_count, table_count=output.table_count,
            field_count=output.field_count, warnings=output.warnings,
            parse_report=output.parse_report,
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
        # 表级口径来自“表级口径”sheet：只补空值，绝不覆盖已人工维护的内容。
        meta = (version.table_meta_json or {}).get((table_code or "").upper()) if version else None
        if meta:
            for column in ("theme", "filing_note", "reporting_domain_code", "reporting_domain_name"):
                value = meta.get(column)
                if value and not getattr(table, column):
                    setattr(table, column, value)

        for row in result.parsed_rows_json or []:
            field_code, field_name = (row.get("field_code") or "").strip(), (row.get("field_name") or "").strip()
            if not field_code or not field_name:
                summary.skipped_rows += 1; summary.warnings.append(f"{result.sheet_name} 第 {row.get('row_number', '?')} 行缺少字段代码或字段名称，已跳过"); continue
            if not _FIELD_CODE_PATTERN.match(field_code):
                summary.skipped_rows += 1
                summary.warnings.append(
                    f"{result.sheet_name} 第 {row.get('row_number', '?')} 行的字段代码「{field_code}」不是标识符，按分段标记行跳过"
                )
                continue
            field = db.scalar(select(TargetField).where(TargetField.target_table_id == table.id,
                TargetField.field_code == field_code))
            payload = {"project_id": document.project_id, "target_table_id": table.id, "field_code": field_code,
                "field_name": field_name, "field_type": row.get("field_type") or None,
                "required_flag": _as_required(row.get("required_flag")), "field_definition": row.get("field_definition") or None,
                "regulatory_description": row.get("regulatory_description") or None}
            # 一表通调研表带回的扩展口径（示例需求文档 A–K 列）：只写非空值，避免覆盖已人工确认的内容。
            for column, source_key in _EXTENDED_FIELD_COLUMNS.items():
                value = row.get(source_key)
                if value not in (None, ""):
                    payload[column] = value
            before = _field_snapshot(field) if field else None
            if field:
                for key, value in payload.items(): setattr(field, key, value)
                summary.updated_fields += 1
            else:
                field = TargetField(**payload); db.add(field); db.flush(); summary.created_fields += 1
            _apply_mart_mapping(db, document, field, row, summary)
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


#: 调研表列 -> ``TargetField`` 扩展列。语义映射在 :mod:`survey_excel_parser` 里已写死。
_EXTENDED_FIELD_COLUMNS = {
    "data_category": "data_category",
    "data_format": "data_format",
    "regulatory_original_definition": "regulatory_original_definition",
    "regulatory_refined_definition": "regulatory_refined_definition",
    "report_name": "report_name",
    "report_field_name": "report_field_name",
    "east_definition": "east_definition",
    "internal_definition": "internal_definition",
    "remarks": "remarks",
}


#: 集市表/字段只在确实是标识符时才落库：真实调研表里有个别单元格填的是
#: ``CASE WHEN ... END`` 之类的取数表达式，直接塞进 ``field_code`` 会超长并被数据库拒绝。
_MART_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]{0,63}$")
#: 监管字段代码必须是标识符。真实调研表的数据区中间夹着"辅助字段""数据项编码""补充字段"
#: 这类分段标记行（表编号/表名称列为空），早期解析会把它们当成字段导入，形成
#: field_code 为中文的假字段——它们没有脚本血缘、没有集市映射，只会让"字段总数/脚本覆盖"
#: 这类统计失真。解析器已跳过这些行，这里再守一道：非标识符代码一律跳过并计入 skipped_rows。
_FIELD_CODE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


def _apply_mart_mapping(db: Session, document: TemplateDocument, field: TargetField, row: dict,
                        summary: "TemplateApplySummary") -> None:
    """把调研表里的“监管集市表/集市字段/取数逻辑”落成集市映射草稿。

    真实调研表一个字段可以对应**多个**集市表（同一 sheet 里重复多组集市列），因此优先按
    ``row["mart_mappings"]`` 逐组落库；老格式（只有单个 ``mart_*`` 键）仍按单条处理。

    只按模板原值建立映射，不推断关联键或过滤条件：``business_rule`` 只放模板给出的取数逻辑，
    缺失即留空并在 ``mapping_name`` 里标注待补，避免把空值伪装成已确认口径。
    """

    groups = row.get("mart_mappings")
    if isinstance(groups, list) and groups:
        for group in groups:
            if isinstance(group, dict):
                _apply_single_mart_mapping(db, document, field, group, summary)
        return
    _apply_single_mart_mapping(db, document, field, row, summary)


def _apply_single_mart_mapping(db: Session, document: TemplateDocument, field: TargetField, row: dict,
                               summary: "TemplateApplySummary") -> None:
    """落一条集市映射草稿（供 ``_apply_mart_mapping`` 逐组调用）。"""

    table_code = (row.get("mart_table_code") or "").strip()
    field_code = (row.get("mart_field_code") or "").strip()
    table_name = (row.get("mart_table_name") or "").strip()
    field_name = (row.get("mart_field_name") or "").strip()
    logic = (row.get("mart_logic") or "").strip()
    if not table_code and not field_code:
        return
    if table_code and not _MART_IDENTIFIER.match(table_code):
        # 不是表名：保留原文作为映射说明，避免把表达式当表名写库。
        logic = "；".join(filter(None, [logic, f"模板集市表原文：{table_code[:500]}"]))
        table_code, table_name = "", ""
    if field_code and not _MART_IDENTIFIER.match(field_code):
        logic = "；".join(filter(None, [logic, f"模板集市字段原文：{field_code[:1500]}"]))
        field_code, field_name = "", ""
    mart_table = None
    if table_code:
        mart_table = db.scalar(select(MartTable).where(
            MartTable.project_id == document.project_id, MartTable.table_code == table_code))
        if mart_table is None:
            mart_table = MartTable(project_id=document.project_id, table_code=table_code,
                                   table_name=table_name or table_code, physical_table_name=table_code,
                                   description=f"由监管报送模板 {document.file_name} 识别")
            db.add(mart_table); db.flush(); summary.created_mart_tables += 1
        elif table_name and mart_table.table_name != table_name:
            mart_table.table_name = table_name
    mart_field = None
    if mart_table is not None and field_code:
        mart_field = db.scalar(select(MartField).where(
            MartField.mart_table_id == mart_table.id, MartField.field_code == field_code))
        if mart_field is None:
            mart_field = MartField(project_id=document.project_id, mart_table_id=mart_table.id,
                                   field_code=field_code, field_name=field_name or field_code,
                                   physical_column_name=field_code)
            db.add(mart_field); db.flush(); summary.created_mart_fields += 1
        elif field_name and mart_field.field_name != field_name:
            mart_field.field_name = field_name
    mapping = db.scalar(select(MartToYbtMapping).where(
        MartToYbtMapping.project_id == document.project_id,
        MartToYbtMapping.target_field_id == field.id,
        MartToYbtMapping.mart_field_id == (mart_field.id if mart_field else None)))
    if mapping is None:
        mapping = MartToYbtMapping(
            project_id=document.project_id,
            target_field_id=field.id,
            mart_field_id=mart_field.id if mart_field else None,
            mapping_name=f"{field.field_code} → {field_code or table_code or '待补集市字段'}",
            mapping_status="draft",
            mart_table_summary=f"{table_name}({table_code})" if table_code else None,
            mart_field_summary=f"{field_name}({field_code})" if field_code else None,
            business_rule=logic or None,
            open_questions=None if logic else "模板未给出取数逻辑，需补充映射规则后再确认",
        )
        db.add(mapping); db.flush(); summary.created_mart_mappings += 1
    elif logic and mapping.business_rule != logic:
        mapping.business_rule = logic

_REQUIRED_TRUE = {"是", "y", "yes", "true", "1", "必填", "必输", "not null", "非空"}


def _as_required(value: Any) -> bool:
    """把模板原值转成必填标记。

    早期解析器产 bool，一表通调研表产“是/否”字符串；``bool("否")`` 为 True，
    直接转换会把所有字段都标成必填，因此这里显式判定字符串。
    """

    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in _REQUIRED_TRUE
