import asyncio
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import BackgroundJob, BackgroundJobItem, Project, ScenarioBusinessMapping, ScenarioTechnicalLineage, StoredFile, TargetField
from app.schemas.governance import BatchOperationRequest, BatchReviewJobRequest
from app.services.auth.dependencies import RealPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.governance.audit import record_audit
from app.services.governance.notifications import notify_user
from app.services.mapping.scenario_draft_generator import generate_business_draft, generate_technical_draft
from app.services.governance.workflow import start_workflow
from app.services.governance.scenario_review import get_or_create_review_package
from app.services.export import export_traceability_workbook
from app.services.storage import get_storage_service
from app.services.task_queue import get_task_queue
from app.services.task_queue.domain_handlers import project_backup_handler


router = APIRouter(tags=["background jobs"])


@router.get("/jobs")
def list_jobs(principal: RealPrincipal, project_id: int | None = None, db: Session = Depends(get_db)) -> list[dict]:
    statement = select(BackgroundJob).order_by(BackgroundJob.id.desc()).limit(200)
    if project_id is not None:
        PermissionService(db, principal).require_project_permission(project_id, "project.view")
        statement = statement.where(BackgroundJob.project_id == project_id)
    elif not PermissionService(db, principal).is_platform_admin():
        visible = PermissionService(db, principal).visible_project_ids() or []
        statement = statement.where(BackgroundJob.project_id.in_(visible))
    return [_job_dict(job) for job in db.scalars(statement).all()]


@router.get("/jobs/{job_id}")
def get_job(job_id: int, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    job = _job_or_404(db, job_id)
    if job.project_id is not None:
        PermissionService(db, principal).require_project_permission(job.project_id, "project.view")
    items = db.scalars(select(BackgroundJobItem).where(BackgroundJobItem.background_job_id == job.id).order_by(BackgroundJobItem.id)).all()
    result = _job_dict(job)
    result["items"] = [{column.key: getattr(item, column.key) for column in item.__table__.columns} for item in items]
    return result


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    job = _job_or_404(db, job_id)
    if job.project_id is not None: PermissionService(db, principal).require_project_permission(job.project_id, "task.manage")
    try: return _job_dict(get_task_queue().cancel(db, job))
    except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: int, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    job = _job_or_404(db, job_id)
    if job.project_id is not None: PermissionService(db, principal).require_project_permission(job.project_id, "task.manage")
    try: return _job_dict(get_task_queue().retry(db, job))
    except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/projects/{project_id}/batch/generate-business-drafts", status_code=status.HTTP_202_ACCEPTED)
def batch_business(project_id: int, payload: BatchOperationRequest, principal: RealPrincipal, db: Session = Depends(get_db), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict:
    return _enqueue(db, project_id, principal, "batch_ai_generation_business", payload.model_dump(mode="json"), idempotency_key, _business_handler)


@router.post("/projects/{project_id}/batch/generate-technical-drafts", status_code=status.HTTP_202_ACCEPTED)
def batch_technical(project_id: int, payload: BatchOperationRequest, principal: RealPrincipal, db: Session = Depends(get_db), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict:
    return _enqueue(db, project_id, principal, "batch_ai_generation_technical", payload.model_dump(mode="json"), idempotency_key, _technical_handler)


@router.post("/projects/{project_id}/batch/create-review-tasks", status_code=status.HTTP_202_ACCEPTED)
def batch_review_tasks(project_id: int, payload: BatchReviewJobRequest, principal: RealPrincipal, db: Session = Depends(get_db), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict:
    return _enqueue(db, project_id, principal, "batch_review_tasks", payload.model_dump(mode="json"), idempotency_key, _review_task_handler)


@router.post("/projects/{project_id}/batch/export-traceability-workbook", status_code=status.HTTP_202_ACCEPTED)
def batch_export(project_id: int, payload: BatchOperationRequest, principal: RealPrincipal, db: Session = Depends(get_db), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict:
    PermissionService(db, principal).require_project_permission(project_id, "export")
    return _enqueue(db, project_id, principal, "excel_export", payload.model_dump(mode="json"), idempotency_key, _export_handler)


@router.post("/projects/{project_id}/backup", status_code=status.HTTP_202_ACCEPTED)
def project_backup(project_id: int, principal: RealPrincipal, db: Session = Depends(get_db), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict:
    return _enqueue(db, project_id, principal, "project_backup", {}, idempotency_key, project_backup_handler)


def _enqueue(db, project_id, principal, job_type, payload, idempotency_key, handler):
    project = PermissionService(db, principal).require_project_permission(project_id, "task.manage")
    job = get_task_queue().enqueue(db, job_type=job_type, institution_id=project.institution_id, project_id=project.id, created_by=principal.user_id, idempotency_key=idempotency_key or uuid.uuid4().hex, payload_summary=payload, handler=handler)
    record_audit(db, action="create", resource_type="background_job", resource_id=job.id, actor_user_id=principal.user_id, institution_id=project.institution_id, project_id=project.id, after={"job_type": job_type, "status": job.status})
    db.commit()
    return _job_dict(job)


def _business_handler(db: Session, job: BackgroundJob) -> dict:
    return _draft_handler(db, job, ScenarioBusinessMapping, generate_business_draft)


def _technical_handler(db: Session, job: BackgroundJob) -> dict:
    return _draft_handler(db, job, ScenarioTechnicalLineage, generate_technical_draft)


def _review_task_handler(db: Session, job: BackgroundJob) -> dict:
    payload=job.payload_summary_json;success=0;failed=0
    for target in payload.get("targets",[]):
        if _job_cancelled(db, job): break
        key=f"{target.get('target_field_id') or target.get('target_type')}:{target.get('scenario_id') or target.get('target_id')}"
        try:
            if payload["workflow_key"] == "scenario_mapping_review":
                package=get_or_create_review_package(db,project_id=job.project_id,target_field_id=int(target["target_field_id"]),scenario_id=int(target["scenario_id"]),created_by=job.created_by)
                target_type,target_id="scenario_review_package",package.id
            else:
                target_type,target_id=target["target_type"],int(target["target_id"])
            instance=start_workflow(db,project_id=job.project_id,workflow_key=payload["workflow_key"],target_type=target_type,target_id=target_id,created_by=job.created_by,assignments={key:int(value) for key,value in payload.get("assignments",{}).items()},due_at=payload.get("due_at"));success+=1
            db.add(BackgroundJobItem(background_job_id=job.id,item_key=key,status="completed",result_summary_json={"workflow_instance_id":instance.id}));db.commit()
        except Exception as exc:
            db.rollback();job=db.get(BackgroundJob,job.id);failed+=1;db.add(BackgroundJobItem(background_job_id=job.id,item_key=key,status="failed",result_summary_json={},error_message=str(exc)[:1000]));db.commit()
    notify_user(db,job.created_by,"batch_generation_completed","批量审核任务已创建",f"成功 {success}，失败 {failed}",project_id=job.project_id,resource_type="background_job",resource_id=job.id);db.commit()
    return {"success_count":success,"failed_count":failed,"total_count":success+failed}


def _export_handler(db: Session, job: BackgroundJob) -> dict:
    project=db.get(Project,job.project_id);content=export_traceability_workbook(db,job.project_id,job.payload_summary_json.get("target_table_id"));file_name=f"{project.name}-业务口径及技术溯源表.xlsx";saved=get_storage_service().save(content,file_name=file_name,project_id=project.id)
    row=StoredFile(institution_id=project.institution_id,project_id=project.id,storage_key=saved.storage_key,original_file_name=file_name,content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",byte_size=saved.byte_size,content_hash=saved.content_hash,classification=project.confidentiality_level,created_by=job.created_by,enabled=True);db.add(row);db.flush();db.add(BackgroundJobItem(background_job_id=job.id,item_key="workbook",status="completed",result_summary_json={"file_id":row.id,"byte_size":row.byte_size}));record_audit(db,action="export",resource_type="traceability_workbook",resource_id=row.id,actor_user_id=job.created_by,institution_id=project.institution_id,project_id=project.id,after={"file_name":file_name,"background_job_id":job.id});notify_user(db,job.created_by,"export_completed","Excel 导出完成",file_name,project_id=project.id,resource_type="stored_file",resource_id=row.id);db.commit();return {"success_count":1,"failed_count":0,"file_id":row.id,"byte_size":row.byte_size}


def _draft_handler(db, job, model, generator):
    field_ids = list(job.payload_summary_json.get("field_ids") or [])
    statement = select(model).where(model.project_id == job.project_id)
    if field_ids: statement = statement.where(model.target_field_id.in_(field_ids))
    rows = list(db.scalars(statement).all());success=0;failed=0
    for row in rows:
        if _job_cancelled(db, job): break
        try:
            asyncio.run(generator(db, row.id));success += 1
            db.add(BackgroundJobItem(background_job_id=job.id, item_key=str(row.id), status="completed", result_summary_json={"mapping_id": row.id}));db.commit()
        except Exception as exc:
            db.rollback();job=db.get(BackgroundJob,job.id);failed += 1
            db.add(BackgroundJobItem(background_job_id=job.id, item_key=str(row.id), status="failed", result_summary_json={}, error_message=str(exc)[:1000]));db.commit()
    notify_user(db,job.created_by,"batch_generation_completed","批量草稿生成完成",f"成功 {success}，失败 {failed}",project_id=job.project_id,resource_type="background_job",resource_id=job.id);db.commit()
    return {"success_count": success, "failed_count": failed, "total_count": len(rows)}


def _job_cancelled(db: Session, job: BackgroundJob) -> bool:
    db.expire(job)
    db.refresh(job)
    return job.status == "cancelled"


def _job_or_404(db, job_id):
    job=db.get(BackgroundJob,job_id)
    if job is None: raise HTTPException(status_code=404,detail="Background job not found")
    return job


def _job_dict(job): return {column.key:getattr(job,column.key) for column in job.__table__.columns}
