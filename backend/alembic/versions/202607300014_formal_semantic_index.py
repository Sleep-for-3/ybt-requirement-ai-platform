"""Add persistent semantic index versions.

Revision ID: 202607300014
Revises: 202607270013
"""

import sqlalchemy as sa
from alembic import op


revision = "202607300014"
down_revision = "202607270013"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    if not _inspector().has_table("embedding_index_versions"):
        op.create_table(
            "embedding_index_versions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=True),
            sa.Column("background_job_id", sa.Integer(), sa.ForeignKey("background_jobs.id"), nullable=True),
            sa.Column("provider", sa.String(length=50), nullable=False),
            sa.Column("model_name", sa.String(length=255), nullable=False),
            sa.Column("model_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("vector_dimension", sa.Integer(), nullable=False),
            sa.Column("distance_metric", sa.String(length=20), nullable=False, server_default="COSINE"),
            sa.Column("collection_name", sa.String(length=255), nullable=False),
            sa.Column("corpus_hash", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="preparing"),
            sa.Column("document_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("indexed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("config_json", sa.JSON(), nullable=False),
            sa.Column("validation_json", sa.JSON(), nullable=False),
            sa.Column("failure_summary", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(length=100), nullable=True),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("collection_name", name="uq_embedding_index_collection"),
        )
        op.create_index("ix_embedding_index_project_status", "embedding_index_versions", ["project_id", "status"])
        op.create_index(
            "uq_embedding_index_one_active_project",
            "embedding_index_versions",
            ["project_id"],
            unique=True,
            postgresql_where=sa.text("status = 'active'"),
            sqlite_where=sa.text("status = 'active'"),
        )
        op.create_index("ix_embedding_index_versions_project_id", "embedding_index_versions", ["project_id"])
        op.create_index("ix_embedding_index_versions_institution_id", "embedding_index_versions", ["institution_id"])
        op.create_index("ix_embedding_index_versions_background_job_id", "embedding_index_versions", ["background_job_id"])
        op.create_index("ix_embedding_index_versions_provider", "embedding_index_versions", ["provider"])
        op.create_index("ix_embedding_index_versions_model_fingerprint", "embedding_index_versions", ["model_fingerprint"])
        op.create_index("ix_embedding_index_versions_corpus_hash", "embedding_index_versions", ["corpus_hash"])
        op.create_index("ix_embedding_index_versions_status", "embedding_index_versions", ["status"])
    else:
        index_names = {
            item["name"] for item in _inspector().get_indexes("embedding_index_versions")
        }
        if "uq_embedding_index_one_active_project" not in index_names:
            op.create_index(
                "uq_embedding_index_one_active_project",
                "embedding_index_versions",
                ["project_id"],
                unique=True,
                postgresql_where=sa.text("status = 'active'"),
                sqlite_where=sa.text("status = 'active'"),
            )

    inspector = _inspector()
    columns = {item["name"] for item in inspector.get_columns("embedding_records")}
    uniques = {item["name"] for item in inspector.get_unique_constraints("embedding_records")}
    indexes = {item["name"] for item in inspector.get_indexes("embedding_records")}
    with op.batch_alter_table("embedding_records") as batch:
        if "embedding_index_version_id" not in columns:
            batch.add_column(sa.Column("embedding_index_version_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                "fk_embedding_records_index_version",
                "embedding_index_versions",
                ["embedding_index_version_id"],
                ["id"],
            )
        if "uq_embedding_unit_provider_model" in uniques:
            batch.drop_constraint("uq_embedding_unit_provider_model", type_="unique")
        if "uq_embedding_index_unit_hash" not in uniques:
            batch.create_unique_constraint(
                "uq_embedding_index_unit_hash",
                ["embedding_index_version_id", "knowledge_unit_id", "content_hash"],
            )
        if "ix_embedding_records_embedding_index_version_id" not in indexes:
            batch.create_index("ix_embedding_records_embedding_index_version_id", ["embedding_index_version_id"])


def downgrade() -> None:
    inspector = _inspector()
    if inspector.has_table("embedding_records"):
        columns = {item["name"] for item in inspector.get_columns("embedding_records")}
        uniques = {item["name"] for item in inspector.get_unique_constraints("embedding_records")}
        indexes = {item["name"] for item in inspector.get_indexes("embedding_records")}
        foreign_keys = {item["name"] for item in inspector.get_foreign_keys("embedding_records")}
        with op.batch_alter_table("embedding_records") as batch:
            if "ix_embedding_records_embedding_index_version_id" in indexes:
                batch.drop_index("ix_embedding_records_embedding_index_version_id")
            if "uq_embedding_index_unit_hash" in uniques:
                batch.drop_constraint("uq_embedding_index_unit_hash", type_="unique")
            if "uq_embedding_unit_provider_model" not in uniques:
                batch.create_unique_constraint(
                    "uq_embedding_unit_provider_model",
                    ["knowledge_unit_id", "embedding_provider", "embedding_model"],
                )
            if "fk_embedding_records_index_version" in foreign_keys:
                batch.drop_constraint("fk_embedding_records_index_version", type_="foreignkey")
            if "embedding_index_version_id" in columns:
                batch.drop_column("embedding_index_version_id")

    if _inspector().has_table("embedding_index_versions"):
        op.drop_table("embedding_index_versions")
