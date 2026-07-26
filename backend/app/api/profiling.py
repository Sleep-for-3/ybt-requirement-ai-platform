from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import CandidateSourceRecommendation,CatalogColumn,ColumnProfileSnapshot,ColumnProfileTask
from app.schemas import ColumnProfileRequest,ColumnProfileSnapshotRead,ColumnProfileTaskRead,ProfileEvidenceBindRequest,MappingEvidenceRead
from app.services.metadata.profile_service import bind_profile_evidence
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.task_queue.domain_handlers import column_profile_handler
from app.services.task_queue.submission import submit_project_job
router=APIRouter(tags=["column profiling"])
@router.post("/catalog/columns/{column_id}/profile")
def profile(column_id:int,payload:ColumnProfileRequest,principal:CurrentPrincipal,db:Session=Depends(get_db)):
    column=db.get(CatalogColumn,column_id)
    if column is None:raise HTTPException(404,"Catalog column not found")
    recommendation=db.get(CandidateSourceRecommendation,payload.source_recommendation_id)
    if recommendation is None or not recommendation.selected_flag:raise HTTPException(400,"Source recommendation must be selected before profiling")
    if recommendation.catalog_column_id!=column.id or recommendation.target_field_id!=payload.target_field_id or recommendation.scenario_id!=payload.scenario_id:raise HTTPException(400,"Selected recommendation does not match the requested catalog field and scenario")
    project=PermissionService(db,principal).require_project_permission(column.project_id,"profile.request")
    job=submit_project_job(db,project,principal,job_type="column_profile",payload={"column_id":column.id,"request":payload.model_dump(mode="json")},handler=column_profile_handler)
    task_id=(job.result_summary_json or {}).get("profile_task_id")
    return db.get(ColumnProfileTask,int(task_id)) if task_id else _job(job)
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

def _job(job):return {column.key:getattr(job,column.key) for column in job.__table__.columns}
