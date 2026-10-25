"""脚本依据复核决定

Revision ID: 202611010010
Revises: 202611010009
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202611010010"
down_revision = "202611010009"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return name in inspector.get_table_names()


def upgrade() -> None:
    if _table_exists("requirement_script_basis_decisions"):
        return
    op.create_table(
        "requirement_script_basis_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("requirement_id", sa.Integer(), nullable=False),
        sa.Column("script_file_id", sa.Integer(), nullable=False),
        sa.Column("frozen_version_id", sa.Integer(), nullable=False),
        sa.Column("latest_version_id", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        # server_default 不能省：TimestampMixin 靠数据库默认值，漏了真实 Insert 会报
        # NotNullViolation（本轮真实踩到：registered decision 表第一次写入即 500）。
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "requirement_id",
            "script_file_id",
            "latest_version_id",
            name="uq_script_basis_decision",
        ),
    )
    op.create_index(
        "ix_requirement_script_basis_decisions_project_id",
        "requirement_script_basis_decisions",
        ["project_id"],
    )
    op.create_index(
        "ix_requirement_script_basis_decisions_requirement_id",
        "requirement_script_basis_decisions",
        ["requirement_id"],
    )
    op.create_index(
        "ix_requirement_script_basis_decisions_script_file_id",
        "requirement_script_basis_decisions",
        ["script_file_id"],
    )
    op.create_index(
        "ix_script_basis_decision_scope",
        "requirement_script_basis_decisions",
        ["project_id", "requirement_id"],
    )


def downgrade() -> None:
    if not _table_exists("requirement_script_basis_decisions"):
        return
    op.drop_table("requirement_script_basis_decisions")
