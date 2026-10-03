"""Lifecycle policy for direct Source-to-Mart and Mart-to-YBT generation.

The mapping row is the only task-local state that the double-layer generators
may read outside ``RegulatoryContextBuilder``.  This policy deliberately keeps
that read small and fail-closed: only an untouched draft without human final
content and without an active double-layer review may cross the model boundary.
"""

from __future__ import annotations

from typing import TypeAlias

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MappingVersion, MartToYbtMapping, SourceToMartMapping, WorkflowInstance


DoubleLayerMapping: TypeAlias = SourceToMartMapping | MartToYbtMapping

DOUBLE_LAYER_REVIEW_WORKFLOW = "double_layer_mapping_review"


class MappingGenerationNotEditable(RuntimeError):
    """The current mapping lifecycle does not permit AI draft generation."""

    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(f"Double-layer mapping generation is not editable: {reason_code}")


def ensure_double_layer_mapping_editable(
    db: Session,
    mapping_type: str,
    mapping: DoubleLayerMapping,
) -> None:
    """Fail closed unless ``mapping`` is an unreviewed, draft-only task row.

    The helper intentionally performs no shared-fact, evidence, or model work.
    It is called once before Context construction and once after the fresh
    Project -> task lock, so a lifecycle transition during model execution is
    authoritative at the write boundary.
    """

    if mapping_type not in {"source_to_mart", "mart_to_ybt"}:
        raise MappingGenerationNotEditable("UNSUPPORTED_DOUBLE_LAYER_MAPPING")

    if mapping.mapping_status != "draft":
        raise MappingGenerationNotEditable("MAPPING_STATUS_NOT_DRAFT")

    if mapping.final_content and mapping.final_content.strip():
        raise MappingGenerationNotEditable("FINAL_CONTENT_PRESENT")

    latest_review = db.scalar(
        select(WorkflowInstance)
        .where(
            WorkflowInstance.project_id == mapping.project_id,
            WorkflowInstance.workflow_key == DOUBLE_LAYER_REVIEW_WORKFLOW,
            WorkflowInstance.target_type == mapping_type,
            WorkflowInstance.target_id == mapping.id,
        )
        .order_by(WorkflowInstance.id.desc())
    )
    if latest_review is not None and latest_review.status == "in_progress":
        raise MappingGenerationNotEditable("DOUBLE_LAYER_REVIEW_IN_PROGRESS")

# Update keys that do not change the reviewed content itself.
NON_CONTENT_UPDATE_KEYS = frozenset({"mapping_status", "reviewed_by", "reviewed_at"})

APPROVED_CONTENT_IMMUTABLE = "APPROVED_CONTENT_IMMUTABLE"
REVIEW_IN_PROGRESS = "DOUBLE_LAYER_REVIEW_IN_PROGRESS"


def _latest_double_layer_review(db: Session, mapping_type: str, mapping: DoubleLayerMapping) -> WorkflowInstance | None:
    return db.scalar(
        select(WorkflowInstance)
        .where(
            WorkflowInstance.project_id == mapping.project_id,
            WorkflowInstance.workflow_key == DOUBLE_LAYER_REVIEW_WORKFLOW,
            WorkflowInstance.target_type == mapping_type,
            WorkflowInstance.target_id == mapping.id,
        )
        .order_by(WorkflowInstance.id.desc())
    )


def ensure_double_layer_mapping_writable(
    db: Session,
    mapping_type: str,
    mapping: DoubleLayerMapping,
    *,
    updates: dict | None = None,
    deleting: bool = False,
) -> bool:
    """Fail-closed lifecycle guard shared by every write entry point (B03 / BA01).

    Returns ``True`` when the caller explicitly re-opens a new draft revision (it must then
    invalidate the previous approval), ``False`` for a normal draft edit.

    Rules:
    * an in-progress double-layer review freezes the row: no content write, no delete;
    * approved content is immutable in place: a content change (or a delete) is refused until the
      caller explicitly re-opens the mapping with ``mapping_status='draft'``, in which case the
      previous approved revision stays preserved in ``mapping_versions``;
    * status-only changes (approve/reject/reviewer fields) keep the old behaviour.
    """

    if mapping_type not in {"source_to_mart", "mart_to_ybt"}:
        raise MappingGenerationNotEditable("UNSUPPORTED_DOUBLE_LAYER_MAPPING")

    latest_review = _latest_double_layer_review(db, mapping_type, mapping)
    if latest_review is not None and latest_review.status == "in_progress":
        raise MappingGenerationNotEditable(REVIEW_IN_PROGRESS)

    if mapping.mapping_status != "approved":
        return False

    requested = dict(updates or {})
    reopens_draft = requested.get("mapping_status") == "draft"
    if deleting:
        if reopens_draft:  # 删除前已显式退回草稿：按新修订处理，放行
            return True
        raise MappingGenerationNotEditable(APPROVED_CONTENT_IMMUTABLE)

    content_keys = set(requested) - NON_CONTENT_UPDATE_KEYS
    if not content_keys:
        return False
    if reopens_draft:
        return True
    raise MappingGenerationNotEditable(APPROVED_CONTENT_IMMUTABLE)


def approved_mapping_is_current(db: Session, mapping_type: str, mapping: DoubleLayerMapping) -> bool:
    """A readiness check must not trust the ``approved`` string alone.

    The approved row is only trustworthy when the newest saved version for it still matches the
    live ``final_content``: any later content edit invalidates the approval.
    """

    if mapping.mapping_status != "approved":
        return False
    latest = db.scalar(
        select(MappingVersion)
        .where(
            MappingVersion.mapping_type == mapping_type,
            MappingVersion.mapping_id == mapping.id,
        )
        .order_by(MappingVersion.version_no.desc())
    )
    if latest is None:
        return False
    return (latest.content_snapshot or "") == (mapping.final_content or "")


__all__ = [
    "APPROVED_CONTENT_IMMUTABLE",
    "DOUBLE_LAYER_REVIEW_WORKFLOW",
    "NON_CONTENT_UPDATE_KEYS",
    "REVIEW_IN_PROGRESS",
    "DoubleLayerMapping",
    "MappingGenerationNotEditable",
    "approved_mapping_is_current",
    "ensure_double_layer_mapping_editable",
    "ensure_double_layer_mapping_writable",
]
