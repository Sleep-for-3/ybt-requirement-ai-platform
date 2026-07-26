"""SQL and shell lineage, script versioning and change impact

Revision ID: 202607150009
Revises: 202607150008
"""

import sqlalchemy as sa
from alembic import op

from app.core.database import Base
from app import models as _models  # noqa: F401 - register model metadata


revision = "202607150009"
down_revision = "202607150008"
branch_labels = None
depends_on = None


TABLES = [
    "code_repositories",
    "script_files",
    "script_file_versions",
    "template_variables",
    "script_dependencies",
    "sql_statements",
    "lineage_nodes",
    "lineage_edges",
    "lineage_resolution_candidates",
    "script_change_sets",
    "script_change_items",
    "impact_analyses",
]


def upgrade() -> None:
    bind = op.get_bind()
    # Historical revision 0001 intentionally creates current metadata on a
    # brand-new database.  checkfirst keeps both fresh and incremental paths
    # valid while the table definitions remain centralized in the models.
    for table_name in TABLES:
        Base.metadata.tables[table_name].create(bind, checkfirst=True)
    for table_name in ("scenario_technical_lineages", "source_to_mart_mappings", "mart_to_ybt_mappings"):
        columns = _columns(table_name)
        with op.batch_alter_table(table_name) as batch_op:
            if "lineage_status" not in columns:
                batch_op.add_column(sa.Column("lineage_status", sa.String(50), nullable=False, server_default="not_linked"))
            if "lineage_last_verified_at" not in columns:
                batch_op.add_column(sa.Column("lineage_last_verified_at", sa.DateTime(timezone=True)))
            if "lineage_change_set_id" not in columns:
                batch_op.add_column(sa.Column(
                    "lineage_change_set_id", sa.Integer(),
                    sa.ForeignKey("script_change_sets.id", name=f"fk_{table_name}_lineage_change_set"),
                ))
        _create_index(f"ix_{table_name}_lineage_status", table_name, ["lineage_status"])
        _create_index(f"ix_{table_name}_lineage_change_set_id", table_name, ["lineage_change_set_id"])


def downgrade() -> None:
    for table_name in ("scenario_technical_lineages", "source_to_mart_mappings", "mart_to_ybt_mappings"):
        columns = _columns(table_name)
        for index_name in (f"ix_{table_name}_lineage_change_set_id", f"ix_{table_name}_lineage_status"):
            if index_name in {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table_name)}:
                op.drop_index(index_name, table_name=table_name)
        with op.batch_alter_table(table_name) as batch_op:
            for column_name in ("lineage_change_set_id", "lineage_last_verified_at", "lineage_status"):
                if column_name in columns:
                    batch_op.drop_column(column_name)
    bind = op.get_bind()
    for table_name in reversed(TABLES):
        Base.metadata.tables[table_name].drop(bind, checkfirst=True)


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _create_index(name: str, table: str, columns: list[str]) -> None:
    existing = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns)
