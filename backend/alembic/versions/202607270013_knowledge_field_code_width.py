"""Allow knowledge units to reference a list of target field codes.

Revision ID: 202607270013
Revises: 202607230012
"""

import sqlalchemy as sa
from alembic import op


revision = "202607270013"
down_revision = "202607230012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_units") as batch:
        batch.alter_column(
            "target_field_code",
            existing_type=sa.String(length=100),
            type_=sa.String(length=500),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_units") as batch:
        batch.alter_column(
            "target_field_code",
            existing_type=sa.String(length=500),
            type_=sa.String(length=100),
            existing_nullable=True,
        )
