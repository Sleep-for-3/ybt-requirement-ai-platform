"""metadata catalog and safe profiling

Revision ID: 202607140005
Revises: 202607100004
"""

import sqlalchemy as sa
from alembic import op

from app.models import (
    CatalogColumn, CatalogImportBinding, CatalogSchema, CatalogTable,
    ColumnProfileSnapshot, ColumnProfileTask, MetadataImportDocument, MetadataSyncTask,
)

revision = "202607140005"
down_revision = "202607100004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in [
        MetadataSyncTask.__table__, CatalogSchema.__table__, CatalogTable.__table__, CatalogColumn.__table__,
        MetadataImportDocument.__table__, ColumnProfileTask.__table__, ColumnProfileSnapshot.__table__,
        CatalogImportBinding.__table__,
    ]:
        table.create(bind=bind, checkfirst=True)
    existing_recommendation = {item["name"] for item in sa.inspect(bind).get_columns("candidate_source_recommendations")}
    for name, column in {
        "catalog_column_id": sa.Column("catalog_column_id", sa.Integer(), sa.ForeignKey("catalog_columns.id"), nullable=True),
        "datasource_id": sa.Column("datasource_id", sa.Integer(), sa.ForeignKey("data_sources.id"), nullable=True),
        "data_type": sa.Column("data_type", sa.String(255), nullable=True),
        "nullable": sa.Column("nullable", sa.Boolean(), nullable=True),
        "profile_status": sa.Column("profile_status", sa.String(50), nullable=True),
    }.items():
        if name not in existing_recommendation:
            op.add_column("candidate_source_recommendations", column)
    existing_logs = {item["name"] for item in sa.inspect(bind).get_columns("sql_execution_logs")}
    if "profile_task_id" not in existing_logs:
        op.add_column("sql_execution_logs", sa.Column("profile_task_id", sa.Integer(), sa.ForeignKey("column_profile_tasks.id"), nullable=True))


def downgrade() -> None:
    op.drop_column("sql_execution_logs", "profile_task_id")
    for name in ["profile_status", "nullable", "data_type", "datasource_id", "catalog_column_id"]:
        op.drop_column("candidate_source_recommendations", name)
    for name in ["catalog_import_bindings", "column_profile_snapshots", "column_profile_tasks", "metadata_import_documents", "catalog_columns", "catalog_tables", "catalog_schemas", "metadata_sync_tasks"]:
        op.drop_table(name)
