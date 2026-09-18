"""Add governed template and knowledge document versions.

Revision ID: 202609160033
Revises: 202609140032
"""

from alembic import op
import sqlalchemy as sa


revision = "202609160033"
down_revision = "202609140032"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "template_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("template_document_id", sa.Integer(), sa.ForeignKey("template_documents.id", name="fk_template_versions_template_document_id"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", name="fk_template_versions_project_id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("regulatory_version", sa.String(160)),
        sa.Column("release_batch", sa.String(160)),
        sa.Column("template_code", sa.String(160), nullable=False),
        sa.Column("publisher", sa.String(255)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("effective_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(50), server_default="draft", nullable=False),
        sa.Column("replaces_version_id", sa.Integer(), sa.ForeignKey("template_versions.id", name="fk_template_versions_replaces_version_id")),
        sa.Column("change_note", sa.Text()),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_type", sa.String(50), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("sheet_names_json", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("parsed_snapshot_json", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("parse_status", sa.String(50), server_default="pending", nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("uploaded_by", sa.String(100)),
        sa.Column("reviewed_by", sa.String(100)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("template_document_id", "version_no", name="uq_template_version_no"),
    )
    for name, columns in (
        ("ix_template_versions_template_document_id", ["template_document_id"]),
        ("ix_template_versions_project_id", ["project_id"]),
        ("ix_template_versions_template_code", ["template_code"]),
        ("ix_template_versions_status", ["status"]),
        ("ix_template_versions_file_hash", ["file_hash"]),
    ):
        op.create_index(name, "template_versions", columns)
    with op.batch_alter_table("template_documents") as batch:
        batch.add_column(sa.Column("template_code", sa.String(160)))
        batch.add_column(sa.Column("display_name", sa.String(255)))
        batch.add_column(sa.Column("current_version_id", sa.Integer(), sa.ForeignKey("template_versions.id", name="fk_template_documents_current_version_id")))
        batch.create_index("ix_template_documents_template_code", ["template_code"])
        batch.create_index("ix_template_documents_current_version_id", ["current_version_id"])
    with op.batch_alter_table("template_parse_results") as batch:
        batch.add_column(sa.Column("template_version_id", sa.Integer(), sa.ForeignKey("template_versions.id", name="fk_template_parse_results_template_version_id")))
        batch.create_index("ix_template_parse_results_template_version_id", ["template_version_id"])
    op.create_table(
        "template_applications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", name="fk_template_applications_project_id"), nullable=False),
        sa.Column("template_document_id", sa.Integer(), sa.ForeignKey("template_documents.id", name="fk_template_applications_template_document_id"), nullable=False),
        sa.Column("template_version_id", sa.Integer(), sa.ForeignKey("template_versions.id", name="fk_template_applications_template_version_id")),
        sa.Column("change_set_json", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("before_snapshot_json", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("after_snapshot_json", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("impact_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("applied_by", sa.String(100)),
        sa.Column("applied_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for name, columns in (
        ("ix_template_applications_project_id", ["project_id"]),
        ("ix_template_applications_template_document_id", ["template_document_id"]),
        ("ix_template_applications_template_version_id", ["template_version_id"]),
    ):
        op.create_index(name, "template_applications", columns)

    with op.batch_alter_table("knowledge_documents") as batch:
        batch.add_column(sa.Column("current_version_id", sa.Integer(), sa.ForeignKey("knowledge_document_versions.id", name="fk_knowledge_documents_current_version_id")))
        batch.add_column(sa.Column("logical_code", sa.String(160)))
        batch.add_column(sa.Column("source_category", sa.String(50), server_default="business_material", nullable=False))
        batch.add_column(sa.Column("regulatory_document_no", sa.String(160)))
        batch.add_column(sa.Column("publisher", sa.String(255)))
        batch.add_column(sa.Column("applicable_project_ids_json", sa.JSON(), server_default="[]", nullable=False))
        batch.add_column(sa.Column("applicable_institution_names_json", sa.JSON(), server_default="[]", nullable=False))
        batch.add_column(sa.Column("applicable_field_codes_json", sa.JSON(), server_default="[]", nullable=False))
        batch.add_column(sa.Column("applicable_scenario_ids_json", sa.JSON(), server_default="[]", nullable=False))
        batch.create_index("ix_knowledge_documents_current_version_id", ["current_version_id"])
        batch.create_index("ix_knowledge_documents_logical_code", ["logical_code"])
        batch.create_index("ix_knowledge_documents_source_category", ["source_category"])
        batch.create_index("ix_knowledge_documents_regulatory_document_no", ["regulatory_document_no"])
    with op.batch_alter_table("knowledge_document_versions") as batch:
        batch.add_column(sa.Column("regulatory_version", sa.String(160)))
        batch.add_column(sa.Column("internal_revision", sa.String(160)))
        batch.add_column(sa.Column("publisher", sa.String(255)))
        batch.add_column(sa.Column("published_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("effective_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("lifecycle_status", sa.String(50), server_default="draft", nullable=False))
        batch.add_column(sa.Column("replaces_version_id", sa.Integer(), sa.ForeignKey("knowledge_document_versions.id", name="fk_knowledge_document_versions_replaces_version_id")))
        batch.add_column(sa.Column("reviewed_by", sa.String(100)))
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("activated_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("parse_summary_json", sa.JSON(), server_default="{}", nullable=False))
        batch.add_column(sa.Column("warnings_json", sa.JSON(), server_default="[]", nullable=False))
        batch.add_column(sa.Column("error_message", sa.Text()))
        batch.create_index("ix_knowledge_document_versions_lifecycle_status", ["lifecycle_status"])
        batch.create_index("ix_knowledge_document_versions_replaces_version_id", ["replaces_version_id"])


def downgrade():
    with op.batch_alter_table("knowledge_document_versions") as batch:
        batch.drop_index("ix_knowledge_document_versions_replaces_version_id")
        batch.drop_index("ix_knowledge_document_versions_lifecycle_status")
        for name in ("error_message", "warnings_json", "parse_summary_json", "activated_at", "reviewed_at", "reviewed_by", "replaces_version_id", "lifecycle_status", "expires_at", "effective_at", "published_at", "publisher", "internal_revision", "regulatory_version"):
            batch.drop_column(name)
    with op.batch_alter_table("knowledge_documents") as batch:
        batch.drop_index("ix_knowledge_documents_regulatory_document_no")
        batch.drop_index("ix_knowledge_documents_source_category")
        batch.drop_index("ix_knowledge_documents_logical_code")
        batch.drop_index("ix_knowledge_documents_current_version_id")
        for name in ("applicable_scenario_ids_json", "applicable_field_codes_json", "applicable_institution_names_json", "applicable_project_ids_json", "publisher", "regulatory_document_no", "source_category", "logical_code", "current_version_id"):
            batch.drop_column(name)
    op.drop_table("template_applications")
    with op.batch_alter_table("template_parse_results") as batch:
        batch.drop_index("ix_template_parse_results_template_version_id")
        batch.drop_column("template_version_id")
    with op.batch_alter_table("template_documents") as batch:
        batch.drop_index("ix_template_documents_current_version_id")
        batch.drop_index("ix_template_documents_template_code")
        batch.drop_column("current_version_id")
        batch.drop_column("display_name")
        batch.drop_column("template_code")
    op.drop_table("template_versions")
