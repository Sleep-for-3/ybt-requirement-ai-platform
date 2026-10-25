"""requirement render artifacts (P1-A)

Revision ID: 202611010003
Revises: 202611010002

Formal requirement documents must be downloadable byte-identically years after
approval.  Rendering is not reproducible (library and zip metadata), so the
rendered bytes are stored once per render identity and every later download
reads that stored file.  A changed template or renderer version produces a new
row and never overwrites an old one.

The table is additive and nullable-safe: existing requirements simply have no
artifact rows until their next export, which renders once and stores.
"""

import sqlalchemy as sa
from alembic import op

revision = "202611010003"
down_revision = "202611010002"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _table_exists("requirement_render_artifacts"):
        return
    op.create_table(
        "requirement_render_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("requirement_id", sa.Integer(), sa.ForeignKey("requirements.id"), nullable=False),
        sa.Column("source_kind", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("format", sa.String(length=10), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column("template_sha256", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("renderer_version", sa.String(length=80), nullable=False),
        sa.Column("config_version", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("render_identity", sa.String(length=64), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_key", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("storage_backend", sa.String(length=40), nullable=False, server_default="local"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ready"),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("diagnostics_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("warnings_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "render_identity", name="uq_requirement_render_identity"),
    )
    op.create_index("ix_requirement_render_artifacts_project_id", "requirement_render_artifacts", ["project_id"])
    op.create_index("ix_requirement_render_artifacts_requirement_id", "requirement_render_artifacts", ["requirement_id"])
    op.create_index("ix_requirement_render_artifacts_source_kind", "requirement_render_artifacts", ["source_kind"])
    op.create_index("ix_requirement_render_artifacts_source_id", "requirement_render_artifacts", ["source_id"])
    op.create_index("ix_requirement_render_artifacts_content_hash", "requirement_render_artifacts", ["content_hash"])
    op.create_index("ix_requirement_render_artifacts_render_identity", "requirement_render_artifacts", ["render_identity"])
    op.create_index("ix_requirement_render_artifacts_file_sha256", "requirement_render_artifacts", ["file_sha256"])
    op.create_index("ix_requirement_render_artifacts_status", "requirement_render_artifacts", ["status"])
    op.create_index(
        "ix_requirement_render_scope",
        "requirement_render_artifacts",
        ["project_id", "requirement_id", "source_kind", "source_id"],
    )


def downgrade() -> None:
    if _table_exists("requirement_render_artifacts"):
        op.drop_table("requirement_render_artifacts")
