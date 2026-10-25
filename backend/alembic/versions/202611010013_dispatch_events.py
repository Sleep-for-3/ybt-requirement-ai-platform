"""字段派工状态变更事件表。"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202611010013"
down_revision = "202611010012"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(table)


def upgrade() -> None:
    if _table_exists("requirement_field_dispatch_events"):
        return
    op.create_table(
        "requirement_field_dispatch_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("requirement_id", sa.Integer(), sa.ForeignKey("requirements.id"), nullable=False),
        sa.Column("field_id", sa.Integer(), sa.ForeignKey("target_fields.id"), nullable=False),
        sa.Column("owner", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="in_progress"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_requirement_field_dispatch_events_project_id", "requirement_field_dispatch_events", ["project_id"])
    op.create_index("ix_requirement_field_dispatch_events_requirement_id", "requirement_field_dispatch_events", ["requirement_id"])
    op.create_index("ix_requirement_field_dispatch_events_field_id", "requirement_field_dispatch_events", ["field_id"])
    op.create_index(
        "ix_dispatch_event_scope",
        "requirement_field_dispatch_events",
        ["requirement_id", "field_id", "id"],
    )


def downgrade() -> None:
    if not _table_exists("requirement_field_dispatch_events"):
        return
    op.drop_table("requirement_field_dispatch_events")
