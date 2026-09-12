"""scenario traceability

Revision ID: 202607100004
Revises: 202607070003
Create Date: 2026-07-10

Table definitions are frozen from git history instead of being imported from the
current ORM (see ``app/schema_freeze``).
"""

import sqlalchemy as sa
from alembic import op

from app.schema_freeze import create_frozen_tables, drop_frozen_tables


revision = "202607100004"
down_revision = "202607070003"
branch_labels = None
depends_on = None

FROZEN_REVISION = revision

TARGET_FIELD_COLUMN_NAMES = (
    "data_category",
    "data_format",
    "regulatory_original_definition",
    "regulatory_refined_definition",
    "report_name",
    "report_field_name",
    "east_definition",
    "internal_definition",
    "remarks",
)


def _target_field_columns() -> dict[str, sa.Column]:
    return {
        "data_category": sa.Column("data_category", sa.String(length=100), nullable=True),
        "data_format": sa.Column("data_format", sa.String(length=100), nullable=True),
        "regulatory_original_definition": sa.Column("regulatory_original_definition", sa.Text(), nullable=True),
        "regulatory_refined_definition": sa.Column("regulatory_refined_definition", sa.Text(), nullable=True),
        "report_name": sa.Column("report_name", sa.String(length=255), nullable=True),
        "report_field_name": sa.Column("report_field_name", sa.String(length=255), nullable=True),
        "east_definition": sa.Column("east_definition", sa.Text(), nullable=True),
        "internal_definition": sa.Column("internal_definition", sa.Text(), nullable=True),
        "remarks": sa.Column("remarks", sa.Text(), nullable=True),
    }


def upgrade() -> None:
    bind = op.get_bind()
    create_frozen_tables(FROZEN_REVISION, bind=bind)

    existing_columns = {column["name"] for column in sa.inspect(bind).get_columns("target_fields")}
    for name, column in _target_field_columns().items():
        if name not in existing_columns:
            op.add_column("target_fields", column)


def downgrade() -> None:
    bind = op.get_bind()
    drop_frozen_tables(FROZEN_REVISION, bind=bind)

    existing_columns = {column["name"] for column in sa.inspect(bind).get_columns("target_fields")}
    for name in reversed(TARGET_FIELD_COLUMN_NAMES):
        if name in existing_columns:
            op.drop_column("target_fields", name)
