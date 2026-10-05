"""C03: record when *this delivery attempt* was queued.

``background_jobs.created_at`` describes the original enqueue, but a retry reuses the same row.  The
compensating dispatcher measured its grace period from ``created_at`` and additionally required
``dispatched_at IS NULL``; combined with a retry that kept the previous attempt's ``dispatched_at``,
a retried job that failed to publish could never be found again.

``queued_at`` gives each attempt its own queue time so the sweep can use it (falling back to
``created_at`` when NULL, which keeps pre-existing rows working).
"""
import sqlalchemy as sa
from alembic import op

revision = "202610060001"
down_revision = "202610050002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("background_jobs", sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_background_jobs_queued_at", "background_jobs", ["queued_at"])
    # Backfill: existing rows get their original creation time as the attempt queue time, so the
    # sweep keeps working for jobs that predate this column.
    op.execute("UPDATE background_jobs SET queued_at = created_at WHERE queued_at IS NULL")


def downgrade() -> None:
    op.drop_index("ix_background_jobs_queued_at", table_name="background_jobs")
    op.drop_column("background_jobs", "queued_at")
