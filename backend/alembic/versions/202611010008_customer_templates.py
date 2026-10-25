"""customer_templates

客户需求文档模板注册表。

Revision ID: 202611010008
Revises: 202611010007
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "202611010008"
down_revision = "202611010007"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table in inspector.get_table_names()


def upgrade() -> None:
    if _table_exists("customer_templates"):
        return
    op.create_table(
        "customer_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("format", sa.String(length=10), nullable=False),
        sa.Column("source_file_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("config_digest", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("renderer_version", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("supported_scope_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "name", "version_no", name="uq_customer_template_version"),
    )
    op.create_index("ix_customer_templates_project_id", "customer_templates", ["project_id"])
    op.create_index("ix_customer_template_scope", "customer_templates", ["project_id", "name"])


def downgrade() -> None:
    if not _table_exists("customer_templates"):
        return
    op.drop_index("ix_customer_template_scope", table_name="customer_templates")
    op.drop_index("ix_customer_templates_project_id", table_name="customer_templates")
    op.drop_table("customer_templates")
