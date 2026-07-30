import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.observability import current_request_id
from app.models import BackgroundJob
from app.services.governance.audit import redact_summary


_SENSITIVE_KEY_PARTS = (
    "password", "passwd", "pwd", "token", "secret", "api_key", "credential",
    "authorization", "cookie", "connection_string", "database_url",
    "sqlalchemy_url", "prompt", "raw_sql", "knowledge_content", "raw_content",
    "document_content",
)


def semantic_idempotency_key(
    *,
    job_type: str,
    payload: dict[str, Any],
    target_resource_type: str | None = None,
    target_resource_id: int | str | None = None,
) -> str:
    """Return a stable opaque fingerprint without embedding governed content."""
    canonical = {
        "job_type": job_type,
        "target_resource_type": target_resource_type,
        "target_resource_id": target_resource_id,
        "payload": _semantic_value(payload),
    }
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def scoped_idempotency_key(
    *,
    institution_id: int | None,
    project_id: int | None,
    job_type: str,
    idempotency_key: str,
) -> str:
    value = f"{institution_id or 0}:{project_id or 0}:{job_type}:{idempotency_key}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_or_get_job(
    db: Session,
    *,
    job_type: str,
    institution_id: int | None,
    project_id: int | None,
    created_by: int,
    idempotency_key: str,
    payload_summary: dict[str, Any],
) -> tuple[BackgroundJob, bool]:
    """
    Insert behind the existing unique constraint and recover from a concurrent
    winner. The savepoint keeps the caller's transaction usable after conflict.
    """
    scoped_key = scoped_idempotency_key(
        institution_id=institution_id,
        project_id=project_id,
        job_type=job_type,
        idempotency_key=idempotency_key,
    )
    existing = db.scalar(select(BackgroundJob).where(BackgroundJob.idempotency_key == scoped_key))
    if existing is not None:
        setattr(existing, "submission_deduplicated", True)
        return existing, True

    job = BackgroundJob(
        institution_id=institution_id,
        project_id=project_id,
        idempotency_key=scoped_key,
        job_type=job_type,
        correlation_id=current_request_id(),
        status="queued",
        progress=0,
        payload_summary_json=redact_summary(payload_summary),
        result_summary_json={},
        created_by=created_by,
    )
    savepoint = db.begin_nested()
    try:
        db.add(job)
        db.flush()
    except IntegrityError:
        savepoint.rollback()
        db.expire_all()
        existing = db.scalar(select(BackgroundJob).where(BackgroundJob.idempotency_key == scoped_key))
        if existing is None:
            raise
        setattr(existing, "submission_deduplicated", True)
        return existing, True
    else:
        savepoint.commit()
        db.commit()
        db.refresh(job)
        setattr(job, "submission_deduplicated", False)
        return job, False


def _semantic_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _semantic_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if not any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS)
        }
    if isinstance(value, (list, tuple)):
        return [_semantic_value(item) for item in value]
    if isinstance(value, set):
        return sorted((_semantic_value(item) for item in value), key=str)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
