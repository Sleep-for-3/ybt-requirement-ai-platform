from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.models import SqlFile
from app.schemas import SqlFileRead
from app.services.sql_file_service import ingest_sql_file

router = APIRouter(prefix="/sql-files", tags=["sql files"])


@router.get("", response_model=list[SqlFileRead])
def list_sql_files(project_id: int, db: Session = Depends(get_db)) -> list[SqlFile]:
    statement = (
        select(SqlFile)
        .options(selectinload(SqlFile.parse_result))
        .where(SqlFile.project_id == project_id)
        .order_by(SqlFile.id.desc())
    )
    return list(db.scalars(statement).all())


@router.post("/upload", response_model=SqlFileRead)
async def upload_sql_file(
    project_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> SqlFile:
    try:
        return await ingest_sql_file(db, project_id, file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
