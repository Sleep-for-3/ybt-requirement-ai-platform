"""Fixed, bounded requirement generation inputs."""
from alembic import op
import sqlalchemy as sa

revision = "202609140030"
down_revision = "202609140029"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("requirement_generation_inputs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("requirement_id", sa.Integer(), sa.ForeignKey("requirements.id"), nullable=False),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey("requirement_revisions.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("background_jobs.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("requirement_id", "idempotency_key", name="uq_requirement_generation_input_key"))
    op.create_index("ix_requirement_generation_inputs_project_id", "requirement_generation_inputs", ["project_id"])
    op.create_index("ix_requirement_generation_inputs_requirement_id", "requirement_generation_inputs", ["requirement_id"])


def downgrade():
    op.drop_table("requirement_generation_inputs")
