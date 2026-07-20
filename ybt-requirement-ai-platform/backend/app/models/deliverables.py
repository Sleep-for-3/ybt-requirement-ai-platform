from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class DeliverableTemplate(Base, TimestampMixin):
    __tablename__ = "deliverable_templates"
    __table_args__ = (Index("ix_deliverable_templates_project_type", "project_id", "template_type", "enabled"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    template_name: Mapped[str] = mapped_column(String(255))
    template_type: Mapped[str] = mapped_column(String(50), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    current_version_no: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class DeliverableTemplateVersion(Base):
    __tablename__ = "deliverable_template_versions"
    __table_args__ = (UniqueConstraint("template_id", "version_no", name="uq_deliverable_template_version"), UniqueConstraint("template_id", "file_hash", name="uq_deliverable_template_hash"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("deliverable_templates.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    stored_file_id: Mapped[int] = mapped_column(ForeignKey("stored_files.id"))
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    sheet_config_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    column_mapping_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    layout_config_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    parse_status: Mapped[str] = mapped_column(String(50), default="parsed")
    warnings_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TemplateSheetMapping(Base, TimestampMixin):
    __tablename__ = "template_sheet_mappings"
    __table_args__ = (UniqueConstraint("template_version_id", "business_section", "sheet_name", name="uq_template_sheet_section"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    template_version_id: Mapped[int] = mapped_column(ForeignKey("deliverable_template_versions.id"), index=True)
    business_section: Mapped[str] = mapped_column(String(50), index=True)
    sheet_name: Mapped[str] = mapped_column(String(255))
    header_row_start: Mapped[int] = mapped_column(Integer, default=1)
    header_row_end: Mapped[int] = mapped_column(Integer, default=1)
    data_start_row: Mapped[int] = mapped_column(Integer, default=2)
    repeat_direction: Mapped[str] = mapped_column(String(20), default="vertical")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class TemplateColumnMapping(Base, TimestampMixin):
    __tablename__ = "template_column_mappings"
    __table_args__ = (UniqueConstraint("template_sheet_mapping_id", "business_field", "excel_column", name="uq_template_column_mapping"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    template_sheet_mapping_id: Mapped[int] = mapped_column(ForeignKey("template_sheet_mappings.id"), index=True)
    business_field: Mapped[str] = mapped_column(String(100), index=True)
    excel_column: Mapped[str] = mapped_column(String(10))
    excel_header: Mapped[str | None] = mapped_column(String(255))
    write_mode: Mapped[str] = mapped_column(String(30), default="overwrite")
    merge_strategy: Mapped[str] = mapped_column(String(30), default="none")
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    default_value: Mapped[str | None] = mapped_column(Text)
    format_config_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)


class DeliverablePackage(Base, TimestampMixin):
    __tablename__ = "deliverable_packages"
    __table_args__ = (Index("ix_deliverable_packages_project_status", "project_id", "status"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    package_name: Mapped[str] = mapped_column(String(255))
    package_type: Mapped[str] = mapped_column(String(50), default="full_delivery_package")
    target_table_id: Mapped[int] = mapped_column(ForeignKey("target_tables.id"), index=True)
    template_version_id: Mapped[int] = mapped_column(ForeignKey("deliverable_template_versions.id"))
    status: Mapped[str] = mapped_column(String(50), default="draft", index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=0)
    generated_file_id: Mapped[int | None] = mapped_column(ForeignKey("stored_files.id"))
    generation_job_id: Mapped[int | None] = mapped_column(ForeignKey("background_jobs.id"))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    warnings_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class DeliverableFieldItem(Base, TimestampMixin):
    __tablename__ = "deliverable_field_items"
    __table_args__ = (UniqueConstraint("deliverable_package_id", "target_field_id", name="uq_deliverable_field_item"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    deliverable_package_id: Mapped[int] = mapped_column(ForeignKey("deliverable_packages.id"), index=True)
    target_table_id: Mapped[int] = mapped_column(ForeignKey("target_tables.id"))
    target_field_id: Mapped[int] = mapped_column(ForeignKey("target_fields.id"), index=True)
    field_order: Mapped[int] = mapped_column(Integer)
    field_status: Mapped[str] = mapped_column(String(50), default="not_started")
    business_summary: Mapped[str | None] = mapped_column(Text)
    technical_summary: Mapped[str | None] = mapped_column(Text)
    source_to_mart_summary: Mapped[str | None] = mapped_column(Text)
    mart_to_ybt_summary: Mapped[str | None] = mapped_column(Text)
    evidence_completeness: Mapped[float] = mapped_column(Float, default=0)
    confidence_level: Mapped[str] = mapped_column(String(50), default="unverified")
    open_question_count: Mapped[int] = mapped_column(Integer, default=0)
    validation_result_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)


class DeliverableEvidenceItem(Base):
    __tablename__ = "deliverable_evidence_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    deliverable_package_id: Mapped[int] = mapped_column(ForeignKey("deliverable_packages.id"), index=True)
    target_field_id: Mapped[int] = mapped_column(ForeignKey("target_fields.id"), index=True)
    scenario_id: Mapped[int | None] = mapped_column(ForeignKey("product_scenarios.id"))
    mapping_type: Mapped[str] = mapped_column(String(50))
    mapping_id: Mapped[int] = mapped_column(Integer)
    evidence_type: Mapped[str] = mapped_column(String(50))
    evidence_id: Mapped[int | None] = mapped_column(Integer)
    claim_type: Mapped[str] = mapped_column(String(50), default="unverified")
    claim_text: Mapped[str] = mapped_column(Text)
    citation_summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PendingQuestion(Base, TimestampMixin):
    __tablename__ = "pending_questions"
    __table_args__ = (Index("ix_pending_questions_project_status_priority", "project_id", "question_status", "priority"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    target_table_id: Mapped[int] = mapped_column(ForeignKey("target_tables.id"), index=True)
    target_field_id: Mapped[int | None] = mapped_column(ForeignKey("target_fields.id"), index=True)
    scenario_id: Mapped[int | None] = mapped_column(ForeignKey("product_scenarios.id"), index=True)
    question_type: Mapped[str] = mapped_column(String(50), default="other")
    question_text: Mapped[str] = mapped_column(Text)
    question_status: Mapped[str] = mapped_column(String(50), default="open", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="medium", index=True)
    assigned_role: Mapped[str | None] = mapped_column(String(50))
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    source_type: Mapped[str | None] = mapped_column(String(50))
    source_id: Mapped[int | None] = mapped_column(Integer)
    resolution_text: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))


class HistoricalCaliberImport(Base, TimestampMixin):
    __tablename__ = "historical_caliber_imports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    stored_file_id: Mapped[int] = mapped_column(ForeignKey("stored_files.id"))
    import_name: Mapped[str] = mapped_column(String(255))
    document_type: Mapped[str] = mapped_column(String(50), default="unknown")
    status: Mapped[str] = mapped_column(String(50), default="parsed")
    parse_summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    warnings_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class HistoricalCaliberItem(Base):
    __tablename__ = "historical_caliber_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    historical_import_id: Mapped[int] = mapped_column(ForeignKey("historical_caliber_imports.id"), index=True)
    target_table_code: Mapped[str | None] = mapped_column(String(100))
    target_field_code: Mapped[str | None] = mapped_column(String(100), index=True)
    target_field_name: Mapped[str | None] = mapped_column(String(255))
    scenario_name: Mapped[str | None] = mapped_column(String(255))
    business_content: Mapped[str | None] = mapped_column(Text)
    technical_content: Mapped[str | None] = mapped_column(Text)
    source_system_name: Mapped[str | None] = mapped_column(String(255))
    database_name: Mapped[str | None] = mapped_column(String(255))
    schema_name: Mapped[str | None] = mapped_column(String(255))
    source_table_name: Mapped[str | None] = mapped_column(String(255))
    source_field_name: Mapped[str | None] = mapped_column(String(255))
    mart_table_name: Mapped[str | None] = mapped_column(String(255))
    mart_field_name: Mapped[str | None] = mapped_column(String(255))
    filter_condition: Mapped[str | None] = mapped_column(Text)
    join_condition: Mapped[str | None] = mapped_column(Text)
    code_mapping_rule: Mapped[str | None] = mapped_column(Text)
    priority_rule: Mapped[str | None] = mapped_column(Text)
    null_handling_rule: Mapped[str | None] = mapped_column(Text)
    source_sheet_name: Mapped[str] = mapped_column(String(255))
    source_cell_range: Mapped[str] = mapped_column(String(100))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    match_status: Mapped[str] = mapped_column(String(50), default="unmatched")
    matched_target_field_id: Mapped[int | None] = mapped_column(ForeignKey("target_fields.id"), index=True)
    matched_scenario_id: Mapped[int | None] = mapped_column(ForeignKey("product_scenarios.id"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CaliberComparison(Base):
    __tablename__ = "caliber_comparisons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    historical_import_id: Mapped[int | None] = mapped_column(ForeignKey("historical_caliber_imports.id"))
    target_field_id: Mapped[int | None] = mapped_column(ForeignKey("target_fields.id"))
    left_package_version_id: Mapped[int | None] = mapped_column(Integer)
    right_package_version_id: Mapped[int | None] = mapped_column(Integer)
    result_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeliverablePackageVersion(Base):
    __tablename__ = "deliverable_package_versions"
    __table_args__ = (UniqueConstraint("deliverable_package_id", "version_no", name="uq_deliverable_package_version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    deliverable_package_id: Mapped[int] = mapped_column(ForeignKey("deliverable_packages.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    generated_file_id: Mapped[int] = mapped_column(ForeignKey("stored_files.id"))
    content_hash: Mapped[str] = mapped_column(String(64))
    content_snapshot_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    change_summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
