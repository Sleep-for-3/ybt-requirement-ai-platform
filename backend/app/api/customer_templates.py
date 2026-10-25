"""客户需求文档模板注册入口（P0-D）。

注册一次、导出多次：导出时给 ``template_id`` 即可，不必每次上传模板文件。
注册与导出使用同一份适配配置与同一套渲染器，因此注册时的支持范围结论与导出
结果一致。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.customer_template_store import (
    CustomerTemplateError,
    get_template,
    latest_by_name,
    list_templates,
    register_template,
    serialize,
)
from app.services.governance.audit import record_audit

router = APIRouter(tags=["customer templates"])


def _parse_config(raw: str | None) -> dict:
    if not raw:
        raise HTTPException(422, "模板适配配置不能为空，需要锚点或命名单元格映射。")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as failure:
        raise HTTPException(422, f"模板适配配置不是合法 JSON：{failure}") from failure
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(422, "模板适配配置必须是 JSON 对象。")
    return payload


@router.post("/projects/{project_id}/customer-templates", status_code=201)
def register_customer_template(project_id: int, principal: CurrentPrincipal,
                               db: Session = Depends(get_db),
                               name: str = Form(..., min_length=1, max_length=200),
                               format: str = Form("docx"),
                               template: UploadFile = File(...),
                               config: str | None = Form(None),
                               notes: str = Form("")):
    """注册客户模板（同名多次注册即多版本，内容与配置都相同则幂等返回旧版本）。"""

    PermissionService(db, principal).require_project_permission(project_id, "deliverable.export")
    payload = _parse_config(config)
    raw = template.file.read()
    try:
        row, created = register_template(
            db, project_id=project_id, name=name, format=format,
            file_name=template.filename or "", raw=raw, config=payload,
            notes=notes, renderer_version="customer-template-registry-v1",
            created_by=principal.user_id,
        )
    except CustomerTemplateError as failure:
        status = 413 if failure.code == "template_too_large" else 422
        raise HTTPException(status, f"{failure.message}（错误代码：{failure.code}）") from failure
    db.commit()
    if created:
        record_audit(db, action="register_customer_template", resource_type="customer_template",
                     resource_id=row.id, actor_user_id=principal.user_id, project_id=project_id,
                     after={"name": row.name, "version_no": row.version_no,
                            "format": row.format, "file_sha256": row.file_sha256,
                            "config_digest": row.config_digest})
        db.commit()
    return {"created": created, "template": serialize(row, with_config=True)}


@router.get("/projects/{project_id}/customer-templates")
def list_customer_templates(project_id: int, principal: CurrentPrincipal,
                            db: Session = Depends(get_db), name: str | None = None,
                            latest_only: bool = True):
    """列出已注册模板；``latest_only`` 每个名称只返回最新版本。"""

    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    rows = latest_by_name(db, project_id) if latest_only else list_templates(db, project_id, name=name)
    if latest_only and name:
        rows = [row for row in rows if row.name == name]
    return {"count": len(rows), "items": [serialize(row) for row in rows],
            "registry_version": "customer-template-registry-v1"}


@router.get("/projects/{project_id}/customer-templates/{template_id}")
def get_customer_template(project_id: int, template_id: int, principal: CurrentPrincipal,
                          db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    row = get_template(db, project_id, template_id)
    if row is None:
        raise HTTPException(404, "模板不存在或不属于该项目")
    return serialize(row, with_config=True)
