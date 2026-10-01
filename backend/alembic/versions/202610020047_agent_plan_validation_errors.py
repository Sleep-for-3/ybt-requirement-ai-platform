"""Record planner validation errors and attempts on the plan (V2 strict planning)."""
import sqlalchemy as sa
from alembic import op

revision = "202610020047"
down_revision = "202610020046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_plans",
        sa.Column("validation_errors_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "agent_plans",
        sa.Column("planner_attempts", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )


def downgrade() -> None:
    op.drop_column("agent_plans", "planner_attempts")
    op.drop_column("agent_plans", "validation_errors_json")
