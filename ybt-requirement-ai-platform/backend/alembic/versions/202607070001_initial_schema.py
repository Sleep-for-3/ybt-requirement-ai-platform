"""initial schema

Revision ID: 202607070001
Revises:
Create Date: 2026-07-07
"""

from alembic import op

from app.core.database import Base
from app import models  # noqa: F401

revision = "202607070001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
