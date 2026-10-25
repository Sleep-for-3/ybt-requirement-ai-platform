"""字段级派工与处置登记服务。

只登记"谁在处理、处理到哪一步、留了什么话"，**不改需求内容、不关缺口、不冻结**。
状态与缺口状态是两套语义：处置完成不等于缺口关闭，缺口关闭仍由工作台重新评估。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Requirement, RequirementFieldDispatch, TargetField
from app.models import RequirementFieldDispatchEvent

DISPATCH_VERSION = "requirement-field-dispatch-v1"
DISPATCH_STATUSES = ("in_progress", "done", "paused")
STATUS_LABELS = {
    "in_progress": "处理中",
    "done": "已处置，待复核",
    "paused": "已暂停",
}
NOTE_REQUIRED = ("paused",)
MAX_OWNER = 100
MAX_NOTE = 2000


class DispatchError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _event_payload(row: RequirementFieldDispatchEvent) -> dict:
    return {
        "id": row.id,
        "owner": row.owner,
        "status": row.status,
        "status_label": STATUS_LABELS.get(row.status, row.status),
        "note": row.note,
        "actor_id": row.actor_id,
        "created_at": _iso(row.created_at),
    }


def serialize(row: RequirementFieldDispatch) -> dict:
    return {
        "field_id": row.field_id,
        "owner": row.owner,
        "status": row.status,
        "status_label": STATUS_LABELS.get(row.status, row.status),
        "note": row.note,
        "updated_at": _iso(row.updated_at or row.created_at),
        "created_by": row.created_by,
        "version": DISPATCH_VERSION,
    }


def record_dispatch(
    db: Session,
    *,
    project_id: int,
    requirement_id: int,
    field_id: int,
    owner: str | None = None,
    status: str = "in_progress",
    note: str | None = None,
    created_by: int | None = None,
) -> tuple[RequirementFieldDispatch, bool]:
    if status not in DISPATCH_STATUSES:
        raise DispatchError("status_unknown", f"未知的处置状态：{status}")
    owner_text = (owner or "").strip()
    note_text = (note or "").strip()
    if len(owner_text) > MAX_OWNER:
        raise DispatchError("owner_too_long", "责任人过长（最多 100 字）")
    if len(note_text) > MAX_NOTE:
        raise DispatchError("note_too_long", "说明过长（最多 2000 字）")
    if status in NOTE_REQUIRED and not note_text:
        raise DispatchError("note_required", f"选择「{STATUS_LABELS[status]}」必须写明原因")

    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.project_id != project_id:
        raise DispatchError("requirement_missing", "需求不存在或不属于当前项目")
    field = db.get(TargetField, field_id)
    if field is None or field.project_id != project_id:
        raise DispatchError("field_missing", "字段不存在或不属于当前项目")
    scope = (requirement.scope_json or {})
    if field.target_table_id != scope.get("target_table_id"):
        raise DispatchError("field_not_in_requirement", "该字段不属于这条需求的监管表")

    row = db.scalars(
        select(RequirementFieldDispatch).where(
            RequirementFieldDispatch.requirement_id == requirement_id,
            RequirementFieldDispatch.field_id == field_id,
        )
    ).first()
    created = row is None
    if created:
        row = RequirementFieldDispatch(
            project_id=project_id,
            requirement_id=requirement_id,
            field_id=field_id,
            created_by=created_by,
        )
        db.add(row)
    previous = (row.owner, row.status, row.note) if not created else None
    row.owner = owner_text or None
    row.status = status
    row.note = note_text or None
    db.flush()

    # 只追加、不覆盖：最近一次处置在 dispatch 表，轨迹在事件表。
    if created or previous != (row.owner, row.status, row.note):
        db.add(
            RequirementFieldDispatchEvent(
                project_id=project_id,
                requirement_id=requirement_id,
                field_id=field_id,
                owner=row.owner,
                status=row.status,
                note=row.note,
                actor_id=created_by,
            )
        )
        db.flush()
    return row, created


def dispatch_events_for_project(
    db: Session, project_id: int, *, per_field: int = 5
) -> dict[tuple[int, int], list[dict]]:
    """每字段最近若干条处置事件（新→旧）。

    一次性取全项目再在内存里截断：按字段逐条查会把只读清单变成 N+1 查询。
    """

    rows = db.scalars(
        select(RequirementFieldDispatchEvent)
        .where(RequirementFieldDispatchEvent.project_id == project_id)
        .order_by(RequirementFieldDispatchEvent.id.desc())
    )
    grouped: dict[tuple[int, int], list[dict]] = {}
    for row in rows:
        key = (row.requirement_id, row.field_id)
        bucket = grouped.setdefault(key, [])
        if len(bucket) < per_field:
            bucket.append(_event_payload(row))
    return grouped


def dispatches_for_project(db: Session, project_id: int) -> dict[tuple[int, int], dict]:
    rows = db.scalars(
        select(RequirementFieldDispatch).where(RequirementFieldDispatch.project_id == project_id)
    )
    events = dispatch_events_for_project(db, project_id)
    payload: dict[tuple[int, int], dict] = {}
    for row in rows:
        item = serialize(row)
        item["history"] = events.get((row.requirement_id, row.field_id), [])
        payload[(row.requirement_id, row.field_id)] = item
    return payload
