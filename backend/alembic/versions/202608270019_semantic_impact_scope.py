"""Extend impact analyses with semantic and requirement scope.

Revision ID: 202608270019
Revises: 202608270018
"""

from alembic import op
import sqlalchemy as sa


revision = "202608270019"
down_revision = "202608270018"
branch_labels = None
depends_on = None


_JSON_LIST_COLUMNS = (
    "affected_source_field_ids_json",
    "affected_semantic_binding_ids_json",
    "affected_semantic_concept_ids_json",
    "affected_semantic_version_ids_json",
    "affected_regulatory_rule_ids_json",
    "affected_regulatory_knowledge_item_ids_json",
    "affected_requirement_ids_json",
    "affected_review_task_ids_json",
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns("impact_analyses")}
    for column_name in _JSON_LIST_COLUMNS:
        if column_name not in existing:
            op.add_column(
                "impact_analyses",
                sa.Column(
                    column_name,
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'[]'"),
                ),
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns("impact_analyses")}
    for column_name in reversed(_JSON_LIST_COLUMNS):
        if column_name in existing:
            op.drop_column("impact_analyses", column_name)
