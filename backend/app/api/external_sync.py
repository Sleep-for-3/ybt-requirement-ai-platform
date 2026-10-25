"""P2-B 外部增量同步入口：事件提交、待复核列表、游标查询。

与 ``metadata_sync`` 的区别：那边是平台主动连数据源做内省与漂移对比；这里是接收
外部系统按游标推送的事件，裁决结果**只产生待复核**，不直接改需求或正式交付。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService
from app.services.external_sync_store import (
    ExternalSyncError,
    ingest_events,
    list_cursors,
    list_pending,
    serialize,
)

router = APIRouter(tags=["external sync"])


@router.post("/projects/{project_id}/external-sync/events", status_code=201)
def submit_external_events(project_id: int, payload: dict[str, Any], principal: CurrentPrincipal,
                           db: Session = Depends(get_db)):
    """提交一批外部事件（按游标分批，单批 ≤ 200 条）。

    重复/乱序/重放**不写入**待复核列表，只在响应里报告；新版本、删除、权限变化
    一律落为 ``pending_review`` 类状态，由人复核后再走需求修订流程。
    """

    PermissionService(db, principal).require_project_permission(project_id, "technical.edit")
    events = payload.get("events")
    if not isinstance(events, list):
        raise HTTPException(422, "请求体必须包含 events 数组")
    try:
        plan = ingest_events(db, project_id=project_id, events=events, created_by=principal.user_id)
    except ExternalSyncError as exc:
        raise HTTPException(422, exc.message) from exc
    db.commit()
    return plan


@router.get("/projects/{project_id}/external-sync/pending")
def pending_external_events(project_id: int, principal: CurrentPrincipal,
                            source: str | None = Query(default=None),
                            limit: int = Query(default=100, ge=1, le=200),
                            db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    rows = list_pending(db, project_id=project_id, source=source, limit=limit)
    return {"project_id": project_id, "count": len(rows), "items": [serialize(row) for row in rows]}


@router.get("/projects/{project_id}/external-sync/cursors")
def external_sync_cursors(project_id: int, principal: CurrentPrincipal, db: Session = Depends(get_db)):
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    rows = list_cursors(db, project_id=project_id)
    return {
        "project_id": project_id,
        "items": [
            {
                "source": row.source,
                "cursor": int(row.cursor or 0),
                "last_observed_at": row.last_observed_at,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ],
    }
