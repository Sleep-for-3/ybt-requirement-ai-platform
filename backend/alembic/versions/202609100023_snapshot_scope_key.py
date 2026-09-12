"""Harden structured requirement snapshot scope identity.

Revision ID: 202609100023
Revises: 202609100022

The original snapshot constraints include nullable ``scenario_id``.  SQL
NULL semantics allow duplicate versions in that case, so this migration adds
one non-null logical scope key and enforces uniqueness on it.
"""

from alembic import op
import sqlalchemy as sa


revision = "202609100023"
down_revision = "202609100022"
branch_labels = None
depends_on = None


TABLE_NAME = "structured_requirement_snapshots"
SCOPE_COLUMN = "scope_key"
VERSION_CONSTRAINT = "uq_structured_requirement_snapshot_scope_key_version"
HASH_CONSTRAINT = "uq_structured_requirement_snapshot_scope_key_hash"
SCOPE_INDEX = "ix_structured_requirement_snapshots_scope_key"


def _scope_key(project_id: int, target_table_id: int, scenario_id: int | None) -> str:
    scenario = int(scenario_id) if scenario_id is not None else 0
    return f"project:{int(project_id)}|target:{int(target_table_id)}|scenario:{scenario}"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE_NAME):
        return

    column_info = {item["name"]: item for item in inspector.get_columns(TABLE_NAME)}
    columns = set(column_info)
    if SCOPE_COLUMN not in columns:
        # Add it nullable first so existing rows can be backfilled on both
        # SQLite and PostgreSQL, then make it non-null in a batch operation.
        op.add_column(TABLE_NAME, sa.Column(SCOPE_COLUMN, sa.String(length=200), nullable=True))
        table = sa.table(
            TABLE_NAME,
            sa.column("id", sa.Integer),
            sa.column("project_id", sa.Integer),
            sa.column("target_table_id", sa.Integer),
            sa.column("scenario_id", sa.Integer),
            sa.column(SCOPE_COLUMN, sa.String(length=200)),
        )
        rows = bind.execute(sa.select(
            table.c.id,
            table.c.project_id,
            table.c.target_table_id,
            table.c.scenario_id,
        )).mappings().all()
        for row in rows:
            bind.execute(
                table.update().where(table.c.id == row["id"]).values(
                    **{SCOPE_COLUMN: _scope_key(row["project_id"], row["target_table_id"], row["scenario_id"])}
                )
            )

    constraints = {item["name"] for item in sa.inspect(bind).get_unique_constraints(TABLE_NAME)}
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes(TABLE_NAME)}
    needs_version = VERSION_CONSTRAINT not in constraints
    needs_hash = HASH_CONSTRAINT not in constraints
    needs_index = SCOPE_INDEX not in indexes

    scope_is_nullable = bool(column_info.get(SCOPE_COLUMN, {}).get("nullable", True))

    if needs_version or needs_hash or scope_is_nullable:
        # ``batch_alter_table`` is required for SQLite, where ALTER TABLE
        # cannot add a named UNIQUE constraint directly.
        with op.batch_alter_table(TABLE_NAME, recreate="always") as batch:
            if scope_is_nullable:
                batch.alter_column(SCOPE_COLUMN, existing_type=sa.String(length=200), nullable=False)
            if needs_version:
                batch.create_unique_constraint(VERSION_CONSTRAINT, [SCOPE_COLUMN, "snapshot_no"])
            if needs_hash:
                batch.create_unique_constraint(HASH_CONSTRAINT, [SCOPE_COLUMN, "content_hash"])
    # If the initial schema migration already created the current model,
    # scope_key is already NOT NULL and there is nothing to alter.

    if needs_index:
        op.create_index(SCOPE_INDEX, TABLE_NAME, [SCOPE_COLUMN], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE_NAME):
        return

    constraints = {item["name"] for item in inspector.get_unique_constraints(TABLE_NAME)}
    indexes = {item["name"] for item in inspector.get_indexes(TABLE_NAME)}
    has_scope = SCOPE_COLUMN in {item["name"] for item in inspector.get_columns(TABLE_NAME)}
    if not has_scope:
        return

    if SCOPE_INDEX in indexes:
        op.drop_index(SCOPE_INDEX, table_name=TABLE_NAME)
    with op.batch_alter_table(TABLE_NAME, recreate="always") as batch:
        if VERSION_CONSTRAINT in constraints:
            batch.drop_constraint(VERSION_CONSTRAINT, type_="unique")
        if HASH_CONSTRAINT in constraints:
            batch.drop_constraint(HASH_CONSTRAINT, type_="unique")
        batch.drop_column(SCOPE_COLUMN)
