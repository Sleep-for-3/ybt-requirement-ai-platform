"""W05 / B07: single-runner lease on the durable background job.

A re-delivered Celery message, a retried job and a crashed worker must never execute the same
handler concurrently, and a job that died mid-run must be recoverable once its lease expires.
"""
import sqlalchemy as sa
from alembic import op

revision = "202610030001"
down_revision = "202610020051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("background_jobs", sa.Column("lease_owner", sa.String(length=120), nullable=True))
    op.add_column("background_jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_background_jobs_lease_expires_at", "background_jobs", ["lease_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_background_jobs_lease_expires_at", table_name="background_jobs")
    op.drop_column("background_jobs", "lease_expires_at")
    op.drop_column("background_jobs", "lease_owner")
