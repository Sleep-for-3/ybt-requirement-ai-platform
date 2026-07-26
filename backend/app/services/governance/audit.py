from typing import Any
import re

from sqlalchemy.orm import Session

from app.models import AuditLog
from app.services.security import redact_content


SENSITIVE_KEYS = ("password", "passwd", "pwd", "token", "secret", "api_key", "credential", "authorization", "cookie", "connection_string", "sqlalchemy_url", "database_url", "raw_sql", "knowledge_content", "raw_content", "document_content")
_SAFE_STORAGE_KEY = re.compile(r"projects/\d+/[0-9a-f]{2}/[0-9a-f]{64}(?:\.[A-Za-z0-9]+)?")
_SAFE_HASH = re.compile(r"[0-9a-f]{32,128}")


def redact_summary(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key_text = str(key)
            key_lower = key_text.lower()
            if any(fragment in key_lower for fragment in SENSITIVE_KEYS):
                continue
            if key_lower == "storage_key" and isinstance(item, str) and _SAFE_STORAGE_KEY.fullmatch(item):
                result[key_text] = item
            elif key_lower.endswith("_hash") and isinstance(item, str) and _SAFE_HASH.fullmatch(item):
                result[key_text] = item
            else:
                result[key_text] = redact_summary(item)
        return result
    if isinstance(value, list):
        return [redact_summary(item) for item in value[:100]]
    if isinstance(value, str):
        return redact_content(value[:2000])
    return value


def record_audit(
    db: Session,
    *,
    action: str,
    resource_type: str,
    resource_id: int | str | None = None,
    actor_user_id: int | None = None,
    institution_id: int | None = None,
    project_id: int | None = None,
    request_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    result: str = "success",
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    from app.core.observability import current_request_id

    correlation_id = request_id or current_request_id()
    log = AuditLog(
        institution_id=institution_id,
        project_id=project_id,
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        request_id=correlation_id,
        correlation_id=correlation_id,
        before_summary_json=redact_summary(before or {}),
        after_summary_json=redact_summary(after or {}),
        result=result,
        ip_address_masked=_mask_ip(ip_address),
        user_agent_summary=(user_agent or "")[:255] or None,
    )
    db.add(log)
    return log


def _mask_ip(value: str | None) -> str | None:
    if not value:
        return None
    if ":" in value:
        parts = value.split(":")
        return ":".join(parts[:3]) + "::/48"
    parts = value.split(".")
    return ".".join(parts[:3] + ["0/24"]) if len(parts) == 4 else "masked"
