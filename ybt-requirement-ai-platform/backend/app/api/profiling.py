from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import CatalogColumn,ColumnProfileSnapshot,ColumnProfileTask
from app.schemas import ColumnProfileRequest,ColumnProfileSnapshotRead,ColumnProfileTaskRead,ProfileEvidenceBindRequest,MappingEvidenceRead
from app.services.metadata.profile_service import bind_profile_evidence,run_column_profile
router=APIRouter(tags=["column profiling"])
@router.post("/catalog/columns/{column_id}/profile",response_model=ColumnProfileTaskRead)
def profile(column_id:int,payload:ColumnProfileRequest,db:Session=Depends(get_db)):
    column=db.get(CatalogColumn,column_id)
    if column is None:raise HTTPException(404,"Catalog column not found")
    try:return run_column_profile(db,column,payload)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
@router.get("/profile-tasks/{task_id}",response_model=ColumnProfileTaskRead)
def task(task_id:int,db:Session=Depends(get_db)):
    item=db.get(ColumnProfileTask,task_id)
    if item is None:raise HTTPException(404,"Profile task not found")
    return item
@router.get("/catalog/columns/{column_id}/profiles",response_model=list[ColumnProfileSnapshotRead])
def profiles(column_id:int,db:Session=Depends(get_db)):
    return list(db.scalars(select(ColumnProfileSnapshot).where(ColumnProfileSnapshot.catalog_column_id==column_id).order_by(ColumnProfileSnapshot.id.desc())).all())

@router.post("/profile-tasks/{task_id}/bind-evidence",response_model=MappingEvidenceRead)
def bind_evidence(task_id:int,payload:ProfileEvidenceBindRequest,db:Session=Depends(get_db)):
    try:return bind_profile_evidence(db,task_id,payload.mapping_type,payload.mapping_id)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
