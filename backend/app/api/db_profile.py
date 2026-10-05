from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import DbProfileTask
from app.schemas import DbProfileTaskCreate, DbProfileTaskRead
from app.services.db.safe_sql_executor import SafeSqlExecutor

router = APIRouter(prefix="/db-profile", tags=["db profile"])


@router.post("/tasks", response_model=DbProfileTaskRead)
def create_db_profile_task(payload: DbProfileTaskCreate, db: Session = Depends(get_db)) -> DbProfileTask:
    executor = SafeSqlExecutor()
    profile_preview = {}
    if payload.table_name and payload.field_name:
        # An invalid identifier is bad input, not a server fault: answer 422 with the reason instead
        # of letting ValueError surface as a 500.
        try:
            profile_preview = executor.profile_field(payload.table_name, payload.field_name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    task = DbProfileTask(
        **payload.model_dump(),
        status="reserved",
        profile_result_json=profile_preview,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task
