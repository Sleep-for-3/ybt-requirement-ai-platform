"""Add durable metadata drift events.

Revision ID: 202608260017
Revises: 202608200016
"""

from alembic import op
import sqlalchemy as sa


revision = "202608260017"
down_revision = "202608200016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    datasource_columns = {item["name"] for item in inspector.get_columns("data_sources")}
    if "last_database_version" not in datasource_columns:
        op.add_column("data_sources", sa.Column("last_database_version", sa.String(length=300)))
    if "last_discovered_schemas_json" not in datasource_columns:
        op.add_column("data_sources", sa.Column("last_discovered_schemas_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    if inspector.has_table("metadata_drift_events"):
        return
    op.create_table(
        "metadata_drift_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("datasource_id", sa.Integer(), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("sync_task_id", sa.Integer(), sa.ForeignKey("metadata_sync_tasks.id"), nullable=False),
        sa.Column("entity_type", sa.String(length=30), nullable=False),
        sa.Column("entity_key", sa.String(length=800), nullable=False),
        sa.Column("change_type", sa.String(length=30), nullable=False),
        sa.Column("schema_name", sa.String(length=255)),
        sa.Column("table_name", sa.String(length=255)),
        sa.Column("column_name", sa.String(length=255)),
        sa.Column("changed_attributes_json", sa.JSON(), nullable=False),
        sa.Column("previous_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("current_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("rename_candidate_key", sa.String(length=800)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_metadata_drift_events_project_id", "metadata_drift_events", ["project_id"])
    op.create_index("ix_metadata_drift_events_datasource_id", "metadata_drift_events", ["datasource_id"])
    op.create_index("ix_metadata_drift_events_sync_task_id", "metadata_drift_events", ["sync_task_id"])
    op.create_index("ix_metadata_drift_events_entity_type", "metadata_drift_events", ["entity_type"])
    op.create_index("ix_metadata_drift_events_change_type", "metadata_drift_events", ["change_type"])
    op.create_index("ix_metadata_drift_events_schema_name", "metadata_drift_events", ["schema_name"])
    op.create_index("ix_metadata_drift_events_table_name", "metadata_drift_events", ["table_name"])
    op.create_index("ix_metadata_drift_events_column_name", "metadata_drift_events", ["column_name"])
    op.create_index("ix_metadata_drift_events_datasource_created", "metadata_drift_events", ["datasource_id", "created_at"])
    op.create_index("ix_metadata_drift_events_task_change", "metadata_drift_events", ["sync_task_id", "change_type"])


def downgrade() -> None:
    op.drop_table("metadata_drift_events")
    op.drop_column("data_sources", "last_discovered_schemas_json")
    op.drop_column("data_sources", "last_database_version")
