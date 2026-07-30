from typing import Any

from sqlalchemy.orm import Session

from app.models import Project
from app.services.auth.dependencies import Principal
from app.services.governance.audit import record_audit
from app.services.task_queue.base import JobHandler
from app.services.task_queue.factory import get_task_queue
from app.services.task_queue.idempotency import semantic_idempotency_key


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
    queue = get_task_queue()
    base_key = idempotency_key or semantic_idempotency_key(
        job_type=job_type,
        payload=payload,
    )
    job = queue.enqueue(
        db,
        job_type=job_type,
        institution_id=project.institution_id,
        project_id=project.id,
        created_by=int(principal.user_id or 0),
        idempotency_key=base_key,
        payload_summary=payload,
        handler=handler,
    )
    # A POST after a terminal result is an explicit rerun. Walk the stable
    # predecessor chain so concurrent reruns converge on one successor while
    # later intentional reruns can still create another auditable job.
    for _ in range(100):
        if not getattr(job, "submission_deduplicated", False) or job.status in {"queued", "running"}:
            break
        predecessor_id = job.id
        successor_key = semantic_idempotency_key(
            job_type=job_type,
            payload={"base_key": base_key, "rerun_of_job_id": predecessor_id},
            target_resource_type="background_job",
            target_resource_id=predecessor_id,
        )
        job = queue.enqueue(
            db,
            job_type=job_type,
            institution_id=project.institution_id,
            project_id=project.id,
            created_by=int(principal.user_id or 0),
            idempotency_key=successor_key,
            payload_summary={**payload, "rerun_of_job_id": predecessor_id},
            handler=handler,
        )
    else:
        raise RuntimeError("Background job rerun chain limit reached")
    if not getattr(job, "submission_deduplicated", False):
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
