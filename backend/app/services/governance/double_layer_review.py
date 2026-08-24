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

from app.models import MartToYbtMapping, SourceToMartMapping, WorkflowInstance


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


__all__ = [
    "DOUBLE_LAYER_REVIEW_WORKFLOW",
    "DoubleLayerMapping",
    "MappingGenerationNotEditable",
    "ensure_double_layer_mapping_editable",
]
