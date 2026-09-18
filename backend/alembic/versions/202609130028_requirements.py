"""Add scoped requirements and immutable delivery records."""
from alembic import op
import sqlalchemy as sa

revision = "202609130028"
down_revision = "202609120027"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "requirements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_requirements_project_id", "requirements", ["project_id"])
    op.create_table(
        "requirement_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("requirement_id", sa.Integer(), sa.ForeignKey("requirements.id"), nullable=False),
        sa.Column("requirement_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_requirement_deliveries_project_id", "requirement_deliveries", ["project_id"])
    op.create_index("ix_requirement_deliveries_requirement_id", "requirement_deliveries", ["requirement_id"])


def downgrade():
    op.drop_table("requirement_deliveries")
    op.drop_table("requirements")
