"""Durable previews for unified imports; existing upload semantics unchanged."""
from alembic import op
import sqlalchemy as sa

revision = "202609170035"
down_revision = "202609170034"
branch_labels = None
depends_on = None


def timestamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade():
    op.create_table("resource_import_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("options_json", sa.JSON(), nullable=False),
        sa.Column("preview_json", sa.JSON(), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("background_jobs.id")), *timestamps(),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_resource_import_request"))
    op.create_index("ix_resource_import_batches_project_id", "resource_import_batches", ["project_id"])
    op.create_table("resource_import_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("resource_import_batches.id"), nullable=False),
        sa.Column("relative_path", sa.String(1000), nullable=False),
        sa.Column("file_kind", sa.String(30), nullable=False),
        sa.Column("stored_file_id", sa.Integer(), sa.ForeignKey("stored_files.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("parsed_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False), *timestamps(),
        sa.UniqueConstraint("batch_id", "relative_path", name="uq_resource_import_path"))
    op.create_index("ix_resource_import_items_batch_id", "resource_import_items", ["batch_id"])


def downgrade():
    op.drop_table("resource_import_items")
    op.drop_table("resource_import_batches")
