from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import MartField, MartTable, Project
from app.schemas import MartFieldCreate, MartFieldRead, MartFieldUpdate, MartTableCreate, MartTableRead, MartTableUpdate

router = APIRouter(tags=["mart"])


@router.post("/projects/{project_id}/mart-tables", response_model=MartTableRead)
def create_mart_table(project_id: int, payload: MartTableCreate, db: Session = Depends(get_db)) -> MartTable:
    _get_project_or_404(db, project_id)
    table = MartTable(project_id=project_id, **payload.model_dump())
    db.add(table)
    db.commit()
    db.refresh(table)
    return table


@router.get("/projects/{project_id}/mart-tables", response_model=list[MartTableRead])
def list_mart_tables(project_id: int, db: Session = Depends(get_db)) -> list[MartTable]:
    return list(db.scalars(select(MartTable).where(MartTable.project_id == project_id).order_by(MartTable.id)).all())


@router.get("/mart-tables/{table_id}", response_model=MartTableRead)
def get_mart_table(table_id: int, db: Session = Depends(get_db)) -> MartTable:
    return _get_mart_table_or_404(db, table_id)


@router.put("/mart-tables/{table_id}", response_model=MartTableRead)
def update_mart_table(table_id: int, payload: MartTableUpdate, db: Session = Depends(get_db)) -> MartTable:
    table = _get_mart_table_or_404(db, table_id)
    _apply_updates(table, payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(table)
    return table


@router.delete("/mart-tables/{table_id}")
def delete_mart_table(table_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    table = _get_mart_table_or_404(db, table_id)
    db.delete(table)
    db.commit()
    return {"status": "deleted"}


@router.post("/mart-tables/{table_id}/mart-fields", response_model=MartFieldRead)
def create_mart_field(table_id: int, payload: MartFieldCreate, db: Session = Depends(get_db)) -> MartField:
    table = _get_mart_table_or_404(db, table_id)
    field = MartField(project_id=table.project_id, mart_table_id=table.id, **payload.model_dump())
    db.add(field)
    db.commit()
    db.refresh(field)
    return field


@router.get("/mart-tables/{table_id}/mart-fields", response_model=list[MartFieldRead])
def list_mart_fields(table_id: int, db: Session = Depends(get_db)) -> list[MartField]:
    _get_mart_table_or_404(db, table_id)
    return list(db.scalars(select(MartField).where(MartField.mart_table_id == table_id).order_by(MartField.id)).all())


@router.get("/mart-fields/{field_id}", response_model=MartFieldRead)
def get_mart_field(field_id: int, db: Session = Depends(get_db)) -> MartField:
    return _get_mart_field_or_404(db, field_id)


@router.put("/mart-fields/{field_id}", response_model=MartFieldRead)
def update_mart_field(field_id: int, payload: MartFieldUpdate, db: Session = Depends(get_db)) -> MartField:
    field = _get_mart_field_or_404(db, field_id)
    _apply_updates(field, payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(field)
    return field


@router.delete("/mart-fields/{field_id}")
def delete_mart_field(field_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    field = _get_mart_field_or_404(db, field_id)
    db.delete(field)
    db.commit()
    return {"status": "deleted"}


def _get_project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _get_mart_table_or_404(db: Session, table_id: int) -> MartTable:
    table = db.get(MartTable, table_id)
    if table is None:
        raise HTTPException(status_code=404, detail="Mart table not found")
    return table


def _get_mart_field_or_404(db: Session, field_id: int) -> MartField:
    field = db.get(MartField, field_id)
    if field is None:
        raise HTTPException(status_code=404, detail="Mart field not found")
    return field


def _apply_updates(model: object, values: dict) -> None:
    for key, value in values.items():
        setattr(model, key, value)
