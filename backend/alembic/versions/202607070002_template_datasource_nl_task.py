"""template datasource nl task

Revision ID: 202607070002
Revises: 202607070001
Create Date: 2026-07-07

Table definitions are frozen from git history instead of being imported from the
current ORM (see ``app/schema_freeze``).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from app.schema_freeze import create_frozen_tables, drop_frozen_tables


revision = "202607070002"
down_revision = "202607070001"
branch_labels = None
depends_on = None

FROZEN_REVISION = revision

FIELD_MAPPING_DRAFT_COLUMN_NAMES = (
    "template_reference_summary",
    "db_query_summary",
    "data_quality_notes",
    "evidence_completeness",
)


def _field_mapping_draft_columns() -> dict[str, sa.Column]:
    return {
        "template_reference_summary": sa.Column("template_reference_summary", sa.Text(), nullable=True),
        "db_query_summary": sa.Column("db_query_summary", sa.Text(), nullable=True),
        "data_quality_notes": sa.Column("data_quality_notes", sa.Text(), nullable=True),
        "evidence_completeness": sa.Column("evidence_completeness", sa.String(length=50), nullable=True),
    }


def upgrade() -> None:
    bind = op.get_bind()
    create_frozen_tables(FROZEN_REVISION, bind=bind)

    existing = {column["name"] for column in inspect(bind).get_columns("field_mapping_drafts")}
    for name, column in _field_mapping_draft_columns().items():
        if name not in existing:
            op.add_column("field_mapping_drafts", column)


def downgrade() -> None:
    bind = op.get_bind()
    existing = {column["name"] for column in inspect(bind).get_columns("field_mapping_drafts")}
    for name in reversed(FIELD_MAPPING_DRAFT_COLUMN_NAMES):
        if name in existing:
            op.drop_column("field_mapping_drafts", name)
    drop_frozen_tables(FROZEN_REVISION, bind=bind)
