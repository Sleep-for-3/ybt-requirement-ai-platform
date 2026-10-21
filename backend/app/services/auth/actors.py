"""Resolve a persisted actor id for rows that require a ``users.id`` foreign key.

``AUTH_MODE=optional`` exposes an unauthenticated legacy principal
(``Principal(None, "legacy-system", ...)``).  Some tables — most notably
``background_jobs.created_by`` — declare a NOT NULL foreign key to ``users``, so
writing ``int(principal.user_id or 0)`` fails with a foreign-key violation and the
whole request 500s.  Development/demo flows must keep working without rewriting the
schema, therefore the legacy principal is materialised once as a real ``users`` row
and every later submission reuses it.

This module is intentionally small and dependency-light so that the task queue,
lineage ingestion and API layers can share it without import cycles.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User

LEGACY_SYSTEM_USERNAME = "legacy-system"


def ensure_actor_user_id(db: Session, actor_user_id: int | None) -> int:
    """Return ``actor_user_id`` or the id of the shared legacy system user.

    A missing actor is only accepted for the anonymous/legacy development principal;
    callers that genuinely have no user (e.g. an internal timer) also converge on the
    same stable row so the foreign key stays valid.
    """
    if actor_user_id:
        return int(actor_user_id)
    user = db.scalar(select(User).where(User.username == LEGACY_SYSTEM_USERNAME))
    if user is None:
        user = User(username=LEGACY_SYSTEM_USERNAME, display_name="Legacy system", status="active")
        db.add(user)
        db.flush()
    return user.id
