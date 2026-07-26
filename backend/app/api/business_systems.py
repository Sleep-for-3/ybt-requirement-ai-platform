from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import BusinessSystem, Project, SourceField, SourceTable
from app.schemas import (
    BusinessSystemCreate,
    BusinessSystemRead,
    BusinessSystemUpdate,
    SourceFieldCreate,
    SourceFieldRead,
    SourceFieldUpdate,
    SourceTableCreate,
    SourceTableRead,
    SourceTableUpdate,
)

router = APIRouter(tags=["business systems"])


@router.post("/projects/{project_id}/business-systems", response_model=BusinessSystemRead)
def create_business_system(project_id: int, payload: BusinessSystemCreate, db: Session = Depends(get_db)) -> BusinessSystem:
    _get_project_or_404(db, project_id)
    system = BusinessSystem(project_id=project_id, **payload.model_dump())
    db.add(system)
    db.commit()
    db.refresh(system)
    return system


@router.get("/projects/{project_id}/business-systems", response_model=list[BusinessSystemRead])
def list_business_systems(project_id: int, db: Session = Depends(get_db)) -> list[BusinessSystem]:
    return list(db.scalars(select(BusinessSystem).where(BusinessSystem.project_id == project_id).order_by(BusinessSystem.id)).all())


@router.get("/business-systems/{system_id}", response_model=BusinessSystemRead)
def get_business_system(system_id: int, db: Session = Depends(get_db)) -> BusinessSystem:
    return _get_business_system_or_404(db, system_id)


@router.put("/business-systems/{system_id}", response_model=BusinessSystemRead)
def update_business_system(system_id: int, payload: BusinessSystemUpdate, db: Session = Depends(get_db)) -> BusinessSystem:
    system = _get_business_system_or_404(db, system_id)
    _apply_updates(system, payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(system)
    return system


@router.delete("/business-systems/{system_id}")
def delete_business_system(system_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    system = _get_business_system_or_404(db, system_id)
    db.delete(system)
    db.commit()
    return {"status": "deleted"}


@router.post("/business-systems/{system_id}/source-tables", response_model=SourceTableRead)
def create_source_table(system_id: int, payload: SourceTableCreate, db: Session = Depends(get_db)) -> SourceTable:
    system = _get_business_system_or_404(db, system_id)
    table = SourceTable(project_id=system.project_id, business_system_id=system.id, **payload.model_dump())
    db.add(table)
    db.commit()
    db.refresh(table)
    return table


@router.get("/business-systems/{system_id}/source-tables", response_model=list[SourceTableRead])
def list_source_tables(system_id: int, db: Session = Depends(get_db)) -> list[SourceTable]:
    _get_business_system_or_404(db, system_id)
    return list(db.scalars(select(SourceTable).where(SourceTable.business_system_id == system_id).order_by(SourceTable.id)).all())


@router.get("/source-tables/{table_id}", response_model=SourceTableRead)
def get_source_table(table_id: int, db: Session = Depends(get_db)) -> SourceTable:
    return _get_source_table_or_404(db, table_id)


@router.put("/source-tables/{table_id}", response_model=SourceTableRead)
def update_source_table(table_id: int, payload: SourceTableUpdate, db: Session = Depends(get_db)) -> SourceTable:
    table = _get_source_table_or_404(db, table_id)
    _apply_updates(table, payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(table)
    return table


@router.delete("/source-tables/{table_id}")
def delete_source_table(table_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    table = _get_source_table_or_404(db, table_id)
    db.delete(table)
    db.commit()
    return {"status": "deleted"}


@router.post("/source-tables/{table_id}/source-fields", response_model=SourceFieldRead)
def create_source_field(table_id: int, payload: SourceFieldCreate, db: Session = Depends(get_db)) -> SourceField:
    table = _get_source_table_or_404(db, table_id)
    field = SourceField(project_id=table.project_id, source_table_id=table.id, **payload.model_dump())
    db.add(field)
    db.commit()
    db.refresh(field)
    return field


@router.get("/source-tables/{table_id}/source-fields", response_model=list[SourceFieldRead])
def list_source_fields(table_id: int, db: Session = Depends(get_db)) -> list[SourceField]:
    _get_source_table_or_404(db, table_id)
    return list(db.scalars(select(SourceField).where(SourceField.source_table_id == table_id).order_by(SourceField.id)).all())


@router.get("/source-fields/{field_id}", response_model=SourceFieldRead)
def get_source_field(field_id: int, db: Session = Depends(get_db)) -> SourceField:
    return _get_source_field_or_404(db, field_id)


@router.put("/source-fields/{field_id}", response_model=SourceFieldRead)
def update_source_field(field_id: int, payload: SourceFieldUpdate, db: Session = Depends(get_db)) -> SourceField:
    field = _get_source_field_or_404(db, field_id)
    _apply_updates(field, payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(field)
    return field


@router.delete("/source-fields/{field_id}")
def delete_source_field(field_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    field = _get_source_field_or_404(db, field_id)
    db.delete(field)
    db.commit()
    return {"status": "deleted"}


def _get_project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _get_business_system_or_404(db: Session, system_id: int) -> BusinessSystem:
    system = db.get(BusinessSystem, system_id)
    if system is None:
        raise HTTPException(status_code=404, detail="Business system not found")
    return system


def _get_source_table_or_404(db: Session, table_id: int) -> SourceTable:
    table = db.get(SourceTable, table_id)
    if table is None:
        raise HTTPException(status_code=404, detail="Source table not found")
    return table


def _get_source_field_or_404(db: Session, field_id: int) -> SourceField:
    field = db.get(SourceField, field_id)
    if field is None:
        raise HTTPException(status_code=404, detail="Source field not found")
    return field


def _apply_updates(model: object, values: dict) -> None:
    for key, value in values.items():
        setattr(model, key, value)
