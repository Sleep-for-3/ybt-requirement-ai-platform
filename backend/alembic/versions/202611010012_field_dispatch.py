"""新增字段级派工与处置登记表。"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202611010012"
down_revision = "202611010011"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(table)


def upgrade() -> None:
    if _table_exists("requirement_field_dispatches"):
        return
    op.create_table(
        "requirement_field_dispatches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("requirement_id", sa.Integer(), sa.ForeignKey("requirements.id"), nullable=False),
        sa.Column("field_id", sa.Integer(), sa.ForeignKey("target_fields.id"), nullable=False),
        sa.Column("owner", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="in_progress"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        # 时间戳必须带库侧默认值：应用侧 TimestampMixin 只管 ORM 插入，
        # 直接 SQL 或漏赋值时 NOT NULL 会炸（round 51 踩过一次 NotNullViolation）。
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_requirement_field_dispatches_project_id", "requirement_field_dispatches", ["project_id"])
    op.create_index("ix_requirement_field_dispatches_requirement_id", "requirement_field_dispatches", ["requirement_id"])
    op.create_index("ix_requirement_field_dispatches_field_id", "requirement_field_dispatches", ["field_id"])
    op.create_index("ix_field_dispatch_project", "requirement_field_dispatches", ["project_id", "requirement_id"])
    op.create_unique_constraint(
        "uq_field_dispatch_scope",
        "requirement_field_dispatches",
        ["requirement_id", "field_id"],
    )


def downgrade() -> None:
    if not _table_exists("requirement_field_dispatches"):
        return
    op.drop_table("requirement_field_dispatches")
