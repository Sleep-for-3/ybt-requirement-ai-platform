from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models import SqlFile, SqlParseResult
from app.services.sql_parser import parse_sql


async def ingest_sql_file(db: Session, project_id: int, upload_file: UploadFile) -> SqlFile:
    suffix = Path(upload_file.filename or "").suffix.lower()
    if suffix != ".sql":
        raise ValueError("Only .sql files are supported by the SQL parser.")

    content_bytes = await upload_file.read()
    raw_sql = content_bytes.decode("utf-8")
    storage_path = _write_sql_upload(project_id, upload_file.filename or "script.sql", content_bytes)
    sql_file = SqlFile(
        project_id=project_id,
        file_name=upload_file.filename or "script.sql",
        storage_path=storage_path,
        raw_sql=raw_sql,
    )
    db.add(sql_file)
    db.flush()

    parsed = parse_sql(raw_sql)
    db.add(
        SqlParseResult(
            sql_file_id=sql_file.id,
            project_id=project_id,
            parsed_success=parsed.parsed_success,
            source_tables_json=parsed.source_tables,
            selected_fields_json=parsed.selected_fields,
            joins_json=parsed.joins,
            where_conditions_json=parsed.where_conditions,
            error_message=parsed.error_message,
        )
    )
    db.commit()
    db.refresh(sql_file)
    return sql_file


def _write_sql_upload(project_id: int, original_name: str, content: bytes) -> str:
    upload_dir = Path(get_settings().storage_dir) / "projects" / str(project_id) / "sql"
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = original_name.replace("/", "_").replace("\\", "_")
    storage_path = upload_dir / f"{uuid4().hex}-{safe_name}"
    with open(storage_path, "wb") as file:
        file.write(content)
    return str(storage_path)
