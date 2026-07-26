"""scenario traceability

Revision ID: 202607100004
Revises: 202607070003
Create Date: 2026-07-10
"""

import sqlalchemy as sa
from alembic import op

from app.models import (
    CandidateSourceRecommendation,
    ProductScenario,
    RegulatoryKnowledgeItem,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    TraceabilityTemplateDocument,
    TraceabilityTemplateParseResult,
)

revision = "202607100004"
down_revision = "202607070003"
branch_labels = None
depends_on = None

TARGET_FIELD_COLUMNS = {
    "data_category": sa.Column("data_category", sa.String(length=100), nullable=True),
    "data_format": sa.Column("data_format", sa.String(length=100), nullable=True),
    "regulatory_original_definition": sa.Column("regulatory_original_definition", sa.Text(), nullable=True),
    "regulatory_refined_definition": sa.Column("regulatory_refined_definition", sa.Text(), nullable=True),
    "report_name": sa.Column("report_name", sa.String(length=255), nullable=True),
    "report_field_name": sa.Column("report_field_name", sa.String(length=255), nullable=True),
    "east_definition": sa.Column("east_definition", sa.Text(), nullable=True),
    "internal_definition": sa.Column("internal_definition", sa.Text(), nullable=True),
    "remarks": sa.Column("remarks", sa.Text(), nullable=True),
}


def upgrade() -> None:
    bind = op.get_bind()
    existing_columns = {column["name"] for column in sa.inspect(bind).get_columns("target_fields")}
    for name, column in TARGET_FIELD_COLUMNS.items():
        if name not in existing_columns:
            op.add_column("target_fields", column)

    for table in [
        ProductScenario.__table__,
        ScenarioBusinessMapping.__table__,
        ScenarioTechnicalLineage.__table__,
        RegulatoryKnowledgeItem.__table__,
        CandidateSourceRecommendation.__table__,
        TraceabilityTemplateDocument.__table__,
        TraceabilityTemplateParseResult.__table__,
    ]:
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    for table_name in [
        "traceability_template_parse_results",
        "traceability_template_documents",
        "candidate_source_recommendations",
        "regulatory_knowledge_items",
        "scenario_technical_lineages",
        "scenario_business_mappings",
        "product_scenarios",
    ]:
        op.drop_table(table_name)
    for name in reversed(TARGET_FIELD_COLUMNS):
        op.drop_column("target_fields", name)
