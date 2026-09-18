"""Leased generation items; AI output is a candidate, never a shared write."""
from alembic import op
import sqlalchemy as sa

revision = "202609140031"
down_revision = "202609140030"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("requirement_generation_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("input_id", sa.Integer(), sa.ForeignKey("requirement_generation_inputs.id"), nullable=False),
        sa.Column("field_id", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("lease_key", sa.String(64)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("candidate_json", sa.JSON()),
        sa.Column("candidate_hash", sa.String(64)),
        sa.Column("reason_code", sa.String(80)),
        sa.Column("decision", sa.String(30), server_default="pending", nullable=False),
        sa.Column("decision_reason", sa.String(2000)),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("adopted_content_version", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("input_id", "field_id", "section", name="uq_requirement_generation_item"))
    op.create_index("ix_requirement_generation_items_input_id", "requirement_generation_items", ["input_id"])


def downgrade():
    op.drop_table("requirement_generation_items")
