"""Add controlled polling configuration for lineage repositories.

Revision ID: 202609100025
Revises: 202609100024

The scheduler only records cadence and enqueues the existing guarded
``script_repository_sync`` job.  It never executes repository content.
"""

from alembic import op
import sqlalchemy as sa


revision = "202609100025"
down_revision = "202609100024"
branch_labels = None
depends_on = None


_COLUMNS = (
    sa.Column("monitor_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("poll_interval_minutes", sa.Integer(), nullable=False, server_default="60"),
    sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("last_monitor_checked_at", sa.DateTime(timezone=True), nullable=True),
    # Soft reference by design; see the model comment.  The referenced job is
    # always revalidated against project/repository scope before display.
    sa.Column("last_monitor_job_id", sa.Integer(), nullable=True),
    sa.Column("last_monitor_error", sa.Text(), nullable=True),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns("code_repositories")}
    for column in _COLUMNS:
        if column.name not in existing:
            op.add_column("code_repositories", column)
    _create_index(
        "ix_code_repositories_monitor_due",
        "code_repositories",
        ["monitor_enabled", "next_poll_at"],
    )
    _create_index(
        "ix_code_repositories_last_monitor_job_id",
        "code_repositories",
        ["last_monitor_job_id"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {item["name"] for item in inspector.get_indexes("code_repositories")}
    for index_name in (
        "ix_code_repositories_last_monitor_job_id",
        "ix_code_repositories_monitor_due",
    ):
        if index_name in indexes:
            op.drop_index(index_name, table_name="code_repositories")
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("code_repositories")}
    for column in reversed(_COLUMNS):
        if column.name in existing:
            op.drop_column("code_repositories", column.name)


def _create_index(name: str, table: str, columns: list[str]) -> None:
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns)
