import json
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import BackgroundJob, ResourceImportBatch, ResourceImportItem
from app.services.auth.dependencies import RealPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.metadata import batch_import as service
from app.services.task_queue.factory import get_task_queue

router = APIRouter(prefix="/projects/{project_id}/resource-imports", tags=["resource imports"])


class Assignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database_name: str = Field(default="", max_length=255)
    schema_name: str = Field(default="", max_length=255)
    layer_key: str | None = Field(default=None, max_length=64)
    business_system_id: int | None = None
    catalog_table_id: int | None = None
    decision: Literal["preserve", "merge", "skip"] = "preserve"
    accept_incomplete: bool = False


class ImportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dialect: str = Field(default="", max_length=30)
    defaults: Assignment = Field(default_factory=Assignment)
    file_options: dict[str, Assignment] = Field(default_factory=dict, max_length=100)
    table_options: dict[str, Assignment] = Field(default_factory=dict, max_length=1000)

    def compact(self):
        return self.model_dump(exclude_unset=True)


class PreviewWrite(BaseModel):
    expected_version: int = Field(ge=1)
    options: ImportOptions


class ApplyRequest(BaseModel):
    expected_version: int = Field(ge=1)


def authorized(db, principal, project_id, write=False):
    permissions = PermissionService(db, principal)
    project = permissions.require_project_permission(project_id, "catalog.manage" if write else "catalog.search")
    if write:
        permissions.require_project_permission(project_id, "script.upload")
    return project


@router.post("", status_code=201)
async def upload(project_id: int, principal: RealPrincipal, files: list[UploadFile] = File(...),
                 idempotency_key: str = Form(..., min_length=1, max_length=100), options: str = Form("{}"),
                 db: Session = Depends(get_db)):
    project = authorized(db, principal, project_id, True)
    if len(files) > 100 or len(options) > 200000:
        raise HTTPException(422, "批次文件或配置数量超出限制")
    try:
        settings = ImportOptions.model_validate(json.loads(options)).compact()
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, "导入默认设置格式不正确") from exc
    content, total = [], 0
    for file in files:
        data = await file.read(10 * 1024 * 1024 + 1)
        total += len(data)
        if len(data) > 10 * 1024 * 1024 or total > 40 * 1024 * 1024:
            raise HTTPException(422, "上传文件超出大小限制")
        content.append((file.filename or "unknown", data))
    try:
        batch = service.create_batch(db, project, principal.user_id, idempotency_key, content, settings)
    except ValueError as exc:
        raise HTTPException(422, "文件路径或格式不受支持") from exc
    return service.summary(db, batch)


@router.get("")
def list_batches(project_id: int, principal: RealPrincipal, db: Session = Depends(get_db)):
    authorized(db, principal, project_id)
    rows = db.scalars(select(ResourceImportBatch).where(ResourceImportBatch.project_id == project_id)
        .order_by(ResourceImportBatch.id.desc()).limit(50))
    return [{"id": x.id, "status": x.status, "version": x.version, "job_id": x.job_id, "created_at": x.created_at} for x in rows]


@router.get("/{batch_id}")
def read(project_id: int, batch_id: int, principal: RealPrincipal, db: Session = Depends(get_db)):
    authorized(db, principal, project_id)
    return service.summary(db, service.load_batch(db, project_id, batch_id))


@router.put("/{batch_id}/preview")
def revise_preview(project_id: int, batch_id: int, payload: PreviewWrite, principal: RealPrincipal, db: Session = Depends(get_db)):
    authorized(db, principal, project_id, True)
    batch = service.load_batch(db, project_id, batch_id)
    options = payload.options.compact()
    if options.get("dialect", "") != batch.options_json.get("dialect", ""):
        raise HTTPException(422, "改变解析方言需要重新上传建立新批次")
    return service.summary(db, service.save_options(db, batch, payload.expected_version, options))


@router.post("/{batch_id}/apply")
def apply(project_id: int, batch_id: int, payload: ApplyRequest, principal: RealPrincipal, db: Session = Depends(get_db)):
    project = authorized(db, principal, project_id, True)
    batch = service.load_batch(db, project_id, batch_id)
    if batch.version != payload.expected_version:
        raise HTTPException(409, "预览版本已更新，请刷新后确认")
    if batch.status == "preview":
        if service.preview(db, batch) != batch.preview_json:
            raise HTTPException(409, "资产或架构已变化，请重新保存预览再确认")
        result = db.execute(update(ResourceImportBatch).where(ResourceImportBatch.id == batch.id,
            ResourceImportBatch.version == payload.expected_version, ResourceImportBatch.status == "preview").values(status="queued"))
        if result.rowcount != 1:
            raise HTTPException(409, "批次正在确认，请刷新")
        db.commit()
    # Stable queue key recovers a confirmation interrupted before enqueue.
    job = get_task_queue().enqueue(db, job_type="resource_batch_import", institution_id=project.institution_id,
        project_id=project_id, created_by=batch.created_by, idempotency_key=f"resource-import-{batch.id}-{batch.version}",
        payload_summary={"batch_id": batch.id, "preview_version": batch.version}, handler=service.batch_import_handler)
    db.refresh(batch)
    batch.job_id = job.id
    db.commit()
    return service.summary(db, batch)


@router.post("/{batch_id}/retry")
def retry(project_id: int, batch_id: int, principal: RealPrincipal, db: Session = Depends(get_db)):
    authorized(db, principal, project_id, True)
    batch = service.load_batch(db, project_id, batch_id)
    job = db.get(BackgroundJob, batch.job_id) if batch.job_id else None
    if job is None or job.project_id != project_id or job.job_type != "resource_batch_import":
        raise HTTPException(409, "没有可重试的导入任务")
    try:
        get_task_queue().retry(db, job)
    except ValueError as exc:
        raise HTTPException(409, "任务尚未结束或重试次数已用尽") from exc
    db.refresh(batch)
    return service.summary(db, batch)


@router.post("/{batch_id}/reopen")
def reopen(project_id: int, batch_id: int, principal: RealPrincipal, db: Session = Depends(get_db)):
    authorized(db, principal, project_id, True)
    batch = service.load_batch(db, project_id, batch_id)
    job = db.get(BackgroundJob, batch.job_id) if batch.job_id else None
    if not job or job.status not in {"failed", "partially_completed", "cancelled"}:
        raise HTTPException(409, "只有已结束的失败或部分失败批次可以调整")
    db.execute(update(ResourceImportBatch).where(ResourceImportBatch.id == batch.id)
        .values(status="preview", version=batch.version + 1, job_id=None))
    db.execute(update(ResourceImportItem).where(ResourceImportItem.batch_id == batch.id,
        ResourceImportItem.status == "failed").values(status="preview"))
    db.refresh(batch)
    batch.preview_json = service.preview(db, batch)
    db.commit()
    return service.summary(db, batch)
