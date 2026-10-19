from datetime import date, datetime, time
from typing import Any
import hashlib
import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog
from app.services.security import redact_content


SENSITIVE_KEYS = ("password", "passwd", "pwd", "token", "secret", "api_key", "credential", "authorization", "cookie", "connection_string", "sqlalchemy_url", "database_url", "raw_sql", "knowledge_content", "raw_content", "document_content")
_SAFE_STORAGE_KEY = re.compile(r"projects/\d+/[0-9a-f]{2}/[0-9a-f]{64}(?:\.[A-Za-z0-9]+)?")
_SAFE_HASH = re.compile(r"[0-9a-f]{32,128}")

# ④ Audit hash chain.  ``prev_hash``/``entry_hash`` are appended by
# :func:`record_audit`; the digest covers only values the caller supplied, so no
# flush is needed before the row can be hashed.
CHAIN_GLOBAL_SCOPE = "__global__"
CHAIN_SCHEMA_VERSION = 1
CHAIN_PAYLOAD_SEPARATOR = "\x1f"


def audit_chain_scope(institution_id: int | None) -> str:
    """Return the chain key for one row.

    The chain is split per institution: that is the tenant boundary the audit
    trail is read and exported along, and it keeps concurrent writes in
    different institutions from competing for the same chain tail.  Rows with
    no institution (platform and system level) form their own chain instead of
    being folded into a tenant, so an operator action can never be mistaken for
    part of a customer's chain.
    """

    if institution_id is None:
        return CHAIN_GLOBAL_SCOPE
    return f"institution:{int(institution_id)}"


def canonical_entry_payload(
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    actor_user_id: int | None = None,
    institution_id: int | None = None,
    project_id: int | None = None,
    request_id: str | None = None,
    before_summary: Any = None,
    after_summary: Any = None,
    result: str = "success",
    ip_address_masked: str | None = None,
    user_agent_summary: str | None = None,
) -> str:
    """Deterministic serialization of the fields covered by the digest.

    ``json.dumps`` with sorted keys and compact separators pins the byte
    representation: the same audit entry always produces the same payload on
    any machine and Python version.  ``default=str`` keeps exotic values (for
    example a date that survived redaction) from raising instead of hashing.
    """

    payload = {
        "schema_version": CHAIN_SCHEMA_VERSION,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "actor_user_id": actor_user_id,
        "institution_id": institution_id,
        "project_id": project_id,
        "request_id": request_id,
        "before_summary": before_summary if before_summary is not None else {},
        "after_summary": after_summary if after_summary is not None else {},
        "result": result,
        "ip_address_masked": ip_address_masked,
        "user_agent_summary": user_agent_summary,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def compute_entry_hash(payload: str, prev_hash: str | None = None) -> str:
    """Digest of one canonical payload, chained to the preceding entry hash."""

    material = f"{prev_hash or ''}{CHAIN_PAYLOAD_SEPARATOR}{payload}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _chain_tail_hash(db: Session, institution_id: int | None) -> str | None:
    """Hash of the newest same-chain entry.

    The lookup is one indexed row (``ix_audit_logs_chain_tail`` on
    ``(institution_id, id)``), never a table scan.  Rows queued in the current
    session but not yet flushed are preferred, because they will receive higher
    ids than everything already stored.
    """

    pending = [
        item
        for item in db.new
        if isinstance(item, AuditLog) and item.institution_id == institution_id and item.entry_hash
    ]
    if pending:
        return pending[-1].entry_hash
    statement = select(AuditLog.entry_hash).where(AuditLog.entry_hash.is_not(None))
    if institution_id is None:
        statement = statement.where(AuditLog.institution_id.is_(None))
    else:
        statement = statement.where(AuditLog.institution_id == institution_id)
    return db.scalar(statement.order_by(AuditLog.id.desc()).limit(1))


def _chain_hashes(
    db: Session,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None,
    actor_user_id: int | None,
    institution_id: int | None,
    project_id: int | None,
    request_id: str | None,
    before_summary: Any,
    after_summary: Any,
    result: str,
    ip_address_masked: str | None,
    user_agent_summary: str | None,
) -> tuple[str | None, str | None]:
    """Return ``(prev_hash, entry_hash)`` for a new entry, or two Nones."""

    from app.core.settings import get_settings

    if not get_settings().audit_chain_enabled:
        return None, None
    prev_hash = _chain_tail_hash(db, institution_id)
    payload = canonical_entry_payload(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_user_id=actor_user_id,
        institution_id=institution_id,
        project_id=project_id,
        request_id=request_id,
        before_summary=before_summary,
        after_summary=after_summary,
        result=result,
        ip_address_masked=ip_address_masked,
        user_agent_summary=user_agent_summary,
    )
    return prev_hash, compute_entry_hash(payload, prev_hash)


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
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
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
    before_summary = redact_summary(before or {})
    after_summary = redact_summary(after or {})
    ip_address_masked = _mask_ip(ip_address)
    user_agent_summary = (user_agent or "")[:255] or None
    prev_hash, entry_hash = _chain_hashes(
        db,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        actor_user_id=actor_user_id,
        institution_id=institution_id,
        project_id=project_id,
        request_id=correlation_id,
        before_summary=before_summary,
        after_summary=after_summary,
        result=result,
        ip_address_masked=ip_address_masked,
        user_agent_summary=user_agent_summary,
    )
    log = AuditLog(
        institution_id=institution_id,
        project_id=project_id,
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        request_id=correlation_id,
        correlation_id=correlation_id,
        before_summary_json=before_summary,
        after_summary_json=after_summary,
        result=result,
        ip_address_masked=ip_address_masked,
        user_agent_summary=user_agent_summary,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
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
