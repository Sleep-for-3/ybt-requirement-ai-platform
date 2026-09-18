"""Bind requirement revisions to governed review and immutable formal delivery."""

from alembic import op
import sqlalchemy as sa


revision = "202609140032"
down_revision = "202609140031"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("requirement_deliveries") as batch:
        batch.create_unique_constraint(
            "uq_requirement_draft_snapshot",
            ["requirement_id", "requirement_version", "content_hash"],
        )
    op.create_table(
        "requirement_review_submissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("requirement_id", sa.Integer(), sa.ForeignKey("requirements.id"), nullable=False),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey("requirement_revisions.id"), nullable=False),
        sa.Column("content_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("submission_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), server_default="pending_review", nullable=False),
        sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("revision_id", name="uq_requirement_review_revision"),
        sa.UniqueConstraint("submission_hash", name="uq_requirement_review_submission_hash"),
    )
    op.create_index("ix_requirement_review_submissions_project_id", "requirement_review_submissions", ["project_id"])
    op.create_index("ix_requirement_review_submissions_requirement_id", "requirement_review_submissions", ["requirement_id"])
    op.create_index("ix_requirement_review_submissions_revision_id", "requirement_review_submissions", ["revision_id"])
    op.create_index("ix_requirement_review_submissions_status", "requirement_review_submissions", ["status"])
    op.create_table(
        "requirement_formal_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("requirement_id", sa.Integer(), sa.ForeignKey("requirements.id"), nullable=False),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey("requirement_revisions.id"), nullable=False),
        sa.Column("review_submission_id", sa.Integer(), sa.ForeignKey("requirement_review_submissions.id"), nullable=False),
        sa.Column("workflow_instance_id", sa.Integer(), sa.ForeignKey("workflow_instances.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("content_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("stored_file_id", sa.Integer(), sa.ForeignKey("stored_files.id"), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("requirement_id", "version_no", name="uq_requirement_formal_version"),
        sa.UniqueConstraint("review_submission_id", name="uq_requirement_formal_review"),
        sa.UniqueConstraint("workflow_instance_id", name="uq_requirement_formal_workflow"),
    )
    op.create_index("ix_requirement_formal_deliveries_project_id", "requirement_formal_deliveries", ["project_id"])
    op.create_index("ix_requirement_formal_deliveries_requirement_id", "requirement_formal_deliveries", ["requirement_id"])
    op.create_index("ix_requirement_formal_deliveries_revision_id", "requirement_formal_deliveries", ["revision_id"])


def downgrade():
    op.drop_table("requirement_formal_deliveries")
    op.drop_table("requirement_review_submissions")
    with op.batch_alter_table("requirement_deliveries") as batch:
        batch.drop_constraint("uq_requirement_draft_snapshot", type_="unique")
