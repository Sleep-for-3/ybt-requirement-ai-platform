"""Add reporting cycles and governed metric snapshots.

Revision ID: 202608280020
Revises: 202608270019
"""

from alembic import op
import sqlalchemy as sa


revision = "202608280020"
down_revision = "202608270019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("reporting_cycles"):
        op.create_table(
            "reporting_cycles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id")),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("cycle_code", sa.String(length=100), nullable=False),
            sa.Column("cycle_name", sa.String(length=255), nullable=False),
            sa.Column("reporting_type", sa.String(length=50), nullable=False),
            sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("data_cutoff_at", sa.DateTime(timezone=True)),
            sa.Column("submission_deadline", sa.DateTime(timezone=True)),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("owner_department", sa.String(length=255)),
            sa.Column("description", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("project_id", "cycle_code", name="uq_reporting_cycles_project_code"),
        )
        op.create_index("ix_reporting_cycles_project_id", "reporting_cycles", ["project_id"])
        op.create_index("ix_reporting_cycles_project_status", "reporting_cycles", ["project_id", "status"])
        op.create_index("ix_reporting_cycles_status", "reporting_cycles", ["status"])
        op.create_index("ix_reporting_cycles_submission_deadline", "reporting_cycles", ["submission_deadline"])
    if not inspector.has_table("metric_snapshots"):
        op.create_table(
            "metric_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id")),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("reporting_cycle_id", sa.Integer(), sa.ForeignKey("reporting_cycles.id"), nullable=False),
            sa.Column("metric_code", sa.String(length=120), nullable=False),
            sa.Column("numerator", sa.Float(), nullable=False),
            sa.Column("denominator", sa.Float(), nullable=False),
            sa.Column("value", sa.Float()),
            sa.Column("scope", sa.String(length=500), nullable=False),
            sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
            sa.Column("calculated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("definition_version", sa.String(length=30), nullable=False),
            sa.UniqueConstraint("project_id", "reporting_cycle_id", "metric_code", name="uq_metric_snapshots_project_cycle_metric"),
        )
        op.create_index("ix_metric_snapshots_project_id", "metric_snapshots", ["project_id"])
        op.create_index("ix_metric_snapshots_reporting_cycle_id", "metric_snapshots", ["reporting_cycle_id"])
        op.create_index("ix_metric_snapshots_metric_code", "metric_snapshots", ["metric_code"])
        op.create_index("ix_metric_snapshots_project_cycle", "metric_snapshots", ["project_id", "reporting_cycle_id"])


def downgrade() -> None:
    op.drop_table("metric_snapshots")
    op.drop_table("reporting_cycles")

