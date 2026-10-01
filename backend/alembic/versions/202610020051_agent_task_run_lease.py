"""Single-runner lease on the agent task (duplicate workers must not execute steps twice)."""
import sqlalchemy as sa
from alembic import op

revision = "202610020051"
down_revision = "202610020050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_tasks", sa.Column("run_lease_until", sa.DateTime(), nullable=True))
    op.create_index("ix_agent_tasks_run_lease_until", "agent_tasks", ["run_lease_until"])


def downgrade() -> None:
    op.drop_index("ix_agent_tasks_run_lease_until", table_name="agent_tasks")
    op.drop_column("agent_tasks", "run_lease_until")
