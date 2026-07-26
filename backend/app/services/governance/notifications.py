from sqlalchemy.orm import Session

from app.models import Notification


def notify_user(
    db: Session,
    user_id: int | None,
    notification_type: str,
    title: str,
    content: str,
    *,
    project_id: int | None = None,
    resource_type: str | None = None,
    resource_id: int | str | None = None,
) -> Notification | None:
    if user_id is None:
        return None
    notification = Notification(
        user_id=user_id,
        project_id=project_id,
        notification_type=notification_type,
        title=title[:255],
        content=content[:2000],
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
    )
    db.add(notification)
    return notification
