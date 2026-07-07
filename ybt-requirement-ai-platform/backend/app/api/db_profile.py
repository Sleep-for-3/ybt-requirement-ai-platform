from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import DbProfileTask
from app.schemas import DbProfileTaskCreate, DbProfileTaskRead
from app.services.db_probe.safe_sql_executor import SafeSqlExecutor

router = APIRouter(prefix="/db-profile", tags=["db profile"])


@router.post("/tasks", response_model=DbProfileTaskRead)
def create_db_profile_task(payload: DbProfileTaskCreate, db: Session = Depends(get_db)) -> DbProfileTask:
    executor = SafeSqlExecutor()
    profile_preview = {}
    if payload.table_name and payload.field_name:
        profile_preview = executor.profile_field(payload.table_name, payload.field_name)
    task = DbProfileTask(
        **payload.model_dump(),
        status="reserved",
        profile_result_json=profile_preview,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task
