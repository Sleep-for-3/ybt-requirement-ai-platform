"""metadata catalog and safe profiling

Revision ID: 202607140005
Revises: 202607100004

Table definitions are frozen from git history instead of being imported from the
current ORM (see ``app/schema_freeze``).
"""

import sqlalchemy as sa
from alembic import op

from app.schema_freeze import create_frozen_tables, drop_frozen_tables


revision = "202607140005"
down_revision = "202607100004"
branch_labels = None
depends_on = None

FROZEN_REVISION = revision

RECOMMENDATION_COLUMN_NAMES = (
    "catalog_column_id",
    "datasource_id",
    "data_type",
    "nullable",
    "profile_status",
)


def _recommendation_columns() -> dict[str, sa.Column]:
    return {
        "catalog_column_id": sa.Column("catalog_column_id", sa.Integer(), nullable=True),
        "datasource_id": sa.Column("datasource_id", sa.Integer(), nullable=True),
        "data_type": sa.Column("data_type", sa.String(255), nullable=True),
        "nullable": sa.Column("nullable", sa.Boolean(), nullable=True),
        "profile_status": sa.Column("profile_status", sa.String(50), nullable=True),
    }


def upgrade() -> None:
    bind = op.get_bind()
    create_frozen_tables(FROZEN_REVISION, bind=bind)

    # SQLite cannot ALTER to add a constraint, so every column that carries a
    # foreign key goes through batch mode (the pre-existing code only worked
    # because the removed ``create_all`` had already created these columns).
    existing_recommendation = {
        item["name"] for item in sa.inspect(bind).get_columns("candidate_source_recommendations")
    }
    missing_recommendation = [
        name for name in RECOMMENDATION_COLUMN_NAMES if name not in existing_recommendation
    ]
    if missing_recommendation:
        with op.batch_alter_table("candidate_source_recommendations") as batch:
            for name in missing_recommendation:
                batch.add_column(_recommendation_columns()[name])
        with op.batch_alter_table("candidate_source_recommendations") as batch:
            batch.create_foreign_key(
                "fk_candidate_source_recommendations_catalog_column_id",
                "catalog_columns",
                ["catalog_column_id"],
                ["id"],
            )
            batch.create_foreign_key(
                "fk_candidate_source_recommendations_datasource_id",
                "data_sources",
                ["datasource_id"],
                ["id"],
            )

    existing_logs = {item["name"] for item in sa.inspect(bind).get_columns("sql_execution_logs")}
    if "profile_task_id" not in existing_logs:
        with op.batch_alter_table("sql_execution_logs") as batch:
            batch.add_column(sa.Column("profile_task_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                "fk_sql_execution_logs_profile_task_id",
                "column_profile_tasks",
                ["profile_task_id"],
                ["id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    existing_logs = {item["name"] for item in sa.inspect(bind).get_columns("sql_execution_logs")}
    if "profile_task_id" in existing_logs:
        with op.batch_alter_table("sql_execution_logs") as batch:
            batch.drop_column("profile_task_id")

    existing_recommendation = {
        item["name"] for item in sa.inspect(bind).get_columns("candidate_source_recommendations")
    }
    with op.batch_alter_table("candidate_source_recommendations") as batch:
        for constraint in (
            "fk_candidate_source_recommendations_datasource_id",
            "fk_candidate_source_recommendations_catalog_column_id",
        ):
            if constraint in {
                item["name"] for item in sa.inspect(bind).get_foreign_keys("candidate_source_recommendations")
            }:
                batch.drop_constraint(constraint, type_="foreignkey")
        for name in reversed(RECOMMENDATION_COLUMN_NAMES):
            if name in existing_recommendation:
                batch.drop_column(name)

    drop_frozen_tables(FROZEN_REVISION, bind=bind)
