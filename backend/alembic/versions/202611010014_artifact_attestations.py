"""人工核对登记表。"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202611010014"
down_revision = "202611010013"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(table)


def upgrade() -> None:
    if _table_exists("requirement_artifact_attestations"):
        return
    op.create_table(
        "requirement_artifact_attestations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("requirement_id", sa.Integer(), sa.ForeignKey("requirements.id"), nullable=False),
        sa.Column("artifact_id", sa.Integer(), sa.ForeignKey("requirement_render_artifacts.id"), nullable=False),
        sa.Column("scope_code", sa.String(length=64), nullable=False),
        sa.Column("conclusion", sa.String(length=16), nullable=False),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column("attested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_requirement_artifact_attestations_project_id", "requirement_artifact_attestations", ["project_id"])
    op.create_index("ix_requirement_artifact_attestations_requirement_id", "requirement_artifact_attestations", ["requirement_id"])
    op.create_index(
        "ix_artifact_attestation_scope",
        "requirement_artifact_attestations",
        ["project_id", "artifact_id", "created_at"],
    )


def downgrade() -> None:
    if not _table_exists("requirement_artifact_attestations"):
        return
    op.drop_table("requirement_artifact_attestations")
