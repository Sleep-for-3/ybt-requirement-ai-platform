"""initial schema

Revision ID: 202607070001
Revises:
Create Date: 2026-07-07

The original body called ``Base.metadata.create_all()``, so this "historical"
revision actually created whatever the working tree happened to contain - a
fresh install silently got today's schema while later revisions became no-ops.

The tables are now frozen from git history: the definitions below are the
metadata that really existed in the commit that introduced this revision.  See
``app/schema_freeze`` (runtime) and ``scripts/migration/frozen_schema_gen.py``
(regeneration tool).
"""

from alembic import op

from app.schema_freeze import create_frozen_tables, drop_frozen_tables


revision = "202607070001"
down_revision = None
branch_labels = None
depends_on = None

FROZEN_REVISION = revision


def upgrade() -> None:
    create_frozen_tables(FROZEN_REVISION, bind=op.get_bind())


def downgrade() -> None:
    drop_frozen_tables(FROZEN_REVISION, bind=op.get_bind())
