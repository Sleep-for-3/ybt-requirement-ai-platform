"""Attach confirmed requirement rules to existing UAT suites and review workflows."""
from alembic import op
import sqlalchemy as sa

revision = "202609180037"
down_revision = "202609180036"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("requirement_uat_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("requirement_id", sa.Integer(), sa.ForeignKey("requirements.id"), nullable=False),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey("requirement_revisions.id"), nullable=False),
        sa.Column("suite_id", sa.Integer(), sa.ForeignKey("uat_suites.id"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("cases_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("revision_id", name="uq_requirement_uat_revision"),
        sa.UniqueConstraint("suite_id", name="uq_requirement_uat_suite"))
    op.create_index("ix_requirement_uat_links_project_id", "requirement_uat_links", ["project_id"])
    op.create_index("ix_requirement_uat_links_requirement_id", "requirement_uat_links", ["requirement_id"])


def downgrade():
    op.drop_table("requirement_uat_links")
