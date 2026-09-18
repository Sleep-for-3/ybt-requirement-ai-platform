"""Append-only isolated requirement content; do not backfill shared facts."""
from alembic import op
import sqlalchemy as sa

revision = "202609140029"
down_revision = "202609130028"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("requirements", sa.Column("content_version", sa.Integer(), nullable=False, server_default="0"))
    op.create_table("requirement_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("requirement_id", sa.Integer(), sa.ForeignKey("requirements.id"), nullable=False),
        sa.Column("content_version", sa.Integer(), nullable=False),
        sa.Column("scope_version", sa.Integer(), nullable=False),
        sa.Column("parent_version", sa.Integer()),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("requirement_id", "content_version", name="uq_requirement_content_version"))
    op.create_index("ix_requirement_revisions_project_id", "requirement_revisions", ["project_id"])
    op.create_index("ix_requirement_revisions_requirement_id", "requirement_revisions", ["requirement_id"])


def downgrade():
    op.drop_table("requirement_revisions")
    op.drop_column("requirements", "content_version")
