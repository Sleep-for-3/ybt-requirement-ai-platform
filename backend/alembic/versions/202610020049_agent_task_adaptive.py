"""Adaptive planning flag on the agent task (Observe -> Replan)."""
import sqlalchemy as sa
from alembic import op

revision = "202610020049"
down_revision = "202610020048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_tasks",
        sa.Column("adaptive", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("agent_tasks", "adaptive")
