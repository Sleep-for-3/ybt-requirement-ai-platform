"""production governance workflow

Revision ID: 202607150007
Revises: 202607140006
"""

import sqlalchemy as sa
from alembic import op


revision = "202607150007"
down_revision = "202607140006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _create_table(
        "institutions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("institution_code", sa.String(100), nullable=False),
        sa.Column("institution_name", sa.String(255), nullable=False),
        sa.Column("institution_type", sa.String(50), nullable=False, server_default="bank"),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("data_classification_policy_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("institution_code", name="uq_institutions_code"),
    )
    _create_index("ix_institutions_type_status", "institutions", ["institution_type", "status"])

    if "email" not in _columns("users"):
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("email", sa.String(255)))
            batch.add_column(sa.Column("password_hash", sa.Text()))
            batch.add_column(sa.Column("status", sa.String(50), nullable=False, server_default="active"))
            batch.add_column(sa.Column("last_login_at", sa.DateTime(timezone=True)))
            batch.add_column(sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"))
            batch.add_column(sa.Column("locked_until", sa.DateTime(timezone=True)))
            batch.create_unique_constraint("uq_users_email", ["email"])
            batch.create_index("ix_users_status", ["status"])

    if "institution_id" not in _columns("projects"):
        with op.batch_alter_table("projects") as batch:
            batch.add_column(sa.Column("institution_id", sa.Integer()))
            batch.add_column(sa.Column("project_status", sa.String(50), nullable=False, server_default="active"))
            batch.add_column(sa.Column("project_owner_id", sa.Integer()))
            batch.add_column(sa.Column("confidentiality_level", sa.String(50), nullable=False, server_default="internal"))
            batch.create_foreign_key("fk_projects_institution", "institutions", ["institution_id"], ["id"])
            batch.create_foreign_key("fk_projects_owner", "users", ["project_owner_id"], ["id"])
            batch.create_index("ix_projects_institution", ["institution_id"])
            batch.create_index("ix_projects_status", ["project_status"])

    _create_table(
        "institution_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="member"),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.UniqueConstraint("institution_id", "user_id", name="uq_institution_membership"),
    )
    _create_index("ix_institution_membership_user", "institution_memberships", ["user_id", "status"])

    _create_table(
        "project_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("project_role", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_membership"),
    )
    _create_index("ix_project_membership_user", "project_memberships", ["user_id", "status"])

    _create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_jti", sa.String(64), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("replaced_by_jti", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("token_jti", name="uq_refresh_token_jti"),
    )
    _create_index("ix_refresh_tokens_user", "refresh_tokens", ["user_id", "revoked_at"])

    _create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("identifier_hash", sa.String(64), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("identifier_hash", name="uq_login_attempt_identifier"),
    )

    _create_table(
        "workflow_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_key", sa.String(100), nullable=False),
        sa.Column("workflow_name", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("steps_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("workflow_key", name="uq_workflow_definition_key"),
    )
    workflow_table = sa.table(
        "workflow_definitions",
        sa.column("workflow_key", sa.String()),
        sa.column("workflow_name", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("steps_json", sa.JSON()),
    )
    op.bulk_insert(workflow_table, [
        {"workflow_key": "scenario_mapping_review", "workflow_name": "场景口径五阶段审核", "enabled": True, "steps_json": _scenario_steps()},
        {"workflow_key": "double_layer_mapping_review", "workflow_name": "双层口径审核", "enabled": True, "steps_json": _review_steps()},
        {"workflow_key": "project_export_review", "workflow_name": "项目导出审核", "enabled": True, "steps_json": _export_steps()},
    ])

    _create_table(
        "workflow_instances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("workflow_key", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(100), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("current_step", sa.String(100)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    _create_index("ix_workflow_target", "workflow_instances", ["project_id", "target_type", "target_id"])

    _create_table(
        "review_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("workflow_instance_id", sa.Integer(), sa.ForeignKey("workflow_instances.id"), nullable=False),
        sa.Column("step_key", sa.String(100), nullable=False),
        sa.Column("task_type", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(100), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("assignee_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("assignee_role", sa.String(50)),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    _create_index("ix_review_task_assignee_status", "review_tasks", ["assignee_user_id", "status"])

    _create_table(
        "review_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("review_task_id", sa.Integer(), sa.ForeignKey("review_tasks.id"), nullable=False),
        sa.Column("decision", sa.String(50), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("content_snapshot_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    _create_table(
        "background_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id")),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id")),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("job_type", sa.String(100), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_step", sa.String(255)),
        sa.Column("payload_summary_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("result_summary_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text()),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("idempotency_key", name="uq_background_job_idempotency"),
    )
    _create_index("ix_background_jobs_project_status", "background_jobs", ["project_id", "status"])

    _create_table(
        "background_job_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("background_job_id", sa.Integer(), sa.ForeignKey("background_jobs.id"), nullable=False),
        sa.Column("item_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("result_summary_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("background_job_id", "item_key", name="uq_background_job_item"),
    )

    _create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id")),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id")),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.String(100)),
        sa.Column("request_id", sa.String(64)),
        sa.Column("before_summary_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("after_summary_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("result", sa.String(50), nullable=False, server_default="success"),
        sa.Column("ip_address_masked", sa.String(100)),
        sa.Column("user_agent_summary", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    _create_index("ix_audit_logs_lookup", "audit_logs", ["institution_id", "project_id", "action", "created_at"])

    _create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id")),
        sa.Column("notification_type", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.String(100)),
        sa.Column("resource_id", sa.String(100)),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    _create_index("ix_notifications_user_read", "notifications", ["user_id", "read_at"])

    _create_table(
        "stored_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id")),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("original_file_name", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("classification", sa.String(50), nullable=False, server_default="internal"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("storage_key", name="uq_stored_files_storage_key"),
    )
    _create_index("ix_stored_files_scope", "stored_files", ["institution_id", "project_id", "classification"])
    _create_index("ix_stored_files_hash", "stored_files", ["content_hash"])


def downgrade() -> None:
    for table in [
        "stored_files", "notifications", "audit_logs", "background_job_items", "background_jobs",
        "review_decisions", "review_tasks", "workflow_instances", "workflow_definitions",
        "login_attempts", "refresh_tokens", "project_memberships", "institution_memberships",
    ]:
        op.drop_table(table)
    _drop_indexes_for_columns("projects", {"institution_id", "project_status", "project_owner_id"})
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("confidentiality_level")
        batch.drop_column("project_owner_id")
        batch.drop_column("project_status")
        batch.drop_column("institution_id")
    _drop_indexes_for_columns("users", {"email", "status", "locked_until"})
    with op.batch_alter_table("users") as batch:
        batch.drop_column("locked_until")
        batch.drop_column("failed_login_count")
        batch.drop_column("last_login_at")
        batch.drop_column("status")
        batch.drop_column("password_hash")
        batch.drop_column("email")
    op.drop_table("institutions")


def _scenario_steps() -> list[dict[str, str]]:
    return [
        {"step_key": "business_draft", "task_type": "fill", "assignee_role": "business_analyst"},
        {"step_key": "business_review", "task_type": "review", "assignee_role": "business_reviewer"},
        {"step_key": "technical_draft", "task_type": "fill", "assignee_role": "technical_analyst"},
        {"step_key": "technical_review", "task_type": "review", "assignee_role": "technical_reviewer"},
        {"step_key": "final_review", "task_type": "review", "assignee_role": "final_reviewer"},
    ]


def _review_steps() -> list[dict[str, str]]:
    return [
        {"step_key": "technical_review", "task_type": "review", "assignee_role": "technical_reviewer"},
        {"step_key": "final_review", "task_type": "review", "assignee_role": "final_reviewer"},
    ]


def _export_steps() -> list[dict[str, str]]:
    return [{"step_key": "final_review", "task_type": "review", "assignee_role": "final_reviewer"}]


def _create_table(name: str, *columns, **kwargs):
    if not sa.inspect(op.get_bind()).has_table(name):
        return op.create_table(name, *columns, **kwargs)
    return None


def _create_index(name: str, table: str, columns: list[str]) -> None:
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns)


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _drop_indexes_for_columns(table: str, columns: set[str]) -> None:
    for index in sa.inspect(op.get_bind()).get_indexes(table):
        if columns.intersection(index.get("column_names") or []):
            op.drop_index(index["name"], table_name=table)
