"""caliber document production

Revision ID: 202607200010
Revises: 202607150009
"""

import sqlalchemy as sa
from alembic import op


revision = "202607200010"
down_revision = "202607150009"
branch_labels = None
depends_on = None


JSON_OBJECT_DEFAULT = sa.text("'{}'")
JSON_ARRAY_DEFAULT = sa.text("'[]'")


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def upgrade() -> None:
    op.create_table(
        "deliverable_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("template_name", sa.String(length=255), nullable=False),
        sa.Column("template_type", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("current_version_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        *_timestamps(),
        if_not_exists=True,
    )
    op.create_table(
        "deliverable_template_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("deliverable_templates.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("stored_file_id", sa.Integer(), sa.ForeignKey("stored_files.id"), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("sheet_config_json", sa.JSON(), nullable=False, server_default=JSON_ARRAY_DEFAULT),
        sa.Column("column_mapping_json", sa.JSON(), nullable=False, server_default=JSON_ARRAY_DEFAULT),
        sa.Column("layout_config_json", sa.JSON(), nullable=False, server_default=JSON_OBJECT_DEFAULT),
        sa.Column("parse_status", sa.String(length=50), nullable=False, server_default="parsed"),
        sa.Column("warnings_json", sa.JSON(), nullable=False, server_default=JSON_ARRAY_DEFAULT),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )
    op.create_table(
        "template_sheet_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "template_version_id",
            sa.Integer(),
            sa.ForeignKey("deliverable_template_versions.id"),
            nullable=False,
        ),
        sa.Column("business_section", sa.String(length=50), nullable=False),
        sa.Column("sheet_name", sa.String(length=255), nullable=False),
        sa.Column("header_row_start", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("header_row_end", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("data_start_row", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("repeat_direction", sa.String(length=20), nullable=False, server_default="vertical"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        if_not_exists=True,
    )
    op.create_table(
        "template_column_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "template_sheet_mapping_id",
            sa.Integer(),
            sa.ForeignKey("template_sheet_mappings.id"),
            nullable=False,
        ),
        sa.Column("business_field", sa.String(length=100), nullable=False),
        sa.Column("excel_column", sa.String(length=10), nullable=False),
        sa.Column("excel_header", sa.String(length=255), nullable=True),
        sa.Column("write_mode", sa.String(length=30), nullable=False, server_default="overwrite"),
        sa.Column("merge_strategy", sa.String(length=30), nullable=False, server_default="none"),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("default_value", sa.Text(), nullable=True),
        sa.Column("format_config_json", sa.JSON(), nullable=False, server_default=JSON_OBJECT_DEFAULT),
        *_timestamps(),
        if_not_exists=True,
    )
    op.create_table(
        "deliverable_packages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("package_name", sa.String(length=255), nullable=False),
        sa.Column("package_type", sa.String(length=50), nullable=False, server_default="full_delivery_package"),
        sa.Column("target_table_id", sa.Integer(), sa.ForeignKey("target_tables.id"), nullable=False),
        sa.Column(
            "template_version_id",
            sa.Integer(),
            sa.ForeignKey("deliverable_template_versions.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="draft"),
        sa.Column("version_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generated_file_id", sa.Integer(), sa.ForeignKey("stored_files.id"), nullable=True),
        sa.Column("generation_job_id", sa.Integer(), sa.ForeignKey("background_jobs.id"), nullable=True),
        sa.Column("render_job_id", sa.Integer(), sa.ForeignKey("background_jobs.id"), nullable=True),
        sa.Column("generation_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("render_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=False, server_default=JSON_OBJECT_DEFAULT),
        sa.Column("warnings_json", sa.JSON(), nullable=False, server_default=JSON_ARRAY_DEFAULT),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        *_timestamps(),
        if_not_exists=True,
    )
    op.create_table(
        "deliverable_field_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "deliverable_package_id",
            sa.Integer(),
            sa.ForeignKey("deliverable_packages.id"),
            nullable=False,
        ),
        sa.Column("target_table_id", sa.Integer(), sa.ForeignKey("target_tables.id"), nullable=False),
        sa.Column("target_field_id", sa.Integer(), sa.ForeignKey("target_fields.id"), nullable=False),
        sa.Column("field_order", sa.Integer(), nullable=False),
        sa.Column("field_status", sa.String(length=50), nullable=False, server_default="not_started"),
        sa.Column("business_summary", sa.Text(), nullable=True),
        sa.Column("technical_summary", sa.Text(), nullable=True),
        sa.Column("source_to_mart_summary", sa.Text(), nullable=True),
        sa.Column("mart_to_ybt_summary", sa.Text(), nullable=True),
        sa.Column("evidence_completeness", sa.Float(), nullable=False, server_default="0"),
        sa.Column("confidence_level", sa.String(length=50), nullable=False, server_default="unverified"),
        sa.Column("open_question_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("validation_result_json", sa.JSON(), nullable=False, server_default=JSON_OBJECT_DEFAULT),
        *_timestamps(),
        if_not_exists=True,
    )
    op.create_table(
        "deliverable_evidence_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "deliverable_package_id",
            sa.Integer(),
            sa.ForeignKey("deliverable_packages.id"),
            nullable=False,
        ),
        sa.Column("target_field_id", sa.Integer(), sa.ForeignKey("target_fields.id"), nullable=False),
        sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("product_scenarios.id"), nullable=True),
        sa.Column("mapping_type", sa.String(length=50), nullable=False),
        sa.Column("mapping_id", sa.Integer(), nullable=False),
        sa.Column("evidence_type", sa.String(length=50), nullable=False),
        sa.Column("evidence_id", sa.Integer(), nullable=True),
        sa.Column("claim_type", sa.String(length=50), nullable=False, server_default="unverified"),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("citation_summary_json", sa.JSON(), nullable=False, server_default=JSON_OBJECT_DEFAULT),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )
    op.create_table(
        "pending_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("target_table_id", sa.Integer(), sa.ForeignKey("target_tables.id"), nullable=False),
        sa.Column("target_field_id", sa.Integer(), sa.ForeignKey("target_fields.id"), nullable=True),
        sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("product_scenarios.id"), nullable=True),
        sa.Column("question_type", sa.String(length=50), nullable=False, server_default="other"),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("question_status", sa.String(length=50), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("assigned_role", sa.String(length=50), nullable=True),
        sa.Column("assigned_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("source_type", sa.String(length=50), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("resolution_text", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        if_not_exists=True,
    )
    op.create_table(
        "historical_caliber_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institutions.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("stored_file_id", sa.Integer(), sa.ForeignKey("stored_files.id"), nullable=False),
        sa.Column("import_name", sa.String(length=255), nullable=False),
        sa.Column("document_type", sa.String(length=50), nullable=False, server_default="unknown"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="parsed"),
        sa.Column("parse_summary_json", sa.JSON(), nullable=False, server_default=JSON_OBJECT_DEFAULT),
        sa.Column("warnings_json", sa.JSON(), nullable=False, server_default=JSON_ARRAY_DEFAULT),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        *_timestamps(),
        if_not_exists=True,
    )
    op.create_table(
        "historical_caliber_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "historical_import_id",
            sa.Integer(),
            sa.ForeignKey("historical_caliber_imports.id"),
            nullable=False,
        ),
        sa.Column("target_table_code", sa.String(length=100), nullable=True),
        sa.Column("target_field_code", sa.String(length=100), nullable=True),
        sa.Column("target_field_name", sa.String(length=255), nullable=True),
        sa.Column("scenario_name", sa.String(length=255), nullable=True),
        sa.Column("business_content", sa.Text(), nullable=True),
        sa.Column("technical_content", sa.Text(), nullable=True),
        sa.Column("source_system_name", sa.String(length=255), nullable=True),
        sa.Column("database_name", sa.String(length=255), nullable=True),
        sa.Column("schema_name", sa.String(length=255), nullable=True),
        sa.Column("source_table_name", sa.String(length=255), nullable=True),
        sa.Column("source_field_name", sa.String(length=255), nullable=True),
        sa.Column("mart_table_name", sa.String(length=255), nullable=True),
        sa.Column("mart_field_name", sa.String(length=255), nullable=True),
        sa.Column("filter_condition", sa.Text(), nullable=True),
        sa.Column("join_condition", sa.Text(), nullable=True),
        sa.Column("code_mapping_rule", sa.Text(), nullable=True),
        sa.Column("priority_rule", sa.Text(), nullable=True),
        sa.Column("null_handling_rule", sa.Text(), nullable=True),
        sa.Column("source_sheet_name", sa.String(length=255), nullable=False),
        sa.Column("source_cell_range", sa.String(length=100), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("match_status", sa.String(length=50), nullable=False, server_default="unmatched"),
        sa.Column("matched_target_field_id", sa.Integer(), sa.ForeignKey("target_fields.id"), nullable=True),
        sa.Column("matched_scenario_id", sa.Integer(), sa.ForeignKey("product_scenarios.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )
    op.create_table(
        "deliverable_package_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "deliverable_package_id",
            sa.Integer(),
            sa.ForeignKey("deliverable_packages.id"),
            nullable=False,
        ),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("generated_file_id", sa.Integer(), sa.ForeignKey("stored_files.id"), nullable=False),
        sa.Column("workflow_instance_id", sa.Integer(), sa.ForeignKey("workflow_instances.id"), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("review_snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column("review_submission_hash", sa.String(length=64), nullable=True),
        sa.Column("content_snapshot_json", sa.JSON(), nullable=False, server_default=JSON_OBJECT_DEFAULT),
        sa.Column("change_summary_json", sa.JSON(), nullable=False, server_default=JSON_OBJECT_DEFAULT),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )
    op.create_table(
        "caliber_comparisons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "historical_import_id",
            sa.Integer(),
            sa.ForeignKey("historical_caliber_imports.id"),
            nullable=True,
        ),
        sa.Column("target_field_id", sa.Integer(), sa.ForeignKey("target_fields.id"), nullable=True),
        sa.Column("left_package_version_id", sa.Integer(), nullable=True),
        sa.Column("right_package_version_id", sa.Integer(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=False, server_default=JSON_OBJECT_DEFAULT),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )

    _create_unique_constraints()
    _create_indexes()


def _create_unique_constraints() -> None:
    constraints = {
        "deliverable_template_versions": [
            ("uq_deliverable_template_version", ["template_id", "version_no"]),
            ("uq_deliverable_template_hash", ["template_id", "file_hash"]),
        ],
        "template_sheet_mappings": [
            ("uq_template_sheet_section", ["template_version_id", "business_section", "sheet_name"]),
        ],
        "template_column_mappings": [
            (
                "uq_template_column_mapping",
                ["template_sheet_mapping_id", "business_field", "excel_column"],
            ),
        ],
        "deliverable_field_items": [
            ("uq_deliverable_field_item", ["deliverable_package_id", "target_field_id"]),
        ],
        "deliverable_package_versions": [
            ("uq_deliverable_package_version", ["deliverable_package_id", "version_no"]),
            ("uq_deliverable_package_workflow", ["deliverable_package_id", "workflow_instance_id"]),
            (
                "uq_deliverable_package_review_snapshot",
                ["deliverable_package_id", "review_snapshot_hash"],
            ),
        ],
    }
    if op.get_bind().dialect.name == "sqlite":
        for table_name, table_constraints in constraints.items():
            existing = {
                item["name"]
                for item in sa.inspect(op.get_bind()).get_unique_constraints(table_name)
                if item.get("name")
            }
            with op.batch_alter_table(table_name) as batch_op:
                for name, columns in table_constraints:
                    if name not in existing:
                        batch_op.create_unique_constraint(name, columns)
        return
    for table_name, table_constraints in constraints.items():
        existing = {
            item["name"]
            for item in sa.inspect(op.get_bind()).get_unique_constraints(table_name)
            if item.get("name")
        }
        for name, columns in table_constraints:
            if name not in existing:
                op.create_unique_constraint(name, table_name, columns)


def _create_indexes() -> None:
    indexes = [
        ("ix_deliverable_templates_institution_id", "deliverable_templates", ["institution_id"]),
        ("ix_deliverable_templates_project_id", "deliverable_templates", ["project_id"]),
        ("ix_deliverable_templates_template_type", "deliverable_templates", ["template_type"]),
        (
            "ix_deliverable_templates_project_type",
            "deliverable_templates",
            ["project_id", "template_type", "enabled"],
        ),
        ("ix_deliverable_template_versions_project_id", "deliverable_template_versions", ["project_id"]),
        ("ix_deliverable_template_versions_template_id", "deliverable_template_versions", ["template_id"]),
        ("ix_deliverable_template_versions_file_hash", "deliverable_template_versions", ["file_hash"]),
        ("ix_template_sheet_mappings_project_id", "template_sheet_mappings", ["project_id"]),
        (
            "ix_template_sheet_mappings_template_version_id",
            "template_sheet_mappings",
            ["template_version_id"],
        ),
        (
            "ix_template_sheet_mappings_business_section",
            "template_sheet_mappings",
            ["business_section"],
        ),
        ("ix_template_column_mappings_project_id", "template_column_mappings", ["project_id"]),
        (
            "ix_template_column_mappings_template_sheet_mapping_id",
            "template_column_mappings",
            ["template_sheet_mapping_id"],
        ),
        (
            "ix_template_column_mappings_business_field",
            "template_column_mappings",
            ["business_field"],
        ),
        ("ix_deliverable_packages_institution_id", "deliverable_packages", ["institution_id"]),
        ("ix_deliverable_packages_project_id", "deliverable_packages", ["project_id"]),
        ("ix_deliverable_packages_target_table_id", "deliverable_packages", ["target_table_id"]),
        ("ix_deliverable_packages_status", "deliverable_packages", ["status"]),
        (
            "ix_deliverable_packages_project_status",
            "deliverable_packages",
            ["project_id", "status"],
        ),
        (
            "ix_deliverable_packages_generation_fingerprint",
            "deliverable_packages",
            ["generation_fingerprint"],
        ),
        (
            "ix_deliverable_packages_render_fingerprint",
            "deliverable_packages",
            ["render_fingerprint"],
        ),
        ("ix_deliverable_field_items_project_id", "deliverable_field_items", ["project_id"]),
        (
            "ix_deliverable_field_items_deliverable_package_id",
            "deliverable_field_items",
            ["deliverable_package_id"],
        ),
        (
            "ix_deliverable_field_items_target_field_id",
            "deliverable_field_items",
            ["target_field_id"],
        ),
        ("ix_deliverable_evidence_items_project_id", "deliverable_evidence_items", ["project_id"]),
        (
            "ix_deliverable_evidence_items_deliverable_package_id",
            "deliverable_evidence_items",
            ["deliverable_package_id"],
        ),
        (
            "ix_deliverable_evidence_items_target_field_id",
            "deliverable_evidence_items",
            ["target_field_id"],
        ),
        ("ix_pending_questions_institution_id", "pending_questions", ["institution_id"]),
        ("ix_pending_questions_project_id", "pending_questions", ["project_id"]),
        ("ix_pending_questions_target_table_id", "pending_questions", ["target_table_id"]),
        ("ix_pending_questions_target_field_id", "pending_questions", ["target_field_id"]),
        ("ix_pending_questions_scenario_id", "pending_questions", ["scenario_id"]),
        ("ix_pending_questions_question_status", "pending_questions", ["question_status"]),
        ("ix_pending_questions_priority", "pending_questions", ["priority"]),
        (
            "ix_pending_questions_project_status_priority",
            "pending_questions",
            ["project_id", "question_status", "priority"],
        ),
        ("ix_historical_caliber_imports_institution_id", "historical_caliber_imports", ["institution_id"]),
        ("ix_historical_caliber_imports_project_id", "historical_caliber_imports", ["project_id"]),
        ("ix_historical_caliber_items_project_id", "historical_caliber_items", ["project_id"]),
        (
            "ix_historical_caliber_items_historical_import_id",
            "historical_caliber_items",
            ["historical_import_id"],
        ),
        (
            "ix_historical_caliber_items_target_field_code",
            "historical_caliber_items",
            ["target_field_code"],
        ),
        ("ix_historical_caliber_items_content_hash", "historical_caliber_items", ["content_hash"]),
        (
            "ix_historical_caliber_items_matched_target_field_id",
            "historical_caliber_items",
            ["matched_target_field_id"],
        ),
        ("ix_caliber_comparisons_project_id", "caliber_comparisons", ["project_id"]),
        ("ix_deliverable_package_versions_project_id", "deliverable_package_versions", ["project_id"]),
        (
            "ix_deliverable_package_versions_deliverable_package_id",
            "deliverable_package_versions",
            ["deliverable_package_id"],
        ),
        (
            "ix_deliverable_package_versions_workflow_instance_id",
            "deliverable_package_versions",
            ["workflow_instance_id"],
        ),
        (
            "ix_deliverable_package_versions_review_snapshot_hash",
            "deliverable_package_versions",
            ["review_snapshot_hash"],
        ),
    ]
    for name, table_name, columns in indexes:
        existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table_name)}
        if name not in existing:
            op.create_index(name, table_name, columns, unique=False)


def downgrade() -> None:
    for table_name in [
        "caliber_comparisons",
        "deliverable_package_versions",
        "historical_caliber_items",
        "historical_caliber_imports",
        "pending_questions",
        "deliverable_evidence_items",
        "deliverable_field_items",
        "deliverable_packages",
        "template_column_mappings",
        "template_sheet_mappings",
        "deliverable_template_versions",
        "deliverable_templates",
    ]:
        op.drop_table(table_name)
