"""template version parse report column

Revision ID: 202611010002
Revises: 202611010001

P0-C keeps the loss diagnostic of the XLSX template reader next to the version it
belongs to.  The knowledge document side already had ``parse_summary_json``; the
regulatory template version did not, so the structured report (sheet/row counts,
formula cache misses, skipped sheets) could only live in a few flattened warning
strings and was lost on reload.

The column is nullable-safe for existing rows: the reader fills it on the next
upload, and every consumer reads ``parse_report_json or {}``.
"""

import sqlalchemy as sa
from alembic import op

revision = "202611010002"
down_revision = "202611010001"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    if not _column_exists("template_versions", "parse_report_json"):
        op.add_column("template_versions", sa.Column("parse_report_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))


def downgrade() -> None:
    if _column_exists("template_versions", "parse_report_json"):
        op.drop_column("template_versions", "parse_report_json")
