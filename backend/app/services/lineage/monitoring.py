"""Controlled, auditable polling for configured lineage repositories.

This module is intentionally a scheduler boundary, not another ingestion
implementation.  A due monitor only enqueues the existing
``script_repository_sync`` background job, so repository allowlists, safe Git
flags, file budgets, parser isolation, change classification and review gates
remain centralized in the existing sync pipeline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BackgroundJob, CodeRepository
from app.services.governance.audit import record_audit
from app.services.lineage.ingestion import ensure_actor_user_id
from app.services.lineage.jobs import script_repository_sync_handler
from app.services.security import redact_content
from app.services.task_queue import get_task_queue
from app.services.task_queue.base import TaskQueue
from app.services.task_queue.idempotency import semantic_idempotency_key


MIN_POLL_INTERVAL_MINUTES = 5
MAX_POLL_INTERVAL_MINUTES = 10_080
DEFAULT_SWEEP_LIMIT = 100
MAX_SWEEP_LIMIT = 500
ACTIVE_JOB_STATUSES = {"queued", "running"}


@dataclass(frozen=True)
class RepositoryMonitorSweepResult:
    checked_count: int
    enqueued_count: int
    skipped_active_count: int
    failed_count: int
    repository_ids: tuple[int, ...]
    job_ids: tuple[int, ...]
    failures: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def configure_repository_monitor(
    repository: CodeRepository,
    *,
    enabled: bool,
    poll_interval_minutes: int,
    run_immediately: bool = False,
    now: datetime | None = None,
) -> CodeRepository:
    """Apply monitor configuration without performing external I/O."""

    interval = int(poll_interval_minutes)
    if not MIN_POLL_INTERVAL_MINUTES <= interval <= MAX_POLL_INTERVAL_MINUTES:
        raise ValueError(
            f"Polling interval must be between {MIN_POLL_INTERVAL_MINUTES} "
            f"and {MAX_POLL_INTERVAL_MINUTES} minutes"
        )
    current = _utc(now)
    repository.monitor_enabled = bool(enabled)
    repository.poll_interval_minutes = interval
    repository.next_poll_at = (
        current if run_immediately else current + timedelta(minutes=interval)
    ) if enabled else None
    if not enabled:
        repository.last_monitor_error = None
    return repository


def enqueue_repository_sync_job(
    db: Session,
    repository: CodeRepository,
    *,
    actor_user_id: int | None,
    trigger_type: str,
    scheduled_for: datetime | None = None,
    queue: TaskQueue | None = None,
) -> BackgroundJob:
    """Enqueue one repository sync with a content-free idempotency key."""

    if not repository.enabled:
        raise ValueError("Code repository is disabled")
    if trigger_type not in {"manual", "monitor_manual", "scheduled_poll"}:
        raise ValueError("Unsupported repository sync trigger")
    actor_id = ensure_actor_user_id(db, actor_user_id or repository.created_by)
    due_at = _utc(scheduled_for)
    payload = {
        "repository_id": repository.id,
        "branch": repository.default_branch,
        "last_sync_commit": repository.last_sync_commit,
        "trigger_type": trigger_type,
    }
    key_payload = dict(payload)
    if trigger_type != "manual":
        # The due slot makes each interval independently auditable while
        # concurrent sweepers still converge on the same background job.
        key_payload["scheduled_for"] = due_at.isoformat()
        payload["scheduled_for"] = due_at.isoformat()
    selected_queue = queue or get_task_queue()
    job = selected_queue.enqueue(
        db,
        job_type="script_repository_sync",
        institution_id=repository.institution_id,
        project_id=repository.project_id,
        created_by=actor_id,
        idempotency_key=semantic_idempotency_key(
            job_type="script_repository_sync",
            target_resource_type="code_repository",
            target_resource_id=repository.id,
            payload=key_payload,
        ),
        payload_summary=payload,
        handler=script_repository_sync_handler,
    )
    if trigger_type != "manual":
        repository.last_monitor_job_id = job.id
        repository.last_monitor_checked_at = due_at
        repository.last_monitor_error = None
    return job


def run_due_repository_monitors(
    db: Session,
    *,
    now: datetime | None = None,
    project_id: int | None = None,
    actor_user_id: int | None = None,
    limit: int = DEFAULT_SWEEP_LIMIT,
    queue: TaskQueue | None = None,
) -> RepositoryMonitorSweepResult:
    """Lock and enqueue due monitors, returning a compact operational result."""

    current = _utc(now)
    capped_limit = min(max(int(limit), 1), MAX_SWEEP_LIMIT)
    statement = select(CodeRepository).where(
        CodeRepository.enabled.is_(True),
        CodeRepository.monitor_enabled.is_(True),
        CodeRepository.next_poll_at.is_not(None),
        CodeRepository.next_poll_at <= current,
    )
    if project_id is not None:
        statement = statement.where(CodeRepository.project_id == int(project_id))
    statement = statement.order_by(CodeRepository.next_poll_at, CodeRepository.id).limit(capped_limit)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    repositories = list(db.scalars(statement).all())

    enqueued_repository_ids: list[int] = []
    job_ids: list[int] = []
    failures: list[dict[str, Any]] = []
    skipped_active = 0
    selected_queue = queue or get_task_queue()
    for repository in repositories:
        due_at = _utc(repository.next_poll_at)
        last_job = _scoped_monitor_job(db, repository)
        if last_job is not None and last_job.status in ACTIVE_JOB_STATUSES:
            skipped_active += 1
            # Avoid hammering an active repository on every scheduler tick.
            repository.next_poll_at = current + timedelta(minutes=1)
            db.commit()
            continue
        try:
            repository.next_poll_at = current + timedelta(minutes=repository.poll_interval_minutes)
            job = enqueue_repository_sync_job(
                db,
                repository,
                actor_user_id=actor_user_id,
                trigger_type="scheduled_poll",
                scheduled_for=due_at,
                queue=selected_queue,
            )
            record_audit(
                db,
                action="lineage_monitor_poll",
                resource_type="code_repository",
                resource_id=repository.id,
                actor_user_id=job.created_by,
                institution_id=repository.institution_id,
                project_id=repository.project_id,
                after={
                    "background_job_id": job.id,
                    "scheduled_for": due_at.isoformat(),
                    "next_poll_at": repository.next_poll_at,
                },
            )
            db.commit()
            enqueued_repository_ids.append(repository.id)
            job_ids.append(job.id)
        except Exception as exc:  # scheduler boundary: isolate one repository
            db.rollback()
            repository = db.get(CodeRepository, repository.id)
            if repository is not None:
                repository.last_monitor_checked_at = current
                repository.last_monitor_error = redact_content(str(exc)[:2000])
                repository.next_poll_at = current + timedelta(
                    minutes=min(max(repository.poll_interval_minutes, 1), 15)
                )
                record_audit(
                    db,
                    action="lineage_monitor_poll",
                    resource_type="code_repository",
                    resource_id=repository.id,
                    actor_user_id=actor_user_id or repository.created_by,
                    institution_id=repository.institution_id,
                    project_id=repository.project_id,
                    after={"error": repository.last_monitor_error},
                    result="failed",
                )
                db.commit()
            failures.append({
                "repository_id": repository.id if repository is not None else None,
                "error": redact_content(str(exc)[:500]),
            })

    return RepositoryMonitorSweepResult(
        checked_count=len(repositories),
        enqueued_count=len(job_ids),
        skipped_active_count=skipped_active,
        failed_count=len(failures),
        repository_ids=tuple(enqueued_repository_ids),
        job_ids=tuple(job_ids),
        failures=tuple(failures),
    )


def repository_monitor_status(db: Session, repository: CodeRepository) -> dict[str, Any]:
    """Project-scoped status projection used by repository APIs."""

    job = _scoped_monitor_job(db, repository)
    error = repository.last_monitor_error
    if job is not None and job.status == "failed" and job.error_message:
        error = redact_content(job.error_message[:2000])
    return {
        "enabled": bool(repository.monitor_enabled),
        "poll_interval_minutes": int(repository.poll_interval_minutes or 60),
        "next_poll_at": repository.next_poll_at,
        "last_checked_at": repository.last_monitor_checked_at,
        "last_job_id": job.id if job is not None else None,
        "last_job_status": job.status if job is not None else None,
        "last_error": error,
    }


def _scoped_monitor_job(db: Session, repository: CodeRepository) -> BackgroundJob | None:
    if repository.last_monitor_job_id is None:
        return None
    job = db.get(BackgroundJob, repository.last_monitor_job_id)
    if (
        job is None
        or job.project_id != repository.project_id
        or job.institution_id != repository.institution_id
        or job.job_type != "script_repository_sync"
        or int((job.payload_summary_json or {}).get("repository_id", -1)) != repository.id
    ):
        return None
    return job


def _utc(value: datetime | None) -> datetime:
    result = value or datetime.now(UTC)
    if result.tzinfo is None:
        return result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


__all__ = [
    "RepositoryMonitorSweepResult",
    "configure_repository_monitor",
    "enqueue_repository_sync_job",
    "repository_monitor_status",
    "run_due_repository_monitors",
]
