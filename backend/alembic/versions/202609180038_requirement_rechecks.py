"""Append-only change evidence and explicit replacement revisions."""
from alembic import op
import sqlalchemy as sa

revision = "202609180038"
down_revision = "202609180037"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("requirement_rechecks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("requirement_id", sa.Integer(), sa.ForeignKey("requirements.id"), nullable=False),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey("requirement_revisions.id"), nullable=False),
        sa.Column("replacement_revision_id", sa.Integer(), sa.ForeignKey("requirement_revisions.id")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("change_hash", sa.String(64), nullable=False),
        sa.Column("changes_json", sa.JSON(), nullable=False),
        sa.Column("resolution", sa.String(10000)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("revision_id", "change_hash", name="uq_requirement_recheck_change"))
    op.create_index("ix_requirement_rechecks_project_id", "requirement_rechecks", ["project_id"])
    op.create_index("ix_requirement_rechecks_requirement_id", "requirement_rechecks", ["requirement_id"])


def downgrade():
    op.drop_table("requirement_rechecks")
