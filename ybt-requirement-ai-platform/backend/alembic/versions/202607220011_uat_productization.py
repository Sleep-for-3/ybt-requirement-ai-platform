"""uat productization and deployment readiness

Revision ID: 202607220011
Revises: 202607200010
"""

import sqlalchemy as sa
from alembic import op


revision = "202607220011"
down_revision = "202607200010"
branch_labels = None
depends_on = None

JSON_OBJECT_DEFAULT = sa.text("'{}'")


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def upgrade() -> None:
    op.create_table(
        "uat_suites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("suite_name", sa.String(length=255), nullable=False),
        sa.Column("suite_type", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("project_id", "suite_name", name="uq_uat_suite_project_name"),
        if_not_exists=True,
    )
    op.create_index("ix_uat_suites_institution_id", "uat_suites", ["institution_id"], if_not_exists=True)
    op.create_index("ix_uat_suites_project_id", "uat_suites", ["project_id"], if_not_exists=True)
    op.create_index("ix_uat_suites_suite_type", "uat_suites", ["suite_type"], if_not_exists=True)
    op.create_index("ix_uat_suites_project_type", "uat_suites", ["project_id", "suite_type"], if_not_exists=True)

    op.create_table(
        "uat_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("uat_suite_id", sa.Integer(), sa.ForeignKey("uat_suites.id"), nullable=False),
        sa.Column("case_code", sa.String(length=100), nullable=False),
        sa.Column("case_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("case_category", sa.String(length=50), nullable=False),
        sa.Column("precondition_json", sa.JSON(), nullable=False, server_default=JSON_OBJECT_DEFAULT),
        sa.Column("input_requirement_json", sa.JSON(), nullable=False, server_default=JSON_OBJECT_DEFAULT),
        sa.Column("expected_result_json", sa.JSON(), nullable=False, server_default=JSON_OBJECT_DEFAULT),
        sa.Column("execution_mode", sa.String(length=20), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.UniqueConstraint("uat_suite_id", "case_code", name="uq_uat_case_suite_code"),
        if_not_exists=True,
    )
    op.create_index("ix_uat_cases_project_id", "uat_cases", ["project_id"], if_not_exists=True)
    op.create_index("ix_uat_cases_uat_suite_id", "uat_cases", ["uat_suite_id"], if_not_exists=True)
    op.create_index("ix_uat_cases_case_code", "uat_cases", ["case_code"], if_not_exists=True)
    op.create_index("ix_uat_cases_case_category", "uat_cases", ["case_category"], if_not_exists=True)
    op.create_index("ix_uat_cases_execution_mode", "uat_cases", ["execution_mode"], if_not_exists=True)
    op.create_index("ix_uat_cases_severity", "uat_cases", ["severity"], if_not_exists=True)
    op.create_index("ix_uat_cases_suite_order", "uat_cases", ["uat_suite_id", "display_order"], if_not_exists=True)

    op.create_table(
        "uat_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("uat_suite_id", sa.Integer(), sa.ForeignKey("uat_suites.id"), nullable=False),
        sa.Column("run_name", sa.String(length=255), nullable=False),
        sa.Column("run_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("environment_name", sa.String(length=100), nullable=False, server_default="test"),
        sa.Column("application_version", sa.String(length=100), nullable=True),
        sa.Column("git_commit_sha", sa.String(length=64), nullable=True),
        sa.Column("started_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=False, server_default=JSON_OBJECT_DEFAULT),
        sa.Column("background_job_id", sa.Integer(), sa.ForeignKey("background_jobs.id"), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("project_id", "uat_suite_id", "run_no", name="uq_uat_run_suite_no"),
        if_not_exists=True,
    )
    op.create_index("ix_uat_runs_institution_id", "uat_runs", ["institution_id"], if_not_exists=True)
    op.create_index("ix_uat_runs_project_id", "uat_runs", ["project_id"], if_not_exists=True)
    op.create_index("ix_uat_runs_uat_suite_id", "uat_runs", ["uat_suite_id"], if_not_exists=True)
    op.create_index("ix_uat_runs_status", "uat_runs", ["status"], if_not_exists=True)
    op.create_index("ix_uat_runs_git_commit_sha", "uat_runs", ["git_commit_sha"], if_not_exists=True)
    op.create_index("ix_uat_runs_background_job_id", "uat_runs", ["background_job_id"], if_not_exists=True)
    op.create_index("ix_uat_runs_project_status", "uat_runs", ["project_id", "status"], if_not_exists=True)

    op.create_table(
        "uat_case_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("uat_run_id", sa.Integer(), sa.ForeignKey("uat_runs.id"), nullable=False),
        sa.Column("uat_case_id", sa.Integer(), sa.ForeignKey("uat_cases.id"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("actual_result_json", sa.JSON(), nullable=False, server_default=JSON_OBJECT_DEFAULT),
        sa.Column("expected_result_json", sa.JSON(), nullable=False, server_default=JSON_OBJECT_DEFAULT),
        sa.Column("evidence_json", sa.JSON(), nullable=False, server_default=JSON_OBJECT_DEFAULT),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("executed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("uat_run_id", "uat_case_id", name="uq_uat_result_run_case"),
        if_not_exists=True,
    )
    op.create_index("ix_uat_case_results_project_id", "uat_case_results", ["project_id"], if_not_exists=True)
    op.create_index("ix_uat_case_results_uat_run_id", "uat_case_results", ["uat_run_id"], if_not_exists=True)
    op.create_index("ix_uat_case_results_uat_case_id", "uat_case_results", ["uat_case_id"], if_not_exists=True)
    op.create_index("ix_uat_case_results_status", "uat_case_results", ["status"], if_not_exists=True)
    op.create_index("ix_uat_case_results_run_status", "uat_case_results", ["uat_run_id", "status"], if_not_exists=True)

    op.create_table(
        "uat_findings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("uat_run_id", sa.Integer(), sa.ForeignKey("uat_runs.id"), nullable=False),
        sa.Column("uat_case_result_id", sa.Integer(), sa.ForeignKey("uat_case_results.id"), nullable=True),
        sa.Column("finding_no", sa.Integer(), nullable=False),
        sa.Column("finding_type", sa.String(length=30), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("reproduction_steps", sa.Text(), nullable=True),
        sa.Column("expected_behavior", sa.Text(), nullable=True),
        sa.Column("actual_behavior", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("assigned_role", sa.String(length=50), nullable=True),
        sa.Column("assigned_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolution_text", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("uat_run_id", "finding_no", name="uq_uat_finding_run_no"),
        if_not_exists=True,
    )
    for column in ("institution_id", "project_id", "uat_run_id", "uat_case_result_id", "finding_type", "severity", "status"):
        op.create_index(f"ix_uat_findings_{column}", "uat_findings", [column], if_not_exists=True)
    op.create_index("ix_uat_findings_run_status", "uat_findings", ["uat_run_id", "status"], if_not_exists=True)

    op.create_table(
        "uat_signoffs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("uat_run_id", sa.Integer(), sa.ForeignKey("uat_runs.id"), nullable=False),
        sa.Column("signoff_role", sa.String(length=30), nullable=False),
        sa.Column("signoff_status", sa.String(length=20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("signed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        *_timestamps(),
        if_not_exists=True,
    )
    op.create_index("ix_uat_signoffs_project_id", "uat_signoffs", ["project_id"], if_not_exists=True)
    op.create_index("ix_uat_signoffs_uat_run_id", "uat_signoffs", ["uat_run_id"], if_not_exists=True)
    op.create_index("ix_uat_signoffs_signoff_role", "uat_signoffs", ["signoff_role"], if_not_exists=True)
    op.create_index("ix_uat_signoffs_signoff_status", "uat_signoffs", ["signoff_status"], if_not_exists=True)
    op.create_index("ix_uat_signoffs_run_role", "uat_signoffs", ["uat_run_id", "signoff_role"], if_not_exists=True)

    op.create_table(
        "uat_packs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("pack_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="uploaded"),
        sa.Column("manifest_json", sa.JSON(), nullable=False, server_default=JSON_OBJECT_DEFAULT),
        sa.Column("validation_json", sa.JSON(), nullable=False, server_default=JSON_OBJECT_DEFAULT),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        *_timestamps(),
        if_not_exists=True,
    )
    op.create_index("ix_uat_packs_institution_id", "uat_packs", ["institution_id"], if_not_exists=True)
    op.create_index("ix_uat_packs_project_id", "uat_packs", ["project_id"], if_not_exists=True)
    op.create_index("ix_uat_packs_status", "uat_packs", ["status"], if_not_exists=True)
    op.create_index("ix_uat_packs_project_status", "uat_packs", ["project_id", "status"], if_not_exists=True)

    op.create_table(
        "uat_pack_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("uat_pack_id", sa.Integer(), sa.ForeignKey("uat_packs.id"), nullable=False),
        sa.Column("stored_file_id", sa.Integer(), sa.ForeignKey("stored_files.id"), nullable=False),
        sa.Column("relative_path", sa.String(length=500), nullable=False),
        sa.Column("original_file_name", sa.String(length=255), nullable=False),
        sa.Column("material_type", sa.String(length=50), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("uat_pack_id", "relative_path", name="uq_uat_pack_item_path"),
        if_not_exists=True,
    )
    op.create_index("ix_uat_pack_items_project_id", "uat_pack_items", ["project_id"], if_not_exists=True)
    op.create_index("ix_uat_pack_items_uat_pack_id", "uat_pack_items", ["uat_pack_id"], if_not_exists=True)
    op.create_index("ix_uat_pack_items_stored_file_id", "uat_pack_items", ["stored_file_id"], if_not_exists=True)
    op.create_index("ix_uat_pack_items_material_type", "uat_pack_items", ["material_type"], if_not_exists=True)
    op.create_index("ix_uat_pack_items_content_hash", "uat_pack_items", ["content_hash"], if_not_exists=True)
    op.create_index("ix_uat_pack_items_pack_type", "uat_pack_items", ["uat_pack_id", "material_type"], if_not_exists=True)


def downgrade() -> None:
    for table_name in (
        "uat_pack_items",
        "uat_packs",
        "uat_signoffs",
        "uat_findings",
        "uat_case_results",
        "uat_runs",
        "uat_cases",
        "uat_suites",
    ):
        op.drop_table(table_name)
