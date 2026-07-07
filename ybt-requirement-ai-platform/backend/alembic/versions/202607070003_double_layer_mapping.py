"""double layer mapping

Revision ID: 202607070003
Revises: 202607070002
Create Date: 2026-07-07
"""

from alembic import op

from app.models import (
    BusinessSystem,
    MappingEvidenceReference,
    MappingVersion,
    MartField,
    MartTable,
    MartToYbtMapping,
    SourceField,
    SourceTable,
    SourceToMartMapping,
)

revision = "202607070003"
down_revision = "202607070002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in [
        BusinessSystem.__table__,
        SourceTable.__table__,
        SourceField.__table__,
        MartTable.__table__,
        MartField.__table__,
        SourceToMartMapping.__table__,
        MartToYbtMapping.__table__,
        MappingEvidenceReference.__table__,
        MappingVersion.__table__,
    ]:
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    for table_name in [
        "mapping_versions",
        "mapping_evidence_references",
        "mart_to_ybt_mappings",
        "source_to_mart_mappings",
        "mart_fields",
        "mart_tables",
        "source_fields",
        "source_tables",
        "business_systems",
    ]:
        try:
            op.drop_table(table_name)
        except Exception:
            pass
