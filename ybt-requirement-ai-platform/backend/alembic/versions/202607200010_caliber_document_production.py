"""caliber document production

Revision ID: 202607200010
Revises: 202607150009
"""
from alembic import op

from app.core.database import Base
from app import models as _models  # noqa: F401

revision = "202607200010"
down_revision = "202607150009"
branch_labels = None
depends_on = None

TABLES = [
    "deliverable_templates", "deliverable_template_versions", "template_sheet_mappings",
    "template_column_mappings", "deliverable_packages", "deliverable_field_items",
    "deliverable_evidence_items", "pending_questions", "historical_caliber_imports",
    "historical_caliber_items", "caliber_comparisons", "deliverable_package_versions",
]


def upgrade() -> None:
    bind = op.get_bind()
    for name in TABLES:
        Base.metadata.tables[name].create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(TABLES):
        Base.metadata.tables[name].drop(bind, checkfirst=True)
