"""audit log hash chain columns and chain tail index

Revision ID: 202611010001
Revises: 202610060001

Written with explicit Alembic operations instead of importing the live ORM: the
release gates reject a migration that reads the live model layer.
"""

import sqlalchemy as sa
from alembic import op

revision = "202611010001"
down_revision = "202610060001"
branch_labels = None
depends_on = None

TAIL_INDEX = "ix_audit_logs_chain_tail"


def _column_exists(table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not _column_exists(table_name, column.name):
        op.add_column(table_name, column)


def _drop_column_if_present(table_name: str, column_name: str) -> None:
    if _column_exists(table_name, column_name):
        op.drop_column(table_name, column_name)


def _index_exists(table_name: str, index_name: str) -> bool:
    return index_name in {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    _add_column_if_missing("audit_logs", sa.Column("prev_hash", sa.String(length=64), nullable=True))
    _add_column_if_missing("audit_logs", sa.Column("entry_hash", sa.String(length=64), nullable=True))
    if not _index_exists("audit_logs", TAIL_INDEX):
        op.create_index(TAIL_INDEX, "audit_logs", ["institution_id", "id"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index(TAIL_INDEX, table_name="audit_logs", if_exists=True)
    _drop_column_if_present("audit_logs", "entry_hash")
    _drop_column_if_present("audit_logs", "prev_hash")
