from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models import TargetField, TargetTable, TemplateDocument, TemplateParseResult
from app.schemas import TemplatePreviewItem, TemplateUploadResponse
from app.services.template_parser import ExcelTemplateParser


@dataclass
class TemplateApplySummary:
    template_id: int
    created_tables: int = 0
    updated_tables: int = 0
    created_fields: int = 0
    updated_fields: int = 0
    skipped_rows: int = 0
    warnings: list[str] = None

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []


async def ingest_template(db: Session, project_id: int, upload_file: UploadFile) -> TemplateUploadResponse:
    suffix = Path(upload_file.filename or "").suffix.lower()
    if suffix == ".xls":
        raise ValueError("暂不支持 .xls，请另存为 .xlsx 后上传。")
    if suffix != ".xlsx":
        raise ValueError("MVP 阶段只支持 .xlsx 一表通模板。")

    content = await upload_file.read()
    storage_path = _write_template_upload(project_id, upload_file.filename or "template.xlsx", content)
    document = TemplateDocument(
        project_id=project_id,
        file_name=upload_file.filename or "template.xlsx",
        file_type="xlsx",
        storage_path=storage_path,
        sheet_names_json=[],
        parse_status="pending",
    )
    db.add(document)
    db.flush()

    try:
        output = ExcelTemplateParser().parse(storage_path)
        document.sheet_names_json = output.sheet_names
        document.parse_status = "success"
        for result in output.results:
            db.add(
                TemplateParseResult(
                    template_document_id=document.id,
                    project_id=project_id,
                    sheet_name=result.sheet_name,
                    table_code=result.table_code,
                    table_name=result.table_name,
                    field_count=result.field_count,
                    raw_header_json=result.raw_header,
                    parsed_rows_json=result.parsed_rows,
                    warnings_json=result.warnings,
                )
            )
        db.commit()
        return TemplateUploadResponse(
            template_id=document.id,
            file_name=document.file_name,
            parse_status=document.parse_status,
            sheet_count=output.sheet_count,
            table_count=output.table_count,
            field_count=output.field_count,
            warnings=output.warnings,
            preview=[
                TemplatePreviewItem(
                    sheet_name=result.sheet_name,
                    table_code=result.table_code,
                    table_name=result.table_name,
                    field_count=result.field_count,
                )
                for result in output.results
            ],
        )
    except Exception as exc:
        document.parse_status = "failed"
        document.error_message = str(exc)
        db.commit()
        raise


def apply_template(db: Session, template_id: int) -> TemplateApplySummary:
    document = db.get(TemplateDocument, template_id)
    if document is None:
        raise ValueError("Template document not found")
    results = db.scalars(
        select(TemplateParseResult).where(TemplateParseResult.template_document_id == template_id)
    ).all()
    summary = TemplateApplySummary(template_id=template_id)
    for result in results:
        table_code = result.table_code or result.sheet_name
        table_name = result.table_name or result.sheet_name
        table = db.scalar(
            select(TargetTable).where(TargetTable.project_id == document.project_id, TargetTable.table_code == table_code)
        )
        if table:
            table.table_name = table_name
            table.description = table.description or f"由模板 {document.file_name} / {result.sheet_name} 导入"
            summary.updated_tables += 1
        else:
            table = TargetTable(
                project_id=document.project_id,
                table_code=table_code,
                table_name=table_name,
                description=f"由模板 {document.file_name} / {result.sheet_name} 导入",
            )
            db.add(table)
            db.flush()
            summary.created_tables += 1

        for row in result.parsed_rows_json or []:
            field_code = (row.get("field_code") or "").strip()
            field_name = (row.get("field_name") or "").strip()
            if not field_code or not field_name:
                summary.skipped_rows += 1
                summary.warnings.append(f"{result.sheet_name} 第 {row.get('row_number', '?')} 行缺少字段代码或字段名称，已跳过")
                continue
            field = db.scalar(
                select(TargetField).where(TargetField.target_table_id == table.id, TargetField.field_code == field_code)
            )
            payload = {
                "project_id": document.project_id,
                "target_table_id": table.id,
                "field_code": field_code,
                "field_name": field_name,
                "field_type": row.get("field_type") or None,
                "required_flag": bool(row.get("required_flag")),
                "field_definition": row.get("field_definition") or None,
                "regulatory_description": row.get("regulatory_description") or None,
            }
            if field:
                for key, value in payload.items():
                    setattr(field, key, value)
                summary.updated_fields += 1
            else:
                db.add(TargetField(**payload))
                summary.created_fields += 1
    db.commit()
    return summary


def _write_template_upload(project_id: int, original_name: str, content: bytes) -> str:
    upload_dir = Path(get_settings().storage_dir) / "projects" / str(project_id) / "templates"
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = original_name.replace("/", "_").replace("\\", "_")
    path = upload_dir / f"{uuid4().hex}-{safe_name}"
    with open(path, "wb") as file:
        file.write(content)
    return str(path)
