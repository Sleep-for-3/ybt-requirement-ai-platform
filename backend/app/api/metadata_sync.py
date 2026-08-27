from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import DataSource, MetadataDriftEvent, MetadataSyncTask, Project
from app.schemas import MetadataDriftEventRead, MetadataSyncRequest, MetadataSyncTaskRead
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.task_queue.domain_handlers import metadata_sync_handler
from app.services.task_queue.submission import submit_project_job
from app.services.task_queue.presentation import job_submission_response

router=APIRouter(tags=["metadata sync"])

@router.post("/datasources/{datasource_id}/metadata-sync")
def sync(datasource_id:int,payload:MetadataSyncRequest,principal:CurrentPrincipal,db:Session=Depends(get_db)):
    datasource=db.get(DataSource,datasource_id)
    if datasource is None: raise HTTPException(404,"Data source not found")
    project=PermissionService(db,principal).require_project_permission(datasource.project_id,"catalog.manage")
    job=submit_project_job(db,project,principal,job_type="metadata_sync",payload={"datasource_id":datasource.id,**payload.model_dump(mode="json")},handler=metadata_sync_handler)
    task_id=(job.result_summary_json or {}).get("metadata_sync_task_id")
    return db.get(MetadataSyncTask,int(task_id)) if task_id else _job(job)

@router.get("/datasources/{datasource_id}/metadata-sync-tasks",response_model=list[MetadataSyncTaskRead])
def tasks(datasource_id:int,principal:CurrentPrincipal,db:Session=Depends(get_db)):
    datasource=db.get(DataSource,datasource_id)
    if datasource is None: raise HTTPException(404,"Data source not found")
    PermissionService(db,principal).require_project_permission(datasource.project_id,"catalog.search")
    return list(db.scalars(select(MetadataSyncTask).where(MetadataSyncTask.datasource_id==datasource_id).order_by(MetadataSyncTask.id.desc())).all())

@router.get("/metadata-sync-tasks/{task_id}",response_model=MetadataSyncTaskRead)
def task(task_id:int,principal:CurrentPrincipal,db:Session=Depends(get_db)):
    item=db.get(MetadataSyncTask,task_id)
    if item is None: raise HTTPException(404,"Metadata sync task not found")
    PermissionService(db,principal).require_project_permission(item.project_id,"catalog.search")
    return item

@router.get("/metadata-sync-tasks/{task_id}/drift",response_model=list[MetadataDriftEventRead])
def drift(task_id:int,principal:CurrentPrincipal,offset:int=Query(0,ge=0),limit:int=Query(250,ge=1,le=1000),db:Session=Depends(get_db)):
    item=db.get(MetadataSyncTask,task_id)
    if item is None: raise HTTPException(404,"Metadata sync task not found")
    PermissionService(db,principal).require_project_permission(item.project_id,"catalog.search")
    return list(db.scalars(select(MetadataDriftEvent).where(MetadataDriftEvent.sync_task_id==task_id).order_by(MetadataDriftEvent.id.desc()).offset(offset).limit(limit)).all())

def _job(job):return job_submission_response(job)
