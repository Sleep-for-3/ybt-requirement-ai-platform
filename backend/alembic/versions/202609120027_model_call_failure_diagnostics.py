"""Record provider HTTP status and error detail on model call logs.

Revision ID: 202609120027
Revises: 202609120026

``ModelCallLog`` used to persist only ``error_type`` (for example
``provider_error``).  Operators therefore could not tell a malformed request
(HTTP 400) from a quota problem (429) or a provider-side outage (5xx), and the
real-model rehearsal stalled on exactly that gap.  Both columns stay nullable so
the migration is safe on databases that already contain call history.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "202609120027"
down_revision = "202609120026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_call_logs", sa.Column("http_status", sa.Integer(), nullable=True))
    op.add_column("model_call_logs", sa.Column("error_detail", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("model_call_logs", "error_detail")
    op.drop_column("model_call_logs", "http_status")
