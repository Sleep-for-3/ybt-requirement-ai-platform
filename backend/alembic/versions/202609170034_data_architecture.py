"""Add architecture configuration without modifying existing catalog rows."""
from alembic import op
import sqlalchemy as sa

revision = "202609170034"
down_revision = "202609160033"
branch_labels = None
depends_on = None


def timestamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade():
    op.create_table("data_architectures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id")),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id")),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition_json", sa.JSON(), nullable=False), *timestamps(),
        sa.CheckConstraint("(project_id IS NULL) <> (institution_id IS NULL)", name="ck_architecture_one_owner"),
        sa.UniqueConstraint("project_id", name="uq_data_architecture_project"),
        sa.UniqueConstraint("institution_id", name="uq_data_architecture_institution"))
    op.create_table("data_architecture_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("architecture_id", sa.Integer(), sa.ForeignKey("data_architectures.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition_json", sa.JSON(), nullable=False), *timestamps(),
        sa.UniqueConstraint("architecture_id", "version", name="uq_architecture_revision"))
    op.create_table("catalog_classifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("catalog_table_id", sa.Integer(), sa.ForeignKey("catalog_tables.id"), nullable=False, unique=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("architecture_revision_id", sa.Integer(), sa.ForeignKey("data_architecture_revisions.id")),
        sa.Column("assignment_json", sa.JSON(), nullable=False), *timestamps())
    op.create_index("ix_catalog_classifications_project_id", "catalog_classifications", ["project_id"])


def downgrade():
    op.drop_table("catalog_classifications")
    op.drop_table("data_architecture_revisions")
    op.drop_table("data_architectures")
