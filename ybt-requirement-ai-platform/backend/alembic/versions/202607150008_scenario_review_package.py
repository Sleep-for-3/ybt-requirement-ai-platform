"""scenario review package and cancellable celery jobs

Revision ID: 202607150008
Revises: 202607150007
"""

import sqlalchemy as sa
from alembic import op


revision = "202607150008"
down_revision = "202607150007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "governance_workflow_enabled" not in _columns(inspector, "projects"):
        op.add_column("projects", sa.Column("governance_workflow_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    if not inspector.has_table("scenario_review_packages"):
        op.create_table(
            "scenario_review_packages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("target_field_id", sa.Integer(), sa.ForeignKey("target_fields.id"), nullable=False),
            sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("product_scenarios.id"), nullable=False),
            sa.Column("business_mapping_id", sa.Integer(), sa.ForeignKey("scenario_business_mappings.id"), nullable=False),
            sa.Column("technical_lineage_id", sa.Integer(), sa.ForeignKey("scenario_technical_lineages.id"), nullable=False),
            sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
            sa.Column("current_version_no", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("project_id", "target_field_id", "scenario_id", name="uq_scenario_review_package_scope"),
        )
    _create_index("ix_scenario_review_packages_project", "scenario_review_packages", ["project_id", "status"])
    inspector = sa.inspect(op.get_bind())
    if "celery_task_id" not in _columns(inspector, "background_jobs"):
        op.add_column("background_jobs", sa.Column("celery_task_id", sa.String(255)))
    _create_index("ix_background_jobs_celery_task_id", "background_jobs", ["celery_task_id"])


def downgrade() -> None:
    op.drop_index("ix_background_jobs_celery_task_id", table_name="background_jobs")
    op.drop_column("background_jobs", "celery_task_id")
    op.drop_index("ix_scenario_review_packages_project", table_name="scenario_review_packages")
    op.drop_table("scenario_review_packages")
    op.drop_column("projects", "governance_workflow_enabled")


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def _create_index(name: str, table: str, columns: list[str]) -> None:
    existing = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns)
