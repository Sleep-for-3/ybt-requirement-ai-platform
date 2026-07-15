import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import Project
from app.services.auth.dependencies import Principal
from app.services.governance.audit import record_audit
from app.services.task_queue.base import JobHandler
from app.services.task_queue.factory import get_task_queue


def submit_project_job(
    db: Session,
    project: Project,
    principal: Principal,
    *,
    job_type: str,
    payload: dict[str, Any],
    handler: JobHandler,
    idempotency_key: str | None = None,
):
    job = get_task_queue().enqueue(
        db,
        job_type=job_type,
        institution_id=project.institution_id,
        project_id=project.id,
        created_by=int(principal.user_id or 0),
        idempotency_key=idempotency_key or uuid.uuid4().hex,
        payload_summary=payload,
        handler=handler,
    )
    record_audit(
        db,
        action="create",
        resource_type="background_job",
        resource_id=job.id,
        actor_user_id=principal.user_id,
        institution_id=project.institution_id,
        project_id=project.id,
        after={"job_type": job_type, "status": job.status},
    )
    db.commit()
    return job
