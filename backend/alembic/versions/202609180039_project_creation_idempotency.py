"""Add an optional client request key for idempotent project creation."""

from alembic import op
import sqlalchemy as sa


revision = "202609180039"
down_revision = "202609180038"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("projects", sa.Column("creation_request_id", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_projects_creation_request_id",
        "projects",
        ["creation_request_id"],
        unique=True,
    )


def downgrade():
    op.drop_index("ix_projects_creation_request_id", table_name="projects")
    op.drop_column("projects", "creation_request_id")
