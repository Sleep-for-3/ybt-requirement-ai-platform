"""P2-B 同步事件落库服务：裁决在 ``requirement_source_sync``，这里只负责记账。

三个约束，缺一不可：

1. **重放幂等**：``(project, source, object_kind, object_key, source_version)``
   唯一，第二次提交同一事件只返回 ``skip_duplicate``，不新增待复核。
2. **游标只前进**：``external_sync_cursors.cursor`` 取 `max(已有, 本批最大)`，
   外部系统回退游标不会让平台"忘掉"已看过的事件。
3. **只产生待复核**：落库的 decision 只允许
   ``pending_review`` / ``mark_deleted_pending_review`` /
   ``mark_permission_pending_review``；跳过类裁决只出现在响应里，不写行。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.external_sync import ExternalSyncCursor, ExternalSyncEvent
from app.services.requirement_source_sync import (
    ACTION_MARK_DELETED,
    ACTION_MARK_PERMISSION,
    ACTION_PENDING_REVIEW,
    SYNC_CONTRACT_VERSION,
    SyncEvent,
    assert_only_review_actions,
    plan_sync,
)

#: 单批事件上限：外部系统应按游标分批推送，而不是一次灌全部历史。
MAX_EVENTS_PER_BATCH = 200

REVIEW_ACTIONS = (ACTION_PENDING_REVIEW, ACTION_MARK_DELETED, ACTION_MARK_PERMISSION)


class ExternalSyncError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _coerce_event(raw: Any, index: int) -> SyncEvent:
    if not isinstance(raw, Mapping):
        raise ExternalSyncError("event_not_object", f"第 {index} 条事件不是 JSON 对象")
    try:
        source = str(raw.get("source") or "")
        object_kind = str(raw.get("object_kind") or "")
        object_key = str(raw.get("object_key") or "")
        source_version = raw.get("source_version")
        cursor = raw.get("cursor")
    except Exception as exc:  # pragma: no cover - 防御性
        raise ExternalSyncError("event_malformed", f"第 {index} 条事件字段无法读取：{exc}") from exc
    if not source or not object_kind or not object_key:
        raise ExternalSyncError(
            "event_identity_missing",
            f"第 {index} 条事件缺少 source/object_kind/object_key，无法建立幂等身份",
        )
    if not isinstance(source_version, int) or isinstance(source_version, bool) or source_version < 0:
        raise ExternalSyncError("event_version_invalid", f"第 {index} 条事件的 source_version 必须是非负整数")
    if not isinstance(cursor, int) or isinstance(cursor, bool) or cursor < 0:
        raise ExternalSyncError("event_cursor_invalid", f"第 {index} 条事件的 cursor 必须是非负整数")
    payload = raw.get("payload") or {}
    if not isinstance(payload, Mapping):
        raise ExternalSyncError("event_payload_invalid", f"第 {index} 条事件的 payload 必须是 JSON 对象")
    return SyncEvent(
        source=source,
        object_kind=object_kind,
        object_key=object_key,
        source_version=source_version,
        cursor=cursor,
        payload=dict(payload),
        deleted=bool(raw.get("deleted")),
        permissions_changed=bool(raw.get("permissions_changed")),
        observed_at=str(raw.get("observed_at") or ""),
    )


def _object_identity(event: SyncEvent) -> str:
    return f"{event.source}:{event.object_kind}:{event.object_key}"


def load_known_state(db: Session, project_id: int) -> tuple[dict[str, int], dict[str, int], set[str]]:
    """返回 ``(游标, 对象最大版本, 已存在的事件身份)``。

    身份同时收录 ``identity`` 与 ``identity:payload_hash[:12]``，与
    ``plan_sync`` 的幂等判定保持一致。
    """

    cursors = {
        row.source: int(row.cursor or 0)
        for row in db.scalars(select(ExternalSyncCursor).where(ExternalSyncCursor.project_id == project_id))
    }
    versions: dict[str, int] = {}
    known: set[str] = set()
    rows = db.scalars(select(ExternalSyncEvent).where(ExternalSyncEvent.project_id == project_id))
    for row in rows:
        identity = f"{row.source}:{row.object_kind}:{row.object_key}:{row.source_version}"
        known.add(identity)
        if row.payload_hash:
            known.add(f"{identity}:{row.payload_hash[:12]}")
        object_identity = f"{row.source}:{row.object_kind}:{row.object_key}"
        versions[object_identity] = max(versions.get(object_identity, -1), int(row.source_version))
    return cursors, versions, known


def ingest_events(
    db: Session,
    *,
    project_id: int,
    events: Iterable[Any],
    created_by: int | None = None,
) -> dict[str, Any]:
    raw_events = list(events)
    if not raw_events:
        raise ExternalSyncError("events_empty", "事件列表为空")
    if len(raw_events) > MAX_EVENTS_PER_BATCH:
        raise ExternalSyncError(
            "events_too_many",
            f"单批最多 {MAX_EVENTS_PER_BATCH} 条事件，请按游标分批提交",
        )

    parsed = [_coerce_event(item, index) for index, item in enumerate(raw_events, start=1)]
    cursors, versions, known = load_known_state(db, project_id)
    plan = plan_sync(parsed, known_keys=known, known_cursors=cursors, known_versions=versions)
    assert_only_review_actions(plan)

    cursors_after = dict(cursors)
    stored: list[ExternalSyncEvent] = []
    decisions_by_identity = {decision.identity: decision for decision in plan.decisions}
    for event in parsed:
        decision = decisions_by_identity.get(event.identity())
        cursors_after[event.source] = max(cursors_after.get(event.source, 0), int(event.cursor))
        if decision is None or decision.action not in REVIEW_ACTIONS:
            continue
        row = ExternalSyncEvent(
            project_id=project_id,
            source=event.source,
            object_kind=event.object_kind,
            object_key=event.object_key,
            source_version=event.source_version,
            cursor=event.cursor,
            decision=decision.action,
            payload_json=dict(event.payload),
            payload_hash=event.payload_hash(),
            deleted=bool(event.deleted),
            permissions_changed=bool(event.permissions_changed),
            observed_at=event.observed_at or None,
            created_by=created_by,
        )
        db.add(row)
        stored.append(row)

    for source, cursor_value in cursors_after.items():
        row = db.scalar(
            select(ExternalSyncCursor).where(
                ExternalSyncCursor.project_id == project_id,
                ExternalSyncCursor.source == source,
            )
        )
        if row is None:
            db.add(
                ExternalSyncCursor(
                    project_id=project_id,
                    source=source,
                    cursor=cursor_value,
                    updated_by=created_by,
                )
            )
        else:
            row.cursor = max(int(row.cursor or 0), cursor_value)
            row.updated_by = created_by

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ExternalSyncError("event_conflict", "同步事件并发写入冲突，请重试整批（重放是安全的）") from exc

    payload = plan.as_dict()
    payload["stored"] = len(stored)
    payload["stored_ids"] = [row.id for row in stored]
    payload["cursors"] = cursors_after
    payload["contract_version"] = SYNC_CONTRACT_VERSION
    return payload


def serialize(row: ExternalSyncEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "source": row.source,
        "object_kind": row.object_kind,
        "object_key": row.object_key,
        "source_version": row.source_version,
        "cursor": row.cursor,
        "decision": row.decision,
        "payload_hash": row.payload_hash,
        "deleted": bool(row.deleted),
        "permissions_changed": bool(row.permissions_changed),
        "observed_at": row.observed_at,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_pending(
    db: Session,
    *,
    project_id: int,
    source: str | None = None,
    limit: int = 100,
) -> list[ExternalSyncEvent]:
    stmt = select(ExternalSyncEvent).where(
        ExternalSyncEvent.project_id == project_id,
        ExternalSyncEvent.decision.in_(REVIEW_ACTIONS),
    )
    if source:
        stmt = stmt.where(ExternalSyncEvent.source == source)
    return list(db.scalars(stmt.order_by(ExternalSyncEvent.id.desc()).limit(max(1, min(limit, 200)))))


def list_cursors(db: Session, *, project_id: int) -> list[ExternalSyncCursor]:
    return list(
        db.scalars(
            select(ExternalSyncCursor)
            .where(ExternalSyncCursor.project_id == project_id)
            .order_by(ExternalSyncCursor.source)
        )
    )
