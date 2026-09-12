from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RequirementSnapshotCreate(BaseModel):
    target_table_id: int = Field(gt=0)
    scenario_id: int | None = Field(default=None, gt=0)
    change_note: str | None = Field(default=None, max_length=2000)


class RequirementSnapshotSummary(BaseModel):
    id: int
    project_id: int
    target_table_id: int
    scenario_id: int | None
    scope_key: str
    snapshot_no: int
    requirement_version: str
    schema_version: str
    model_version: str
    catalog_revision: str | None
    lineage_revision: str | None
    status: str
    content_hash: str
    change_note: str | None
    created_by: int | None
    created_at: datetime


class RequirementSnapshotRead(RequirementSnapshotSummary):
    content_snapshot_json: dict[str, Any]
    idempotent: bool = False
