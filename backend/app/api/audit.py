from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import AuditLog
from app.services.auth.dependencies import RealPrincipal
from app.services.auth.permission_service import PermissionService


router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
def search_audit_logs(
    principal: RealPrincipal,
    project_id: int | None = None,
    actor_user_id: int | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[dict]:
    permissions = PermissionService(db, principal)
    statement = select(AuditLog)
    if project_id is not None:
        permissions.require_project_permission(project_id, "audit.read")
        statement = statement.where(AuditLog.project_id == project_id)
    elif not permissions.is_platform_admin():
        visible = permissions.visible_project_ids() or []
        allowed = []
        for candidate in visible:
            try:
                permissions.require_project_permission(candidate, "audit.read")
                allowed.append(candidate)
            except Exception:
                continue
        statement = statement.where(AuditLog.project_id.in_(allowed))
    if actor_user_id is not None: statement = statement.where(AuditLog.actor_user_id == actor_user_id)
    if action: statement = statement.where(AuditLog.action == action)
    if resource_type: statement = statement.where(AuditLog.resource_type == resource_type)
    if created_from: statement = statement.where(AuditLog.created_at >= created_from)
    if created_to: statement = statement.where(AuditLog.created_at <= created_to)
    rows = db.scalars(statement.order_by(AuditLog.id.desc()).limit(min(max(limit, 1), 500))).all()
    return [{column.key: getattr(row, column.key) for column in row.__table__.columns} for row in rows]
