"""double layer mapping

Revision ID: 202607070003
Revises: 202607070002
Create Date: 2026-07-07

Table definitions are frozen from git history instead of being imported from the
current ORM (see ``app/schema_freeze``).
"""

from alembic import op

from app.schema_freeze import create_frozen_tables, drop_frozen_tables


revision = "202607070003"
down_revision = "202607070002"
branch_labels = None
depends_on = None

FROZEN_REVISION = revision


def upgrade() -> None:
    create_frozen_tables(FROZEN_REVISION, bind=op.get_bind())


def downgrade() -> None:
    drop_frozen_tables(FROZEN_REVISION, bind=op.get_bind())
