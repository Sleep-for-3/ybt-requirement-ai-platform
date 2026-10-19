"""Replay and verification for the audit hash chain (④)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog
from app.services.governance.audit import (
    CHAIN_GLOBAL_SCOPE,
    audit_chain_scope,
    canonical_entry_payload,
    compute_entry_hash,
)

MAX_BREAK_IDS = 100

_CHAIN_COLUMNS = (
    AuditLog.id,
    AuditLog.institution_id,
    AuditLog.project_id,
    AuditLog.actor_user_id,
    AuditLog.action,
    AuditLog.resource_type,
    AuditLog.resource_id,
    AuditLog.request_id,
    AuditLog.before_summary_json,
    AuditLog.after_summary_json,
    AuditLog.result,
    AuditLog.ip_address_masked,
    AuditLog.user_agent_summary,
    AuditLog.prev_hash,
    AuditLog.entry_hash,
)


@dataclass(frozen=True)
class AuditChainVerification:
    """Structured outcome of :func:`verify_audit_chain`."""

    intact: bool
    checked: int
    chains_checked: int
    first_broken_id: int | None
    first_broken_reason: str | None
    affected_range: tuple[int, int] | None
    break_ids: tuple[int, ...] = ()
    last_checked_id: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "intact": self.intact,
            "checked": self.checked,
            "chains_checked": self.chains_checked,
            "first_broken_id": self.first_broken_id,
            "first_broken_reason": self.first_broken_reason,
            "affected_range": list(self.affected_range) if self.affected_range else None,
            "break_ids": list(self.break_ids),
            "last_checked_id": self.last_checked_id,
        }


def _payload_for_row(row: Any) -> str:
    return canonical_entry_payload(
        action=row.action,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        actor_user_id=row.actor_user_id,
        institution_id=row.institution_id,
        project_id=row.project_id,
        request_id=row.request_id,
        before_summary=row.before_summary_json or {},
        after_summary=row.after_summary_json or {},
        result=row.result,
        ip_address_masked=row.ip_address_masked,
        user_agent_summary=row.user_agent_summary,
    )


def verify_audit_chain(
    db: Session,
    *,
    institution_id: int | str | None = None,
    limit: int | None = None,
) -> AuditChainVerification:
    """Walk the audit hash chain from its oldest hashed row and report breaks.

    ``institution_id`` restricts the walk to a single chain; pass
    :data:`app.services.governance.audit.CHAIN_GLOBAL_SCOPE` to verify only the
    chain of rows whose institution is NULL.  ``limit`` bounds how many hashed
    rows are replayed (oldest first).

    Rows written while the feature was disabled (``entry_hash`` NULL) are
    skipped: the next hashed row links back to the last hashed row, so a
    disabled window is not reported as a break.
    """

    statement = select(*_CHAIN_COLUMNS).where(AuditLog.entry_hash.is_not(None))
    if institution_id == CHAIN_GLOBAL_SCOPE:
        statement = statement.where(AuditLog.institution_id.is_(None))
    elif institution_id is not None:
        statement = statement.where(AuditLog.institution_id == int(institution_id))
    statement = statement.order_by(AuditLog.institution_id, AuditLog.id)
    if limit is not None:
        statement = statement.limit(int(limit))

    expected: dict[str, str] = {}
    last_ids: dict[str, int] = {}
    first_break: dict[str, tuple[int, str]] = {}
    break_ids: list[int] = []
    checked = 0
    last_checked_id: int | None = None

    for row in db.execute(statement):
        checked += 1
        last_checked_id = int(row.id)
        scope = audit_chain_scope(row.institution_id)
        last_ids[scope] = int(row.id)
        reason = None
        if (row.prev_hash or "") != expected.get(scope, ""):
            reason = "prev_hash does not link to the previous entry of the chain"
        recomputed = compute_entry_hash(_payload_for_row(row), row.prev_hash or None)
        if recomputed != row.entry_hash:
            reason = reason or "entry_hash does not match the replayed digest"
        # Chain the next row against the replayed digest, so a tampered entry
        # also surfaces as a broken link on every row recorded after it.
        expected[scope] = recomputed
        if reason is not None:
            if scope not in first_break:
                first_break[scope] = (int(row.id), reason)
            if len(break_ids) < MAX_BREAK_IDS:
                break_ids.append(int(row.id))

    if not first_break:
        return AuditChainVerification(
            intact=True,
            checked=checked,
            chains_checked=len(last_ids),
            first_broken_id=None,
            first_broken_reason=None,
            affected_range=None,
            last_checked_id=last_checked_id,
        )

    earliest = min(first_break, key=lambda key: first_break[key][0])
    broken_id, reason = first_break[earliest]
    return AuditChainVerification(
        intact=False,
        checked=checked,
        chains_checked=len(last_ids),
        first_broken_id=broken_id,
        first_broken_reason=reason,
        affected_range=(broken_id, last_ids.get(earliest, broken_id)),
        break_ids=tuple(break_ids),
        last_checked_id=last_checked_id,
    )
