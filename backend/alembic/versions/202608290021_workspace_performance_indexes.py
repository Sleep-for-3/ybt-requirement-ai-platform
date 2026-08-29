"""Add targeted requirement workspace performance indexes.

Revision ID: 202608290021
Revises: 202608280020
"""

from alembic import op


revision = "202608290021"
down_revision = "202608280020"
branch_labels = None
depends_on = None


INDEXES = (
    ("ix_target_fields_project_table", "target_fields", ["project_id", "target_table_id"]),
    ("ix_product_scenarios_project_enabled_order", "product_scenarios", ["project_id", "enabled", "sort_order"]),
    ("ix_scenario_business_field_scenario", "scenario_business_mappings", ["target_field_id", "scenario_id"]),
    ("ix_scenario_technical_field_scenario", "scenario_technical_lineages", ["target_field_id", "scenario_id"]),
    ("ix_source_to_mart_project_field", "source_to_mart_mappings", ["project_id", "mart_field_id"]),
    ("ix_pending_questions_workspace_scope", "pending_questions", ["project_id", "target_table_id", "scenario_id"]),
    ("ix_background_jobs_project_type_id", "background_jobs", ["project_id", "job_type", "id"]),
    ("ix_mapping_evidence_project_mapping", "mapping_evidence_references", ["project_id", "mapping_type", "mapping_id"]),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns, if_not_exists=True)


def downgrade() -> None:
    for name, table, _columns in reversed(INDEXES):
        op.drop_index(name, table_name=table, if_exists=True)
