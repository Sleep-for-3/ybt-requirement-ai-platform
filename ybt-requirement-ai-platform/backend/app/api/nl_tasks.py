from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import DataSource, NaturalLanguageTask
from app.schemas import NaturalLanguageTaskCreate, NaturalLanguageTaskCreateResponse, NaturalLanguageTaskRead
from app.services.natural_language_task_service import create_natural_language_task, list_project_tasks, run_natural_language_task

router = APIRouter(tags=["natural language tasks"])


@router.post("/nl-tasks", response_model=NaturalLanguageTaskCreateResponse)
def create_task(payload: NaturalLanguageTaskCreate, db: Session = Depends(get_db)) -> NaturalLanguageTaskCreateResponse:
    task = create_natural_language_task(db, payload.project_id, payload.text)
    available = []
    if task.status == "need_clarification" and not task.datasource_id:
        available = list(db.scalars(select(DataSource.name).where(DataSource.project_id == payload.project_id, DataSource.enabled.is_(True))).all())
    return NaturalLanguageTaskCreateResponse(
        task_id=task.id,
        status=task.status,
        datasource_name=task.datasource_name,
        intent=task.intent,
        extracted_table_name=task.extracted_table_name,
        extracted_field_name=task.extracted_field_name,
        message=task.error_message
        or f"已识别数据源 {task.datasource_name}，表 {task.extracted_table_name}，字段 {task.extracted_field_name}。",
        available_datasources=available,
    )


@router.get("/projects/{project_id}/nl-tasks", response_model=list[NaturalLanguageTaskRead])
def list_tasks(project_id: int, db: Session = Depends(get_db)) -> list[NaturalLanguageTask]:
    return list_project_tasks(db, project_id)


@router.get("/nl-tasks/{task_id}", response_model=NaturalLanguageTaskRead)
def get_task(task_id: int, db: Session = Depends(get_db)) -> NaturalLanguageTask:
    task = db.get(NaturalLanguageTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Natural language task not found")
    return task


@router.post("/nl-tasks/{task_id}/run", response_model=NaturalLanguageTaskRead)
def run_task(task_id: int, db: Session = Depends(get_db)) -> NaturalLanguageTask:
    try:
        return run_natural_language_task(db, task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
