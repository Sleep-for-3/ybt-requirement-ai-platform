"""Add the governed regulatory semantic layer.

Revision ID: 202608200015
Revises: 202607300014
"""

import sqlalchemy as sa
from alembic import op


revision = "202608200015"
down_revision = "202607300014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    semantic_tables = {"semantic_concepts", "semantic_bindings", "semantic_relations"}
    existing = set()
    if not op.get_context().as_sql:
        inspector = sa.inspect(op.get_bind())
        existing = {table for table in semantic_tables if inspector.has_table(table)}
    if existing:
        if existing != semantic_tables:
            raise RuntimeError(f"Partial regulatory semantic schema detected: {sorted(existing)}")
        return
    op.create_table(
        "semantic_concepts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("concept_type", sa.String(length=50), nullable=False),
        sa.Column("concept_code", sa.String(length=150), nullable=False),
        sa.Column("concept_name", sa.String(length=255), nullable=False),
        sa.Column("definition", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("aliases_json", sa.JSON(), nullable=False),
        sa.Column("business_domain", sa.String(length=200), nullable=True),
        sa.Column("owner_department", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("confidence_level", sa.String(length=30), nullable=False, server_default="medium"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_type", sa.String(length=50), nullable=False, server_default="manual"),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("confirmed_by", sa.String(length=100), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "concept_type", "concept_code", name="uq_semantic_concept_project_type_code"),
    )
    op.create_index("ix_semantic_concepts_institution_id", "semantic_concepts", ["institution_id"])
    op.create_index("ix_semantic_concepts_project_id", "semantic_concepts", ["project_id"])
    op.create_index("ix_semantic_concepts_concept_type", "semantic_concepts", ["concept_type"])
    op.create_index("ix_semantic_concepts_status", "semantic_concepts", ["status"])
    op.create_index("ix_semantic_concept_project_status", "semantic_concepts", ["project_id", "status"])
    op.create_index("ix_semantic_concept_project_name", "semantic_concepts", ["project_id", "concept_name"])

    op.create_table(
        "semantic_bindings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("semantic_concept_id", sa.Integer(), sa.ForeignKey("semantic_concepts.id"), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("binding_type", sa.String(length=50), nullable=False, server_default="describes"),
        sa.Column("confidence_level", sa.String(length=30), nullable=False, server_default="medium"),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("source_type", sa.String(length=50), nullable=False, server_default="manual"),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("confirmed_by", sa.String(length=100), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "project_id", "semantic_concept_id", "entity_type", "entity_id", "binding_type",
            name="uq_semantic_binding_concept_entity_type",
        ),
    )
    op.create_index("ix_semantic_bindings_institution_id", "semantic_bindings", ["institution_id"])
    op.create_index("ix_semantic_bindings_project_id", "semantic_bindings", ["project_id"])
    op.create_index("ix_semantic_bindings_semantic_concept_id", "semantic_bindings", ["semantic_concept_id"])
    op.create_index("ix_semantic_bindings_entity_type", "semantic_bindings", ["entity_type"])
    op.create_index("ix_semantic_bindings_entity_id", "semantic_bindings", ["entity_id"])
    op.create_index("ix_semantic_bindings_status", "semantic_bindings", ["status"])
    op.create_index("ix_semantic_binding_entity", "semantic_bindings", ["project_id", "entity_type", "entity_id", "status"])
    op.create_index("ix_semantic_binding_concept_status", "semantic_bindings", ["project_id", "semantic_concept_id", "status"])

    op.create_table(
        "semantic_relations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("source_concept_id", sa.Integer(), sa.ForeignKey("semantic_concepts.id"), nullable=False),
        sa.Column("relation_type", sa.String(length=50), nullable=False),
        sa.Column("target_concept_id", sa.Integer(), sa.ForeignKey("semantic_concepts.id"), nullable=False),
        sa.Column("confidence_level", sa.String(length=30), nullable=False, server_default="medium"),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("source_type", sa.String(length=50), nullable=False, server_default="manual"),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("confirmed_by", sa.String(length=100), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "project_id", "source_concept_id", "relation_type", "target_concept_id",
            name="uq_semantic_relation_triple",
        ),
        sa.CheckConstraint("source_concept_id <> target_concept_id", name="ck_semantic_relation_not_self"),
    )
    op.create_index("ix_semantic_relations_institution_id", "semantic_relations", ["institution_id"])
    op.create_index("ix_semantic_relations_project_id", "semantic_relations", ["project_id"])
    op.create_index("ix_semantic_relations_source_concept_id", "semantic_relations", ["source_concept_id"])
    op.create_index("ix_semantic_relations_target_concept_id", "semantic_relations", ["target_concept_id"])
    op.create_index("ix_semantic_relations_relation_type", "semantic_relations", ["relation_type"])
    op.create_index("ix_semantic_relations_status", "semantic_relations", ["status"])
    op.create_index("ix_semantic_relation_source", "semantic_relations", ["project_id", "source_concept_id", "status"])
    op.create_index("ix_semantic_relation_target", "semantic_relations", ["project_id", "target_concept_id", "status"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind()) if not op.get_context().as_sql else None
    for table in ("semantic_relations", "semantic_bindings", "semantic_concepts"):
        if inspector is None or inspector.has_table(table):
            op.drop_table(table)
