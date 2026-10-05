"""N11: durable delivery marker for the background job.

The job row was committed before the broker publish, so a publish failure (or a crash between the
two steps) left the job ``queued`` with no record of whether it had ever been sent.  ``dispatched_at``
makes that state explicit, which lets a compensating dispatcher re-publish the job instead of
losing it.
"""
import sqlalchemy as sa
from alembic import op

revision = "202610050001"
down_revision = "202610030001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("background_jobs", sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_background_jobs_dispatched_at", "background_jobs", ["dispatched_at"])


def downgrade() -> None:
    op.drop_index("ix_background_jobs_dispatched_at", table_name="background_jobs")
    op.drop_column("background_jobs", "dispatched_at")
