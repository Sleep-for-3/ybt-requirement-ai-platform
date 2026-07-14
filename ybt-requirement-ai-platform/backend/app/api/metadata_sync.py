from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import DataSource, MetadataSyncTask
from app.schemas import MetadataSyncRequest, MetadataSyncTaskRead
from app.services.metadata import synchronize_metadata

router=APIRouter(tags=["metadata sync"])

@router.post("/datasources/{datasource_id}/metadata-sync",response_model=MetadataSyncTaskRead)
def sync(datasource_id:int,payload:MetadataSyncRequest,db:Session=Depends(get_db)):
    datasource=db.get(DataSource,datasource_id)
    if datasource is None: raise HTTPException(404,"Data source not found")
    try: return synchronize_metadata(db,datasource,payload.sync_mode,payload.schema_names,payload.include_views)
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc

@router.get("/datasources/{datasource_id}/metadata-sync-tasks",response_model=list[MetadataSyncTaskRead])
def tasks(datasource_id:int,db:Session=Depends(get_db)):
    return list(db.scalars(select(MetadataSyncTask).where(MetadataSyncTask.datasource_id==datasource_id).order_by(MetadataSyncTask.id.desc())).all())

@router.get("/metadata-sync-tasks/{task_id}",response_model=MetadataSyncTaskRead)
def task(task_id:int,db:Session=Depends(get_db)):
    item=db.get(MetadataSyncTask,task_id)
    if item is None: raise HTTPException(404,"Metadata sync task not found")
    return item
