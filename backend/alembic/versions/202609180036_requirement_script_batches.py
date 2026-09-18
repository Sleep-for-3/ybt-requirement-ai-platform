"""Group reverse-engineered single-target requirements without changing old scopes."""
from alembic import op
import sqlalchemy as sa

revision = "202609180036"
down_revision = "202609170035"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("requirement_script_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("import_batch_id", sa.Integer(), sa.ForeignKey("resource_import_batches.id")),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_requirement_script_batch_request"))
    op.create_index("ix_requirement_script_batches_project_id", "requirement_script_batches", ["project_id"])


def downgrade():
    op.drop_table("requirement_script_batches")
