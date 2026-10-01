"""Durable Agent orchestration state.

The agent layer is a *governed* orchestration surface: every step binds to a
registered tool, every tool call is recorded, every human gate is a real review
record, and every artifact points back at the evidence that produced it.

The tables here deliberately do not duplicate governance: human decisions bind
to ``review_tasks`` / ``review_decisions`` (the canonical review ledger) and the
run itself is queued as a normal ``background_jobs`` row so retry / cancel /
resume reuse the existing task queue.
"""
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class AgentTask(Base, TimestampMixin):
    """One business objective driven to completion by the orchestrator."""

    __tablename__ = "agent_tasks"
    __table_args__ = (
        Index("ix_agent_tasks_project_status", "project_id", "status"),
        Index("ix_agent_tasks_project_created", "project_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    objective_key: Mapped[str | None] = mapped_column(String(100), index=True)
    scenario_key: Mapped[str | None] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(50), default="created", index=True)
    current_step_key: Mapped[str | None] = mapped_column(String(100))
    plan_version: Mapped[int] = mapped_column(Integer, default=1)
    background_job_id: Mapped[int | None] = mapped_column(ForeignKey("background_jobs.id"), index=True)
    review_instance_id: Mapped[int | None] = mapped_column(ForeignKey("workflow_instances.id"), index=True)
    completed_steps: Mapped[int] = mapped_column(Integer, default=0)
    pending_steps: Mapped[int] = mapped_column(Integer, default=0)
    failed_steps: Mapped[int] = mapped_column(Integer, default=0)
    human_pending_steps: Mapped[int] = mapped_column(Integer, default=0)
    skipped_steps: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    replanning_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    artifact_count: Mapped[int] = mapped_column(Integer, default=0)
    model_metadata_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    evidence_refs_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    artifact_refs_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    result_summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    started_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))


class AgentPlan(Base, TimestampMixin):
    """An immutable planner output. Replanning appends a new version."""

    __tablename__ = "agent_plans"
    __table_args__ = (UniqueConstraint("task_id", "version_no", name="uq_agent_plan_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("agent_tasks.id"), nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)
    planner_source: Mapped[str] = mapped_column(String(50), default="deterministic")
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    steps_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    plan_hash: Mapped[str | None] = mapped_column(String(64))
    degraded_reason: Mapped[str | None] = mapped_column(String(100))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    superseded_by: Mapped[int | None] = mapped_column(ForeignKey("agent_plans.id"))


class AgentStep(Base, TimestampMixin):
    """One planned step: a tool binding plus its own durable status."""

    __tablename__ = "agent_steps"
    __table_args__ = (
        UniqueConstraint("task_id", "plan_id", "step_key", name="uq_agent_step_key"),
        Index("ix_agent_steps_task_status", "task_id", "status"),
        Index("ix_agent_steps_idempotency", "idempotency_key", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("agent_tasks.id"), nullable=False, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("agent_plans.id"), nullable=False, index=True)
    step_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    depends_on_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    # Dependencies whose absence degrades the step (gap) instead of blocking it.
    optional_depends_on_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    input_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    input_hash: Mapped[str | None] = mapped_column(String(64))
    output_summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    evidence_refs_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    gap_codes_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    requires_human_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    human_gate_key: Mapped[str | None] = mapped_column(String(100))
    review_task_id: Mapped[int | None] = mapped_column(ForeignKey("review_tasks.id"), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    artifact_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))


class AgentToolCall(Base, TimestampMixin):
    """Append-only observability record for one tool invocation attempt."""

    __tablename__ = "agent_tool_calls"
    __table_args__ = (
        Index("ix_agent_tool_calls_task_tool", "task_id", "tool_key"),
        Index("ix_agent_tool_calls_step", "step_id", "attempt"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("agent_tasks.id"), nullable=False, index=True)
    step_id: Mapped[int | None] = mapped_column(ForeignKey("agent_steps.id"), index=True)
    tool_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    tool_version: Mapped[str | None] = mapped_column(String(50))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(50), default="running", index=True)
    input_summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    output_summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    context_hash: Mapped[str | None] = mapped_column(String(64))
    model_name: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    provider_type: Mapped[str | None] = mapped_column(String(50))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    token_usage_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_reason: Mapped[str | None] = mapped_column(String(100))
    degraded_path: Mapped[str | None] = mapped_column(String(100))
    required_permissions_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    risk_level: Mapped[str | None] = mapped_column(String(20))
    read_only: Mapped[bool] = mapped_column(Boolean, default=True)
    human_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    adopted: Mapped[bool] = mapped_column(Boolean, default=False)
    execution_metadata_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)


class AgentHumanDecision(Base, TimestampMixin):
    """The agent-side binding of a human gate decision.

    ``review_task_id`` / ``review_decision_id`` point at the canonical review
    ledger so the agent never keeps a second, competing decision record.
    """

    __tablename__ = "agent_human_decisions"
    __table_args__ = (Index("ix_agent_human_decisions_task_step", "task_id", "step_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("agent_tasks.id"), nullable=False, index=True)
    step_id: Mapped[int] = mapped_column(ForeignKey("agent_steps.id"), nullable=False, index=True)
    tool_call_id: Mapped[int | None] = mapped_column(ForeignKey("agent_tool_calls.id"), index=True)
    decision: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    comment: Mapped[str | None] = mapped_column(Text)
    edited_payload_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    context_hash: Mapped[str | None] = mapped_column(String(64))
    applied_plan_version: Mapped[int | None] = mapped_column(Integer)
    review_task_id: Mapped[int | None] = mapped_column(ForeignKey("review_tasks.id"), index=True)
    review_decision_id: Mapped[int | None] = mapped_column(ForeignKey("review_decisions.id"), index=True)
    decided_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    decided_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentArtifact(Base, TimestampMixin):
    """A produced deliverable candidate, always evidence-linked."""

    __tablename__ = "agent_artifacts"
    __table_args__ = (Index("ix_agent_artifacts_task_type", "task_id", "artifact_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("agent_tasks.id"), nullable=False, index=True)
    step_id: Mapped[int | None] = mapped_column(ForeignKey("agent_steps.id"), index=True)
    tool_call_id: Mapped[int | None] = mapped_column(ForeignKey("agent_tool_calls.id"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="draft", index=True)
    ref_type: Mapped[str | None] = mapped_column(String(100), index=True)
    ref_id: Mapped[str | None] = mapped_column(String(100), index=True)
    summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    evidence_refs_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
