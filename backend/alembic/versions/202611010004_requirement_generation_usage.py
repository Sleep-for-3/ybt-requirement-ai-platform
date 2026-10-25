"""requirement generation item usage ledger (P1-C)

Revision ID: 202611010004
Revises: 202611010003
"""

from alembic import op
import sqlalchemy as sa

revision = "202611010004"
down_revision = "202611010003"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(item["name"] == column for item in inspector.get_columns(table))


def upgrade() -> None:
    if not _column_exists("requirement_generation_items", "usage_json"):
        op.add_column(
            "requirement_generation_items",
            sa.Column("usage_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )


def downgrade() -> None:
    if _column_exists("requirement_generation_items", "usage_json"):
        op.drop_column("requirement_generation_items", "usage_json")
