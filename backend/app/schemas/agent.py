"""Request contracts for the agent API."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AgentDecision = Literal["approve", "reject", "edit_and_approve", "request_reanalysis"]


class AgentTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=4, max_length=2000)
    scenario_key: str | None = Field(default=None, max_length=100)
    # V2: the workspace prefers the model planner; the runtime falls back to the governed
    # deterministic plan (planner_source="fallback") if the model is unavailable or invalid.
    use_llm_planner: bool = True
    adaptive: bool = True
    auto_start: bool = True
    max_retries: int = Field(default=3, ge=0, le=5)


class AgentDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: AgentDecision
    comment: str | None = Field(default=None, max_length=4000)
    edited_payload: dict[str, Any] = Field(default_factory=dict)
    claim: bool = False


class AgentReplanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: str = Field(default="manual_replan", max_length=100)


class AgentSqlChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script_file_id: int
    new_version_id: int | None = None
    auto_start: bool = True
