"""Retrieval-based decision / case memory (human-confirmed experience).

Written explicitly instead of importing the live ORM: the release gates reject a
migration that reads ``app.models`` or ``Base.metadata`` (see
``tests/test_migration_schema_freeze.py``).

The table is the retrieval store only.  Rows must come from a human approval or
a formal review outcome, and a case may never be cited as a regulatory basis.
"""
import sqlalchemy as sa
from alembic import op

revision = "202610020048"
down_revision = "202610020047"
branch_labels = None
depends_on = None


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "decision_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("scenario_key", sa.String(length=100), nullable=True),
        sa.Column("subject_type", sa.String(length=100), nullable=True),
        sa.Column("subject_id", sa.String(length=200), nullable=True),
        sa.Column("decision_type", sa.String(length=100), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("regulatory_refs_json", sa.JSON(), nullable=False),
        # Soft reference: mapping rows are polymorphic (mapping_type + mapping_id).
        sa.Column("related_mapping_id", sa.Integer(), nullable=True),
        sa.Column("related_requirement_id", sa.Integer(), sa.ForeignKey("requirements.id"), nullable=True),
        sa.Column("related_script_id", sa.Integer(), sa.ForeignKey("script_files.id"), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("confidence_source", sa.String(length=50), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("embedding_version", sa.String(length=100), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_decision_cases_institution_id", "decision_cases", ["institution_id"])
    op.create_index("ix_decision_cases_project_id", "decision_cases", ["project_id"])
    op.create_index("ix_decision_cases_scenario_key", "decision_cases", ["scenario_key"])
    op.create_index("ix_decision_cases_subject_type", "decision_cases", ["subject_type"])
    op.create_index("ix_decision_cases_subject_id", "decision_cases", ["subject_id"])
    op.create_index("ix_decision_cases_decision_type", "decision_cases", ["decision_type"])
    op.create_index("ix_decision_cases_related_mapping_id", "decision_cases", ["related_mapping_id"])
    op.create_index("ix_decision_cases_related_requirement_id", "decision_cases", ["related_requirement_id"])
    op.create_index("ix_decision_cases_related_script_id", "decision_cases", ["related_script_id"])
    op.create_index("ix_decision_cases_created_by", "decision_cases", ["created_by"])
    op.create_index("ix_decision_cases_approved_by", "decision_cases", ["approved_by"])
    op.create_index("ix_decision_cases_confidence_source", "decision_cases", ["confidence_source"])
    op.create_index("ix_decision_cases_effective_from", "decision_cases", ["effective_from"])
    op.create_index("ix_decision_cases_status", "decision_cases", ["status"])
    op.create_index("ix_decision_cases_project_type", "decision_cases", ["project_id", "decision_type"])
    op.create_index("ix_decision_cases_project_status", "decision_cases", ["project_id", "status"])
    op.create_index(
        "ix_decision_cases_project_subject", "decision_cases", ["project_id", "subject_type", "subject_id"]
    )
    op.create_index("ix_decision_cases_project_scenario", "decision_cases", ["project_id", "scenario_key"])
    op.create_index("ix_decision_cases_project_effective", "decision_cases", ["project_id", "effective_from"])


def downgrade() -> None:
    op.drop_index("ix_decision_cases_project_effective", table_name="decision_cases")
    op.drop_index("ix_decision_cases_project_scenario", table_name="decision_cases")
    op.drop_index("ix_decision_cases_project_subject", table_name="decision_cases")
    op.drop_index("ix_decision_cases_project_status", table_name="decision_cases")
    op.drop_index("ix_decision_cases_project_type", table_name="decision_cases")
    op.drop_index("ix_decision_cases_status", table_name="decision_cases")
    op.drop_index("ix_decision_cases_effective_from", table_name="decision_cases")
    op.drop_index("ix_decision_cases_confidence_source", table_name="decision_cases")
    op.drop_index("ix_decision_cases_approved_by", table_name="decision_cases")
    op.drop_index("ix_decision_cases_created_by", table_name="decision_cases")
    op.drop_index("ix_decision_cases_related_script_id", table_name="decision_cases")
    op.drop_index("ix_decision_cases_related_requirement_id", table_name="decision_cases")
    op.drop_index("ix_decision_cases_related_mapping_id", table_name="decision_cases")
    op.drop_index("ix_decision_cases_decision_type", table_name="decision_cases")
    op.drop_index("ix_decision_cases_subject_id", table_name="decision_cases")
    op.drop_index("ix_decision_cases_subject_type", table_name="decision_cases")
    op.drop_index("ix_decision_cases_scenario_key", table_name="decision_cases")
    op.drop_index("ix_decision_cases_project_id", table_name="decision_cases")
    op.drop_index("ix_decision_cases_institution_id", table_name="decision_cases")
    op.drop_table("decision_cases")
