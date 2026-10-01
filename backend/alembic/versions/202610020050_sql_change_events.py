"""SQL change events: the idempotency anchor for automatically triggered impact analysis."""
import sqlalchemy as sa
from alembic import op

revision = "202610020050"
down_revision = "202610020049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sql_change_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("script_file_id", sa.Integer(), sa.ForeignKey("script_files.id"), nullable=False),
        sa.Column("old_version_id", sa.Integer(), sa.ForeignKey("script_file_versions.id"), nullable=True),
        sa.Column("new_version_id", sa.Integer(), sa.ForeignKey("script_file_versions.id"), nullable=False),
        sa.Column("semantic_hash", sa.String(length=64), nullable=False),
        sa.Column("old_semantic_hash", sa.String(length=64), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("categories_json", sa.JSON(), nullable=False),
        sa.Column("diff_summary_json", sa.JSON(), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("agent_task_id", sa.Integer(), sa.ForeignKey("agent_tasks.id"), nullable=True),
        sa.Column("detected_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("project_id", "script_file_id", "old_version_id", "new_version_id", "semantic_hash",
                            name="uq_sql_change_event_identity"),
    )
    op.create_index("ix_sql_change_events_id", "sql_change_events", ["id"])
    op.create_index("ix_sql_change_events_institution_id", "sql_change_events", ["institution_id"])
    op.create_index("ix_sql_change_events_project_id", "sql_change_events", ["project_id"])
    op.create_index("ix_sql_change_events_script_file_id", "sql_change_events", ["script_file_id"])
    op.create_index("ix_sql_change_events_semantic_hash", "sql_change_events", ["semantic_hash"])
    op.create_index("ix_sql_change_events_status", "sql_change_events", ["status"])


def downgrade() -> None:
    op.drop_index("ix_sql_change_events_status", table_name="sql_change_events")
    op.drop_index("ix_sql_change_events_semantic_hash", table_name="sql_change_events")
    op.drop_index("ix_sql_change_events_script_file_id", table_name="sql_change_events")
    op.drop_index("ix_sql_change_events_project_id", table_name="sql_change_events")
    op.drop_index("ix_sql_change_events_institution_id", table_name="sql_change_events")
    op.drop_index("ix_sql_change_events_id", table_name="sql_change_events")
    op.drop_table("sql_change_events")
