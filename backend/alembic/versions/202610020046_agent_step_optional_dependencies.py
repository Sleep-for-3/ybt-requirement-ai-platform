"""Agent step optional dependencies (V2 dependency semantics).

A step may declare dependencies whose absence degrades it (explicit gap) instead
of blocking it. Required dependencies stay in ``depends_on_json``.
"""
import sqlalchemy as sa
from alembic import op

revision = "202610020046"
down_revision = "202610010045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_steps",
        sa.Column("optional_depends_on_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column("agent_steps", "optional_depends_on_json")
