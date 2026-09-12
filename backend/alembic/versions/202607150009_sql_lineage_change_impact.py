"""SQL and shell lineage, script versioning and change impact

Revision ID: 202607150009
Revises: 202607150008

Table definitions are frozen from git history instead of being read from
``Base.metadata`` (see ``app/schema_freeze``).
"""

import sqlalchemy as sa
from alembic import op

from app.schema_freeze import create_frozen_tables, drop_frozen_tables


revision = "202607150009"
down_revision = "202607150008"
branch_labels = None
depends_on = None

FROZEN_REVISION = revision

LINEAGE_LINK_TABLES = (
    "scenario_technical_lineages",
    "source_to_mart_mappings",
    "mart_to_ybt_mappings",
)


def upgrade() -> None:
    bind = op.get_bind()
    create_frozen_tables(FROZEN_REVISION, bind=bind)

    for table_name in LINEAGE_LINK_TABLES:
        columns = _columns(table_name)
        with op.batch_alter_table(table_name) as batch_op:
            if "lineage_status" not in columns:
                batch_op.add_column(sa.Column("lineage_status", sa.String(50), nullable=False, server_default="not_linked"))
            if "lineage_last_verified_at" not in columns:
                batch_op.add_column(sa.Column("lineage_last_verified_at", sa.DateTime(timezone=True)))
            if "lineage_change_set_id" not in columns:
                batch_op.add_column(
                    sa.Column(
                        "lineage_change_set_id",
                        sa.Integer(),
                        sa.ForeignKey("script_change_sets.id", name=f"fk_{table_name}_lineage_change_set"),
                    )
                )
        _create_index(f"ix_{table_name}_lineage_status", table_name, ["lineage_status"])
        _create_index(f"ix_{table_name}_lineage_change_set_id", table_name, ["lineage_change_set_id"])


def downgrade() -> None:
    for table_name in LINEAGE_LINK_TABLES:
        columns = _columns(table_name)
        for index_name in (f"ix_{table_name}_lineage_change_set_id", f"ix_{table_name}_lineage_status"):
            if index_name in {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table_name)}:
                op.drop_index(index_name, table_name=table_name)
        with op.batch_alter_table(table_name) as batch_op:
            for column_name in ("lineage_change_set_id", "lineage_last_verified_at", "lineage_status"):
                if column_name in columns:
                    batch_op.drop_column(column_name)
    drop_frozen_tables(FROZEN_REVISION, bind=op.get_bind())


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _create_index(name: str, table: str, columns: list[str]) -> None:
    existing = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns)
