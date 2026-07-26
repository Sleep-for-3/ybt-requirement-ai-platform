"""AI runtime profiles and model call observability.

Revision ID: 202607230012
Revises: 202607220011
"""

import sqlalchemy as sa
from alembic import op


revision = "202607230012"
down_revision = "202607220011"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    profile_columns = _columns("model_profiles")
    with op.batch_alter_table("model_profiles") as batch:
        if "api_key_env_name" not in profile_columns:
            batch.add_column(sa.Column("api_key_env_name", sa.String(length=100), nullable=True))
        if "created_by" not in profile_columns:
            batch.add_column(sa.Column("created_by", sa.String(length=100), nullable=True))
    call_columns = _columns("model_call_logs")
    call_indexes = _indexes("model_call_logs")
    with op.batch_alter_table("model_call_logs") as batch:
        if "provider" not in call_columns:
            batch.add_column(sa.Column("provider", sa.String(length=50), nullable=True))
        if "model_name" not in call_columns:
            batch.add_column(sa.Column("model_name", sa.String(length=255), nullable=True))
        if "error_type" not in call_columns:
            batch.add_column(sa.Column("error_type", sa.String(length=100), nullable=True))
        if "ix_model_call_logs_provider" not in call_indexes:
            batch.create_index("ix_model_call_logs_provider", ["provider"])
        if "ix_model_call_logs_model_name" not in call_indexes:
            batch.create_index("ix_model_call_logs_model_name", ["model_name"])
        if "ix_model_call_logs_status" not in call_indexes:
            batch.create_index("ix_model_call_logs_status", ["status"])


def downgrade() -> None:
    call_columns = _columns("model_call_logs")
    call_indexes = _indexes("model_call_logs")
    with op.batch_alter_table("model_call_logs") as batch:
        for index_name in ("ix_model_call_logs_status", "ix_model_call_logs_model_name", "ix_model_call_logs_provider"):
            if index_name in call_indexes:
                batch.drop_index(index_name)
        for column_name in ("error_type", "model_name", "provider"):
            if column_name in call_columns:
                batch.drop_column(column_name)
    profile_columns = _columns("model_profiles")
    with op.batch_alter_table("model_profiles") as batch:
        if "created_by" in profile_columns:
            batch.drop_column("created_by")
        if "api_key_env_name" in profile_columns:
            batch.drop_column("api_key_env_name")
