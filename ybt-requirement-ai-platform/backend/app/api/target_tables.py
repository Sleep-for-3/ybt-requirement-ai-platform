from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import TargetTable
from app.schemas import TargetTableCreate, TargetTableRead

router = APIRouter(prefix="/target-tables", tags=["target tables"])


@router.get("", response_model=list[TargetTableRead])
def list_target_tables(project_id: int, db: Session = Depends(get_db)) -> list[TargetTable]:
    return list(db.scalars(select(TargetTable).where(TargetTable.project_id == project_id).order_by(TargetTable.id)).all())


@router.post("", response_model=TargetTableRead)
def create_target_table(payload: TargetTableCreate, db: Session = Depends(get_db)) -> TargetTable:
    table = TargetTable(**payload.model_dump())
    db.add(table)
    db.commit()
    db.refresh(table)
    return table
