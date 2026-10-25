"""交付前检查留痕

Revision ID: 202611010011
Revises: 202611010010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202611010011"
down_revision = "202611010010"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return name in inspector.get_table_names()


def upgrade() -> None:
    if _table_exists("requirement_delivery_checks"):
        return
    op.create_table(
        "requirement_delivery_checks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("requirement_id", sa.Integer(), sa.ForeignKey("requirements.id"), nullable=False),
        sa.Column(
            "artifact_id",
            sa.Integer(),
            sa.ForeignKey("requirement_render_artifacts.id"),
            nullable=False,
        ),
        sa.Column("checklist_version", sa.String(64), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("blocking_keys_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("checks_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("summary_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_requirement_delivery_checks_project_id", "requirement_delivery_checks", ["project_id"])
    op.create_index("ix_requirement_delivery_checks_requirement_id", "requirement_delivery_checks", ["requirement_id"])
    op.create_index("ix_delivery_check_scope", "requirement_delivery_checks", ["project_id", "requirement_id", "created_at"])
    op.create_index("ix_delivery_check_artifact", "requirement_delivery_checks", ["artifact_id"])


def downgrade() -> None:
    if not _table_exists("requirement_delivery_checks"):
        return
    op.drop_index("ix_delivery_check_artifact", table_name="requirement_delivery_checks")
    op.drop_index("ix_delivery_check_scope", table_name="requirement_delivery_checks")
    op.drop_index("ix_requirement_delivery_checks_requirement_id", table_name="requirement_delivery_checks")
    op.drop_index("ix_requirement_delivery_checks_project_id", table_name="requirement_delivery_checks")
    op.drop_table("requirement_delivery_checks")
