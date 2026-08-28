from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReportingCycleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_code: str = Field(min_length=1, max_length=100)
    cycle_name: str = Field(min_length=1, max_length=255)
    reporting_type: str = Field(default="regular", min_length=1, max_length=50)
    period_start: datetime
    period_end: datetime
    data_cutoff_at: datetime | None = None
    submission_deadline: datetime | None = None
    status: Literal["draft", "preparing", "reviewing", "ready", "submitted", "closed"] = "draft"
    owner_user_id: int | None = Field(default=None, gt=0)
    owner_department: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=4000)


class ReportingCycleRead(ReportingCycleCreate):
    id: int
    project_id: int
    institution_id: int | None
    created_at: datetime
    updated_at: datetime

