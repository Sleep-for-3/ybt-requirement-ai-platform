"""Durable agent orchestration state (tasks, plans, steps, tool calls, human
decisions, artifacts).

Written explicitly instead of importing the live ORM: the release gates reject a
migration that reads ``app.models`` or ``Base.metadata`` (see
``tests/test_migration_schema_freeze.py``).
"""
import sqlalchemy as sa
from alembic import op

revision = "202610010045"
down_revision = "202609270044"
branch_labels = None
depends_on = None


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("objective_key", sa.String(length=100), nullable=True),
        sa.Column("scenario_key", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("current_step_key", sa.String(length=100), nullable=True),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("background_job_id", sa.Integer(), sa.ForeignKey("background_jobs.id"), nullable=True),
        sa.Column("review_instance_id", sa.Integer(), sa.ForeignKey("workflow_instances.id"), nullable=True),
        sa.Column("completed_steps", sa.Integer(), nullable=False),
        sa.Column("pending_steps", sa.Integer(), nullable=False),
        sa.Column("failed_steps", sa.Integer(), nullable=False),
        sa.Column("human_pending_steps", sa.Integer(), nullable=False),
        sa.Column("skipped_steps", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("replanning_count", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("artifact_count", sa.Integer(), nullable=False),
        sa.Column("model_metadata_json", sa.JSON(), nullable=False),
        sa.Column("evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("artifact_refs_json", sa.JSON(), nullable=False),
        sa.Column("result_summary_json", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_agent_tasks_institution_id", "agent_tasks", ["institution_id"])
    op.create_index("ix_agent_tasks_project_id", "agent_tasks", ["project_id"])
    op.create_index("ix_agent_tasks_objective_key", "agent_tasks", ["objective_key"])
    op.create_index("ix_agent_tasks_scenario_key", "agent_tasks", ["scenario_key"])
    op.create_index("ix_agent_tasks_status", "agent_tasks", ["status"])
    op.create_index("ix_agent_tasks_background_job_id", "agent_tasks", ["background_job_id"])
    op.create_index("ix_agent_tasks_review_instance_id", "agent_tasks", ["review_instance_id"])
    op.create_index("ix_agent_tasks_created_by", "agent_tasks", ["created_by"])
    op.create_index("ix_agent_tasks_project_status", "agent_tasks", ["project_id", "status"])
    op.create_index("ix_agent_tasks_project_created", "agent_tasks", ["project_id", "id"])

    op.create_table(
        "agent_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("agent_tasks.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("planner_source", sa.String(length=50), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("steps_json", sa.JSON(), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=True),
        sa.Column("degraded_reason", sa.String(length=100), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("superseded_by", sa.Integer(), sa.ForeignKey("agent_plans.id"), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("task_id", "version_no", name="uq_agent_plan_version"),
    )
    op.create_index("ix_agent_plans_task_id", "agent_plans", ["task_id"])
    op.create_index("ix_agent_plans_status", "agent_plans", ["status"])

    op.create_table(
        "agent_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("agent_tasks.id"), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("agent_plans.id"), nullable=False),
        sa.Column("step_key", sa.String(length=100), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("tool_key", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("depends_on_json", sa.JSON(), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=True),
        sa.Column("output_summary_json", sa.JSON(), nullable=False),
        sa.Column("evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("gap_codes_json", sa.JSON(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("requires_human_confirmation", sa.Boolean(), nullable=False),
        sa.Column("human_gate_key", sa.String(length=100), nullable=True),
        sa.Column("review_task_id", sa.Integer(), sa.ForeignKey("review_tasks.id"), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("artifact_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("task_id", "plan_id", "step_key", name="uq_agent_step_key"),
    )
    op.create_index("ix_agent_steps_task_id", "agent_steps", ["task_id"])
    op.create_index("ix_agent_steps_plan_id", "agent_steps", ["plan_id"])
    op.create_index("ix_agent_steps_step_key", "agent_steps", ["step_key"])
    op.create_index("ix_agent_steps_tool_key", "agent_steps", ["tool_key"])
    op.create_index("ix_agent_steps_status", "agent_steps", ["status"])
    op.create_index("ix_agent_steps_review_task_id", "agent_steps", ["review_task_id"])
    op.create_index("ix_agent_steps_task_status", "agent_steps", ["task_id", "status"])
    op.create_index("ix_agent_steps_idempotency", "agent_steps", ["idempotency_key"], unique=True)

    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("agent_tasks.id"), nullable=False),
        sa.Column("step_id", sa.Integer(), sa.ForeignKey("agent_steps.id"), nullable=True),
        sa.Column("tool_key", sa.String(length=100), nullable=False),
        sa.Column("tool_version", sa.String(length=50), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("input_summary_json", sa.JSON(), nullable=False),
        sa.Column("output_summary_json", sa.JSON(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("context_hash", sa.String(length=64), nullable=True),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=100), nullable=True),
        sa.Column("provider_type", sa.String(length=50), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("token_usage_json", sa.JSON(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("failure_reason", sa.String(length=100), nullable=True),
        sa.Column("degraded_path", sa.String(length=100), nullable=True),
        sa.Column("required_permissions_json", sa.JSON(), nullable=False),
        sa.Column("risk_level", sa.String(length=20), nullable=True),
        sa.Column("read_only", sa.Boolean(), nullable=False),
        sa.Column("human_confirmed", sa.Boolean(), nullable=False),
        sa.Column("adopted", sa.Boolean(), nullable=False),
        sa.Column("execution_metadata_json", sa.JSON(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_agent_tool_calls_task_id", "agent_tool_calls", ["task_id"])
    op.create_index("ix_agent_tool_calls_step_id", "agent_tool_calls", ["step_id"])
    op.create_index("ix_agent_tool_calls_tool_key", "agent_tool_calls", ["tool_key"])
    op.create_index("ix_agent_tool_calls_status", "agent_tool_calls", ["status"])
    op.create_index("ix_agent_tool_calls_task_tool", "agent_tool_calls", ["task_id", "tool_key"])
    op.create_index("ix_agent_tool_calls_step", "agent_tool_calls", ["step_id", "attempt"])

    op.create_table(
        "agent_human_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("agent_tasks.id"), nullable=False),
        sa.Column("step_id", sa.Integer(), sa.ForeignKey("agent_steps.id"), nullable=False),
        sa.Column("tool_call_id", sa.Integer(), sa.ForeignKey("agent_tool_calls.id"), nullable=True),
        sa.Column("decision", sa.String(length=50), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("edited_payload_json", sa.JSON(), nullable=False),
        sa.Column("context_hash", sa.String(length=64), nullable=True),
        sa.Column("applied_plan_version", sa.Integer(), nullable=True),
        sa.Column("review_task_id", sa.Integer(), sa.ForeignKey("review_tasks.id"), nullable=True),
        sa.Column("review_decision_id", sa.Integer(), sa.ForeignKey("review_decisions.id"), nullable=True),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_agent_human_decisions_task_id", "agent_human_decisions", ["task_id"])
    op.create_index("ix_agent_human_decisions_step_id", "agent_human_decisions", ["step_id"])
    op.create_index("ix_agent_human_decisions_tool_call_id", "agent_human_decisions", ["tool_call_id"])
    op.create_index("ix_agent_human_decisions_decision", "agent_human_decisions", ["decision"])
    op.create_index("ix_agent_human_decisions_review_task_id", "agent_human_decisions", ["review_task_id"])
    op.create_index("ix_agent_human_decisions_review_decision_id", "agent_human_decisions", ["review_decision_id"])
    op.create_index("ix_agent_human_decisions_decided_by", "agent_human_decisions", ["decided_by"])
    op.create_index("ix_agent_human_decisions_task_step", "agent_human_decisions", ["task_id", "step_id"])

    op.create_table(
        "agent_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("agent_tasks.id"), nullable=False),
        sa.Column("step_id", sa.Integer(), sa.ForeignKey("agent_steps.id"), nullable=True),
        sa.Column("tool_call_id", sa.Integer(), sa.ForeignKey("agent_tool_calls.id"), nullable=True),
        sa.Column("artifact_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("ref_type", sa.String(length=100), nullable=True),
        sa.Column("ref_id", sa.String(length=100), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("confirmed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_agent_artifacts_task_id", "agent_artifacts", ["task_id"])
    op.create_index("ix_agent_artifacts_step_id", "agent_artifacts", ["step_id"])
    op.create_index("ix_agent_artifacts_tool_call_id", "agent_artifacts", ["tool_call_id"])
    op.create_index("ix_agent_artifacts_artifact_type", "agent_artifacts", ["artifact_type"])
    op.create_index("ix_agent_artifacts_status", "agent_artifacts", ["status"])
    op.create_index("ix_agent_artifacts_ref_type", "agent_artifacts", ["ref_type"])
    op.create_index("ix_agent_artifacts_ref_id", "agent_artifacts", ["ref_id"])
    op.create_index("ix_agent_artifacts_created_by", "agent_artifacts", ["created_by"])
    op.create_index("ix_agent_artifacts_task_type", "agent_artifacts", ["task_id", "artifact_type"])


def downgrade() -> None:
    op.drop_index("ix_agent_artifacts_task_type", table_name="agent_artifacts")
    op.drop_index("ix_agent_artifacts_created_by", table_name="agent_artifacts")
    op.drop_index("ix_agent_artifacts_ref_id", table_name="agent_artifacts")
    op.drop_index("ix_agent_artifacts_ref_type", table_name="agent_artifacts")
    op.drop_index("ix_agent_artifacts_status", table_name="agent_artifacts")
    op.drop_index("ix_agent_artifacts_artifact_type", table_name="agent_artifacts")
    op.drop_index("ix_agent_artifacts_tool_call_id", table_name="agent_artifacts")
    op.drop_index("ix_agent_artifacts_step_id", table_name="agent_artifacts")
    op.drop_index("ix_agent_artifacts_task_id", table_name="agent_artifacts")
    op.drop_table("agent_artifacts")

    op.drop_index("ix_agent_human_decisions_task_step", table_name="agent_human_decisions")
    op.drop_index("ix_agent_human_decisions_decided_by", table_name="agent_human_decisions")
    op.drop_index("ix_agent_human_decisions_review_decision_id", table_name="agent_human_decisions")
    op.drop_index("ix_agent_human_decisions_review_task_id", table_name="agent_human_decisions")
    op.drop_index("ix_agent_human_decisions_decision", table_name="agent_human_decisions")
    op.drop_index("ix_agent_human_decisions_tool_call_id", table_name="agent_human_decisions")
    op.drop_index("ix_agent_human_decisions_step_id", table_name="agent_human_decisions")
    op.drop_index("ix_agent_human_decisions_task_id", table_name="agent_human_decisions")
    op.drop_table("agent_human_decisions")

    op.drop_index("ix_agent_tool_calls_step", table_name="agent_tool_calls")
    op.drop_index("ix_agent_tool_calls_task_tool", table_name="agent_tool_calls")
    op.drop_index("ix_agent_tool_calls_status", table_name="agent_tool_calls")
    op.drop_index("ix_agent_tool_calls_tool_key", table_name="agent_tool_calls")
    op.drop_index("ix_agent_tool_calls_step_id", table_name="agent_tool_calls")
    op.drop_index("ix_agent_tool_calls_task_id", table_name="agent_tool_calls")
    op.drop_table("agent_tool_calls")

    op.drop_index("ix_agent_steps_idempotency", table_name="agent_steps")
    op.drop_index("ix_agent_steps_task_status", table_name="agent_steps")
    op.drop_index("ix_agent_steps_review_task_id", table_name="agent_steps")
    op.drop_index("ix_agent_steps_status", table_name="agent_steps")
    op.drop_index("ix_agent_steps_tool_key", table_name="agent_steps")
    op.drop_index("ix_agent_steps_step_key", table_name="agent_steps")
    op.drop_index("ix_agent_steps_plan_id", table_name="agent_steps")
    op.drop_index("ix_agent_steps_task_id", table_name="agent_steps")
    op.drop_table("agent_steps")

    op.drop_index("ix_agent_plans_status", table_name="agent_plans")
    op.drop_index("ix_agent_plans_task_id", table_name="agent_plans")
    op.drop_table("agent_plans")

    op.drop_index("ix_agent_tasks_project_created", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_project_status", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_created_by", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_review_instance_id", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_background_job_id", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_status", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_scenario_key", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_objective_key", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_project_id", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_institution_id", table_name="agent_tasks")
    op.drop_table("agent_tasks")
