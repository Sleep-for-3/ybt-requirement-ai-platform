"""Add governed, reusable data quality expectations.

Revision ID: 202608270018
Revises: 202608260017
"""

from alembic import op
import sqlalchemy as sa


revision = "202608270018"
down_revision = "202608260017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("data_quality_expectations"):
        op.create_table(
            "data_quality_expectations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("rule_code", sa.String(length=120), nullable=False),
            sa.Column("rule_name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("rule_type", sa.String(length=50), nullable=False),
            sa.Column("expression", sa.Text()),
            sa.Column("parameters_json", sa.JSON(), nullable=False),
            sa.Column("severity", sa.String(length=20), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("source_type", sa.String(length=50), nullable=False),
            sa.Column("source_id", sa.Integer()),
            sa.Column("confidence_level", sa.String(length=20), nullable=False),
            sa.Column("created_by", sa.String(length=100)),
            sa.Column("confirmed_by", sa.String(length=100)),
            sa.Column("confirmed_at", sa.DateTime(timezone=True)),
            sa.Column("status_reason", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("project_id", "rule_code", name="uq_quality_expectations_project_code"),
        )
        op.create_index("ix_data_quality_expectations_project_id", "data_quality_expectations", ["project_id"])
        op.create_index("ix_data_quality_expectations_rule_type", "data_quality_expectations", ["rule_type"])
        op.create_index("ix_data_quality_expectations_status", "data_quality_expectations", ["status"])
        op.create_index("ix_quality_expectations_project_status", "data_quality_expectations", ["project_id", "status"])
        op.create_index("ix_quality_expectations_project_rule_type", "data_quality_expectations", ["project_id", "rule_type"])
    if not inspector.has_table("data_quality_expectation_bindings"):
        op.create_table(
            "data_quality_expectation_bindings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("expectation_id", sa.Integer(), sa.ForeignKey("data_quality_expectations.id"), nullable=False),
            sa.Column("scope_type", sa.String(length=30), nullable=False),
            sa.Column("entity_type", sa.String(length=80), nullable=False),
            sa.Column("entity_id", sa.Integer()),
            sa.Column("entity_key", sa.String(length=500)),
            sa.Column("binding_status", sa.String(length=30), nullable=False),
            sa.Column("configuration_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_data_quality_expectation_bindings_project_id", "data_quality_expectation_bindings", ["project_id"])
        op.create_index("ix_data_quality_expectation_bindings_expectation_id", "data_quality_expectation_bindings", ["expectation_id"])
        op.create_index("ix_data_quality_expectation_bindings_scope_type", "data_quality_expectation_bindings", ["scope_type"])
        op.create_index("ix_data_quality_expectation_bindings_entity_type", "data_quality_expectation_bindings", ["entity_type"])
        op.create_index("ix_data_quality_expectation_bindings_entity_id", "data_quality_expectation_bindings", ["entity_id"])
        op.create_index("ix_data_quality_expectation_bindings_entity_key", "data_quality_expectation_bindings", ["entity_key"])
        op.create_index("ix_data_quality_expectation_bindings_binding_status", "data_quality_expectation_bindings", ["binding_status"])
        op.create_index("ix_quality_expectation_bindings_project_scope", "data_quality_expectation_bindings", ["project_id", "scope_type", "entity_type", "entity_id"])
        op.create_index("ix_quality_expectation_bindings_expectation", "data_quality_expectation_bindings", ["expectation_id"])


def downgrade() -> None:
    op.drop_table("data_quality_expectation_bindings")
    op.drop_table("data_quality_expectations")
