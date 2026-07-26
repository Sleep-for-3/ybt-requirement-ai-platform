from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Notification, ReviewTask
from app.services.auth.dependencies import RealPrincipal


router = APIRouter(tags=["notifications"])


@router.get("/me/notifications")
def list_notifications(principal: RealPrincipal, unread_only: bool = False, db: Session = Depends(get_db)) -> list[dict]:
    due_before = datetime.now(UTC) + timedelta(hours=24)
    due_tasks = db.scalars(select(ReviewTask).where(
        ReviewTask.assignee_user_id == principal.user_id,
        ReviewTask.status.in_(["pending", "claimed", "returned"]),
        ReviewTask.due_at.is_not(None),
        ReviewTask.due_at <= due_before,
    )).all()
    for task in due_tasks:
        exists = db.scalar(select(Notification.id).where(
            Notification.user_id == principal.user_id,
            Notification.notification_type == "task_due_soon",
            Notification.resource_type == "review_task",
            Notification.resource_id == str(task.id),
        ))
        if not exists:
            db.add(Notification(user_id=principal.user_id,project_id=task.project_id,notification_type="task_due_soon",title="任务即将到期",content=f"审核任务 {task.id} 即将到期",resource_type="review_task",resource_id=str(task.id)))
    db.commit()
    statement = select(Notification).where(Notification.user_id == principal.user_id)
    if unread_only:
        statement = statement.where(Notification.read_at.is_(None))
    rows = db.scalars(statement.order_by(Notification.id.desc()).limit(200)).all()
    return [{column.key: getattr(row, column.key) for column in row.__table__.columns} for row in rows]


@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: int, principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != principal.user_id:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.read_at = datetime.now(UTC)
    db.commit()
    return {"status": "read"}


@router.post("/notifications/read-all")
def mark_all_read(principal: RealPrincipal, db: Session = Depends(get_db)) -> dict:
    result = db.execute(update(Notification).where(Notification.user_id == principal.user_id, Notification.read_at.is_(None)).values(read_at=datetime.now(UTC)))
    db.commit()
    return {"updated": result.rowcount}
