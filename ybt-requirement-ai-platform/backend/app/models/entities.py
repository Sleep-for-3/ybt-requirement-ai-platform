from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TimestampMixin:
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)
    last_login_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[object | None] = mapped_column(DateTime(timezone=True))


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    bank_name: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_status: Mapped[str] = mapped_column(String(50), default="active", index=True)
    project_owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    confidentiality_level: Mapped[str] = mapped_column(String(50), default="internal")
    governance_workflow_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    target_tables: Mapped[list["TargetTable"]] = relationship(back_populates="project")
    target_fields: Mapped[list["TargetField"]] = relationship(back_populates="project")
    business_systems: Mapped[list["BusinessSystem"]] = relationship(back_populates="project")
    mart_tables: Mapped[list["MartTable"]] = relationship(back_populates="project")


class TargetTable(Base):
    __tablename__ = "target_tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    table_code: Mapped[str] = mapped_column(String(100), nullable=False)
    table_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="target_tables")
    fields: Mapped[list["TargetField"]] = relationship(back_populates="target_table")


class TargetField(Base, TimestampMixin):
    __tablename__ = "target_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    target_table_id: Mapped[int] = mapped_column(ForeignKey("target_tables.id"), index=True)
    field_code: Mapped[str] = mapped_column(String(100), nullable=False)
    field_name: Mapped[str] = mapped_column(String(200), nullable=False)
    field_type: Mapped[str | None] = mapped_column(String(100))
    required_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    field_definition: Mapped[str | None] = mapped_column(Text)
    regulatory_description: Mapped[str | None] = mapped_column(Text)
    data_category: Mapped[str | None] = mapped_column(String(100))
    data_format: Mapped[str | None] = mapped_column(String(100))
    regulatory_original_definition: Mapped[str | None] = mapped_column(Text)
    regulatory_refined_definition: Mapped[str | None] = mapped_column(Text)
    report_name: Mapped[str | None] = mapped_column(String(255))
    report_field_name: Mapped[str | None] = mapped_column(String(255))
    east_definition: Mapped[str | None] = mapped_column(Text)
    internal_definition: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="target_fields")
    target_table: Mapped[TargetTable] = relationship(back_populates="fields")


class BusinessSystem(Base, TimestampMixin):
    __tablename__ = "business_systems"
    __table_args__ = (UniqueConstraint("project_id", "system_code", name="uq_business_systems_project_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    system_code: Mapped[str] = mapped_column(String(100), nullable=False)
    system_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_department: Mapped[str | None] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    project: Mapped[Project] = relationship(back_populates="business_systems")
    source_tables: Mapped[list["SourceTable"]] = relationship(back_populates="business_system")


class SourceTable(Base, TimestampMixin):
    __tablename__ = "source_tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    business_system_id: Mapped[int] = mapped_column(ForeignKey("business_systems.id"), index=True)
    table_code: Mapped[str] = mapped_column(String(100), nullable=False)
    table_name: Mapped[str] = mapped_column(String(200), nullable=False)
    table_comment: Mapped[str | None] = mapped_column(Text)
    datasource_id: Mapped[int | None] = mapped_column(ForeignKey("data_sources.id"))
    database_name: Mapped[str | None] = mapped_column(String(255))
    schema_name: Mapped[str | None] = mapped_column(String(255))
    physical_table_name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)

    business_system: Mapped[BusinessSystem] = relationship(back_populates="source_tables")
    fields: Mapped[list["SourceField"]] = relationship(back_populates="source_table")


class SourceField(Base, TimestampMixin):
    __tablename__ = "source_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    source_table_id: Mapped[int] = mapped_column(ForeignKey("source_tables.id"), index=True)
    field_code: Mapped[str] = mapped_column(String(100), nullable=False)
    field_name: Mapped[str] = mapped_column(String(200), nullable=False)
    field_type: Mapped[str | None] = mapped_column(String(100))
    field_comment: Mapped[str | None] = mapped_column(Text)
    physical_column_name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)

    source_table: Mapped[SourceTable] = relationship(back_populates="fields")


class MartTable(Base, TimestampMixin):
    __tablename__ = "mart_tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    table_code: Mapped[str] = mapped_column(String(100), nullable=False)
    table_name: Mapped[str] = mapped_column(String(200), nullable=False)
    subject_area: Mapped[str | None] = mapped_column(String(200))
    table_comment: Mapped[str | None] = mapped_column(Text)
    datasource_id: Mapped[int | None] = mapped_column(ForeignKey("data_sources.id"))
    database_name: Mapped[str | None] = mapped_column(String(255))
    schema_name: Mapped[str | None] = mapped_column(String(255))
    physical_table_name: Mapped[str | None] = mapped_column(String(255))
    is_existing: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="mart_tables")
    fields: Mapped[list["MartField"]] = relationship(back_populates="mart_table")


class MartField(Base, TimestampMixin):
    __tablename__ = "mart_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    mart_table_id: Mapped[int] = mapped_column(ForeignKey("mart_tables.id"), index=True)
    field_code: Mapped[str] = mapped_column(String(100), nullable=False)
    field_name: Mapped[str] = mapped_column(String(200), nullable=False)
    field_type: Mapped[str | None] = mapped_column(String(100))
    field_comment: Mapped[str | None] = mapped_column(Text)
    physical_column_name: Mapped[str | None] = mapped_column(String(255))
    is_existing: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text)

    mart_table: Mapped[MartTable] = relationship(back_populates="fields")


class ProductScenario(Base, TimestampMixin):
    __tablename__ = "product_scenarios"
    __table_args__ = (UniqueConstraint("project_id", "scenario_code", name="uq_product_scenarios_project_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    scenario_code: Mapped[str] = mapped_column(String(100), nullable=False)
    scenario_name: Mapped[str] = mapped_column(String(200), nullable=False)
    scenario_type: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    business_owner: Mapped[str | None] = mapped_column(String(200))
    tech_owner: Mapped[str | None] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ScenarioBusinessMapping(Base, TimestampMixin):
    __tablename__ = "scenario_business_mappings"
    __table_args__ = (
        UniqueConstraint("project_id", "target_field_id", "scenario_id", name="uq_scenario_business_field_scenario"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    target_field_id: Mapped[int] = mapped_column(ForeignKey("target_fields.id"), index=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("product_scenarios.id"), index=True)
    business_definition: Mapped[str | None] = mapped_column(Text)
    source_system_screenshot_required: Mapped[bool] = mapped_column(Boolean, default=False)
    source_system_change_required: Mapped[bool] = mapped_column(Boolean, default=False)
    external_data_required: Mapped[bool] = mapped_column(Boolean, default=False)
    manual_supplement_required: Mapped[bool] = mapped_column(Boolean, default=False)
    business_owner: Mapped[str | None] = mapped_column(String(200))
    business_confirm_status: Mapped[str] = mapped_column(String(50), default="draft")
    business_confirm_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    remarks: Mapped[str | None] = mapped_column(Text)
    ai_generated_content: Mapped[str | None] = mapped_column(Text)
    final_content: Mapped[str | None] = mapped_column(Text)
    confidence_level: Mapped[str] = mapped_column(String(50), default="medium")
    open_questions: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(100))


class ScenarioTechnicalLineage(Base, TimestampMixin):
    __tablename__ = "scenario_technical_lineages"
    __table_args__ = (
        UniqueConstraint("project_id", "target_field_id", "scenario_id", name="uq_scenario_lineage_field_scenario"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    target_field_id: Mapped[int] = mapped_column(ForeignKey("target_fields.id"), index=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("product_scenarios.id"), index=True)
    business_mapping_id: Mapped[int | None] = mapped_column(ForeignKey("scenario_business_mappings.id"))
    source_system_name: Mapped[str | None] = mapped_column(String(255))
    source_database_name: Mapped[str | None] = mapped_column(String(255))
    source_schema_name: Mapped[str | None] = mapped_column(String(255))
    source_table_english_name: Mapped[str | None] = mapped_column(String(255))
    source_table_chinese_name: Mapped[str | None] = mapped_column(String(255))
    source_field_english_name: Mapped[str | None] = mapped_column(String(255))
    source_field_chinese_name: Mapped[str | None] = mapped_column(String(255))
    processing_logic: Mapped[str | None] = mapped_column(Text)
    processing_logic_type: Mapped[str | None] = mapped_column(String(50))
    tech_owner: Mapped[str | None] = mapped_column(String(200))
    tech_confirm_status: Mapped[str] = mapped_column(String(50), default="draft")
    tech_confirm_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    remarks: Mapped[str | None] = mapped_column(Text)
    ai_generated_content: Mapped[str | None] = mapped_column(Text)
    final_content: Mapped[str | None] = mapped_column(Text)
    confidence_level: Mapped[str] = mapped_column(String(50), default="medium")
    open_questions: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(100))
    lineage_status: Mapped[str] = mapped_column(String(50), default="not_linked", index=True)
    lineage_last_verified_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    lineage_change_set_id: Mapped[int | None] = mapped_column(ForeignKey("script_change_sets.id"), index=True)


class RegulatoryKnowledgeItem(Base, TimestampMixin):
    __tablename__ = "regulatory_knowledge_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    knowledge_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    target_table_code: Mapped[str | None] = mapped_column(String(100), index=True)
    target_field_code: Mapped[str | None] = mapped_column(String(100), index=True)
    target_field_name: Mapped[str | None] = mapped_column(String(200))
    scenario_id: Mapped[int | None] = mapped_column(ForeignKey("product_scenarios.id"), index=True)
    question_text: Mapped[str | None] = mapped_column(Text)
    answer_text: Mapped[str | None] = mapped_column(Text)
    institution_suggestion: Mapped[str | None] = mapped_column(Text)
    regulatory_reply: Mapped[str | None] = mapped_column(Text)
    business_explanation: Mapped[str | None] = mapped_column(Text)
    source_document_name: Mapped[str | None] = mapped_column(String(255))
    source_sheet_name: Mapped[str | None] = mapped_column(String(255))
    source_cell_range: Mapped[str | None] = mapped_column(String(100))
    tags_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)


class CandidateSourceRecommendation(Base, TimestampMixin):
    __tablename__ = "candidate_source_recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    target_field_id: Mapped[int] = mapped_column(ForeignKey("target_fields.id"), index=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("product_scenarios.id"), index=True)
    recommended_source_system: Mapped[str | None] = mapped_column(String(255))
    recommended_database_name: Mapped[str | None] = mapped_column(String(255))
    recommended_schema_name: Mapped[str | None] = mapped_column(String(255))
    recommended_table_name: Mapped[str | None] = mapped_column(String(255))
    recommended_table_comment: Mapped[str | None] = mapped_column(Text)
    recommended_field_name: Mapped[str | None] = mapped_column(String(255))
    recommended_field_comment: Mapped[str | None] = mapped_column(Text)
    recommended_processing_logic: Mapped[str | None] = mapped_column(Text)
    recommend_reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_summary: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_level: Mapped[str] = mapped_column(String(50), default="medium")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    selected_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    catalog_column_id: Mapped[int | None] = mapped_column(ForeignKey("catalog_columns.id"), index=True)
    datasource_id: Mapped[int | None] = mapped_column(ForeignKey("data_sources.id"), index=True)
    data_type: Mapped[str | None] = mapped_column(String(255))
    nullable: Mapped[bool | None] = mapped_column(Boolean)
    profile_status: Mapped[str | None] = mapped_column(String(50))
    retrieval_log_id: Mapped[int | None] = mapped_column(ForeignKey("retrieval_logs.id"), index=True)
    knowledge_unit_ids_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    citation_summary_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    recommendation_basis: Mapped[str | None] = mapped_column(String(100))


class TraceabilityTemplateDocument(Base, TimestampMixin):
    __tablename__ = "traceability_template_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    parse_status: Mapped[str] = mapped_column(String(50), default="pending")
    sheet_names_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    detected_scenarios_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    parse_summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    warnings_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    error_message: Mapped[str | None] = mapped_column(Text)


class TraceabilityTemplateParseResult(Base, TimestampMixin):
    __tablename__ = "traceability_template_parse_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    template_document_id: Mapped[int] = mapped_column(ForeignKey("traceability_template_documents.id"), index=True)
    sheet_name: Mapped[str] = mapped_column(String(255), nullable=False)
    header_start_row: Mapped[int] = mapped_column(Integer, nullable=False)
    header_end_row: Mapped[int] = mapped_column(Integer, nullable=False)
    fixed_columns_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    scenario_groups_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    parsed_rows_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    warnings_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)


class SourceToMartMapping(Base, TimestampMixin):
    __tablename__ = "source_to_mart_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    mart_field_id: Mapped[int] = mapped_column(ForeignKey("mart_fields.id"), index=True)
    mapping_name: Mapped[str | None] = mapped_column(String(255))
    mapping_status: Mapped[str] = mapped_column(String(50), default="draft")
    source_system_summary: Mapped[str | None] = mapped_column(Text)
    source_tables_summary: Mapped[str | None] = mapped_column(Text)
    source_fields_summary: Mapped[str | None] = mapped_column(Text)
    business_rule: Mapped[str | None] = mapped_column(Text)
    filter_condition: Mapped[str | None] = mapped_column(Text)
    join_condition: Mapped[str | None] = mapped_column(Text)
    priority_rule: Mapped[str | None] = mapped_column(Text)
    merge_rule: Mapped[str | None] = mapped_column(Text)
    code_mapping_rule: Mapped[str | None] = mapped_column(Text)
    null_handling_rule: Mapped[str | None] = mapped_column(Text)
    exception_rule: Mapped[str | None] = mapped_column(Text)
    quality_check_rule: Mapped[str | None] = mapped_column(Text)
    open_questions: Mapped[str | None] = mapped_column(Text)
    ai_generated_content: Mapped[str | None] = mapped_column(Text)
    final_content: Mapped[str | None] = mapped_column(Text)
    confidence_level: Mapped[str] = mapped_column(String(50), default="medium")
    created_by: Mapped[str | None] = mapped_column(String(100))
    reviewed_by: Mapped[str | None] = mapped_column(String(100))
    reviewed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    lineage_status: Mapped[str] = mapped_column(String(50), default="not_linked", index=True)
    lineage_last_verified_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    lineage_change_set_id: Mapped[int | None] = mapped_column(ForeignKey("script_change_sets.id"), index=True)


class MartToYbtMapping(Base, TimestampMixin):
    __tablename__ = "mart_to_ybt_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    target_field_id: Mapped[int] = mapped_column(ForeignKey("target_fields.id"), index=True)
    mart_field_id: Mapped[int | None] = mapped_column(ForeignKey("mart_fields.id"))
    mapping_name: Mapped[str | None] = mapped_column(String(255))
    mapping_status: Mapped[str] = mapped_column(String(50), default="draft")
    mart_table_summary: Mapped[str | None] = mapped_column(Text)
    mart_field_summary: Mapped[str | None] = mapped_column(Text)
    business_rule: Mapped[str | None] = mapped_column(Text)
    filter_condition: Mapped[str | None] = mapped_column(Text)
    join_condition: Mapped[str | None] = mapped_column(Text)
    code_mapping_rule: Mapped[str | None] = mapped_column(Text)
    null_handling_rule: Mapped[str | None] = mapped_column(Text)
    reporting_condition: Mapped[str | None] = mapped_column(Text)
    validation_rule: Mapped[str | None] = mapped_column(Text)
    open_questions: Mapped[str | None] = mapped_column(Text)
    ai_generated_content: Mapped[str | None] = mapped_column(Text)
    final_content: Mapped[str | None] = mapped_column(Text)
    confidence_level: Mapped[str] = mapped_column(String(50), default="medium")
    created_by: Mapped[str | None] = mapped_column(String(100))
    reviewed_by: Mapped[str | None] = mapped_column(String(100))
    reviewed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    lineage_status: Mapped[str] = mapped_column(String(50), default="not_linked", index=True)
    lineage_last_verified_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    lineage_change_set_id: Mapped[int | None] = mapped_column(ForeignKey("script_change_sets.id"), index=True)


class MappingEvidenceReference(Base):
    __tablename__ = "mapping_evidence_references"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    mapping_type: Mapped[str] = mapped_column(String(50), nullable=False)
    mapping_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    evidence_type: Mapped[str] = mapped_column(String(100), nullable=False)
    evidence_id: Mapped[int | None] = mapped_column(Integer)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    location_text: Mapped[str | None] = mapped_column(String(255))
    quoted_content: Mapped[str | None] = mapped_column(Text)
    evidence_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @staticmethod
    def supported_types() -> set[str]:
        return {
            "template_parse_result",
            "document_chunk",
            "sql_file",
            "sql_parse_result",
            "natural_language_task",
            "sql_execution_log",
            "db_query_result",
            "datasource",
            "source_field",
            "mart_field",
            "target_field",
            "manual_note",
            "regulatory_knowledge_item",
            "source_recommendation",
            "catalog_column",
            "metadata_sync_task",
            "column_profile",
            "profile_snapshot",
            "script_file",
            "script_file_version",
            "sql_statement",
            "script_dependency",
            "lineage_node",
            "lineage_edge",
            "script_change_set",
            "impact_analysis",
        }


class MappingVersion(Base):
    __tablename__ = "mapping_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    mapping_type: Mapped[str] = mapped_column(String(50), nullable=False)
    mapping_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    change_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str | None] = mapped_column(String(100))


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_type: Mapped[str] = mapped_column(String(100), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    knowledge_type: Mapped[str] = mapped_column(String(50), default="manual_note", index=True)
    knowledge_scope: Mapped[str] = mapped_column(String(50), default="project", index=True)
    institution_name: Mapped[str | None] = mapped_column(String(255), index=True)
    document_status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    confidentiality_level: Mapped[str] = mapped_column(String(50), default="internal")
    file_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    current_version_no: Mapped[int] = mapped_column(Integer, default=1)
    parse_status: Mapped[str] = mapped_column(String(50), default="pending")
    parse_summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    warnings_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(),onupdate=func.now())

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(back_populates="document")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    embedding_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")


class KnowledgeDocumentVersion(Base):
    __tablename__="knowledge_document_versions";__table_args__=(UniqueConstraint("document_id","version_no",name="uq_knowledge_document_version"),)
    id:Mapped[int]=mapped_column(Integer,primary_key=True,index=True);project_id:Mapped[int]=mapped_column(ForeignKey("projects.id"),index=True);document_id:Mapped[int]=mapped_column(ForeignKey("knowledge_documents.id"),index=True);version_no:Mapped[int]=mapped_column(Integer);file_name:Mapped[str]=mapped_column(String(255));storage_path:Mapped[str]=mapped_column(String(500));file_hash:Mapped[str]=mapped_column(String(64),index=True);change_note:Mapped[str|None]=mapped_column(Text);parse_status:Mapped[str]=mapped_column(String(50),default="pending");created_at:Mapped[object]=mapped_column(DateTime(timezone=True),server_default=func.now());created_by:Mapped[str|None]=mapped_column(String(100))

class KnowledgeUnit(Base,TimestampMixin):
    __tablename__="knowledge_units";__table_args__=(Index("ix_knowledge_units_retrieval","project_id","knowledge_scope","institution_name","knowledge_type","target_field_code","scenario_id","enabled"),)
    id:Mapped[int]=mapped_column(Integer,primary_key=True,index=True);project_id:Mapped[int]=mapped_column(ForeignKey("projects.id"),index=True);document_id:Mapped[int]=mapped_column(ForeignKey("knowledge_documents.id"),index=True);document_version_id:Mapped[int]=mapped_column(ForeignKey("knowledge_document_versions.id"),index=True);knowledge_type:Mapped[str]=mapped_column(String(50),index=True);knowledge_scope:Mapped[str]=mapped_column(String(50),index=True);institution_name:Mapped[str|None]=mapped_column(String(255),index=True);unit_type:Mapped[str]=mapped_column(String(50));title:Mapped[str|None]=mapped_column(String(500));content:Mapped[str]=mapped_column(Text);normalized_content:Mapped[str]=mapped_column(Text);source_file_name:Mapped[str]=mapped_column(String(255));source_sheet_name:Mapped[str|None]=mapped_column(String(255));source_page_no:Mapped[int|None]=mapped_column(Integer);source_heading:Mapped[str|None]=mapped_column(String(500));source_cell_range:Mapped[str|None]=mapped_column(String(100));target_table_code:Mapped[str|None]=mapped_column(String(100));target_field_code:Mapped[str|None]=mapped_column(String(100),index=True);target_field_name:Mapped[str|None]=mapped_column(String(255));scenario_id:Mapped[int|None]=mapped_column(ForeignKey("product_scenarios.id"),index=True);business_system_id:Mapped[int|None]=mapped_column(ForeignKey("business_systems.id"));source_table_name:Mapped[str|None]=mapped_column(String(255));source_field_name:Mapped[str|None]=mapped_column(String(255));mart_table_name:Mapped[str|None]=mapped_column(String(255));mart_field_name:Mapped[str|None]=mapped_column(String(255));tags_json:Mapped[list]=mapped_column(MutableList.as_mutable(JSON),default=list);metadata_json:Mapped[dict]=mapped_column(MutableDict.as_mutable(JSON),default=dict);confidentiality_level:Mapped[str]=mapped_column(String(50),default="internal");enabled:Mapped[bool]=mapped_column(Boolean,default=True,index=True);content_hash:Mapped[str]=mapped_column(String(64),index=True)

class KnowledgeKeywordIndex(Base):
    __tablename__="knowledge_keyword_indexes";__table_args__=(UniqueConstraint("knowledge_unit_id","token",name="uq_knowledge_keyword_unit_token"),Index("ix_knowledge_keyword_project_token","project_id","token"))
    id:Mapped[int]=mapped_column(Integer,primary_key=True);project_id:Mapped[int]=mapped_column(ForeignKey("projects.id"),index=True);knowledge_unit_id:Mapped[int]=mapped_column(ForeignKey("knowledge_units.id"),index=True);token:Mapped[str]=mapped_column(String(255),index=True);weight:Mapped[float]=mapped_column(Float,default=1.0);created_at:Mapped[object]=mapped_column(DateTime(timezone=True),server_default=func.now())

class KnowledgeEntityLink(Base):
    __tablename__="knowledge_entity_links";id:Mapped[int]=mapped_column(Integer,primary_key=True);project_id:Mapped[int]=mapped_column(ForeignKey("projects.id"),index=True);knowledge_unit_id:Mapped[int]=mapped_column(ForeignKey("knowledge_units.id"),index=True);entity_type:Mapped[str]=mapped_column(String(50),index=True);entity_id:Mapped[int|None]=mapped_column(Integer);entity_code:Mapped[str|None]=mapped_column(String(255));entity_name:Mapped[str|None]=mapped_column(String(255));relation_type:Mapped[str]=mapped_column(String(50));confidence:Mapped[float]=mapped_column(Float,default=1.0);created_at:Mapped[object]=mapped_column(DateTime(timezone=True),server_default=func.now())

class KnowledgeIngestionTask(Base):
    __tablename__="knowledge_ingestion_tasks";id:Mapped[int]=mapped_column(Integer,primary_key=True);project_id:Mapped[int]=mapped_column(ForeignKey("projects.id"),index=True);document_id:Mapped[int]=mapped_column(ForeignKey("knowledge_documents.id"),index=True);document_version_id:Mapped[int]=mapped_column(ForeignKey("knowledge_document_versions.id"));status:Mapped[str]=mapped_column(String(50),index=True);parser_name:Mapped[str]=mapped_column(String(100));started_at:Mapped[object|None]=mapped_column(DateTime(timezone=True));finished_at:Mapped[object|None]=mapped_column(DateTime(timezone=True));unit_count:Mapped[int]=mapped_column(Integer,default=0);indexed_count:Mapped[int]=mapped_column(Integer,default=0);failed_count:Mapped[int]=mapped_column(Integer,default=0);warnings_json:Mapped[list]=mapped_column(MutableList.as_mutable(JSON),default=list);error_message:Mapped[str|None]=mapped_column(Text);created_at:Mapped[object]=mapped_column(DateTime(timezone=True),server_default=func.now());created_by:Mapped[str|None]=mapped_column(String(100))

class EmbeddingRecord(Base,TimestampMixin):
    __tablename__="embedding_records";__table_args__=(UniqueConstraint("knowledge_unit_id","embedding_provider","embedding_model",name="uq_embedding_unit_provider_model"),);id:Mapped[int]=mapped_column(Integer,primary_key=True);project_id:Mapped[int]=mapped_column(ForeignKey("projects.id"),index=True);knowledge_unit_id:Mapped[int]=mapped_column(ForeignKey("knowledge_units.id"),index=True);embedding_provider:Mapped[str]=mapped_column(String(50));embedding_model:Mapped[str]=mapped_column(String(255));vector_store_provider:Mapped[str]=mapped_column(String(50));vector_record_id:Mapped[str]=mapped_column(String(255));embedding_dimension:Mapped[int]=mapped_column(Integer);content_hash:Mapped[str]=mapped_column(String(64));status:Mapped[str]=mapped_column(String(50))

class RetrievalLog(Base):
    __tablename__="retrieval_logs";id:Mapped[int]=mapped_column(Integer,primary_key=True);project_id:Mapped[int]=mapped_column(ForeignKey("projects.id"),index=True);query_text:Mapped[str]=mapped_column(Text);query_type:Mapped[str]=mapped_column(String(50));target_field_id:Mapped[int|None]=mapped_column(ForeignKey("target_fields.id"));scenario_id:Mapped[int|None]=mapped_column(ForeignKey("product_scenarios.id"));filters_json:Mapped[dict]=mapped_column(MutableDict.as_mutable(JSON),default=dict);retrieval_strategy:Mapped[str]=mapped_column(String(50));keyword_result_count:Mapped[int]=mapped_column(Integer,default=0);vector_result_count:Mapped[int]=mapped_column(Integer,default=0);final_result_count:Mapped[int]=mapped_column(Integer,default=0);result_ids_json:Mapped[list]=mapped_column(MutableList.as_mutable(JSON),default=list);latency_ms:Mapped[int]=mapped_column(Integer,default=0);created_at:Mapped[object]=mapped_column(DateTime(timezone=True),server_default=func.now());created_by:Mapped[str|None]=mapped_column(String(100))

class ModelProfile(Base,TimestampMixin):
    __tablename__="model_profiles";id:Mapped[int]=mapped_column(Integer,primary_key=True);profile_name:Mapped[str]=mapped_column(String(255),unique=True);provider_type:Mapped[str]=mapped_column(String(50));base_url:Mapped[str|None]=mapped_column(String(500));model_name:Mapped[str|None]=mapped_column(String(255));embedding_model_name:Mapped[str|None]=mapped_column(String(255));enabled:Mapped[bool]=mapped_column(Boolean,default=True);local_only:Mapped[bool]=mapped_column(Boolean,default=False);supports_structured_output:Mapped[bool]=mapped_column(Boolean,default=True);max_context_tokens:Mapped[int]=mapped_column(Integer,default=8192);temperature:Mapped[float]=mapped_column(Float,default=.2);config_json:Mapped[dict]=mapped_column(MutableDict.as_mutable(JSON),default=dict)

class PromptTemplateVersion(Base):
    __tablename__="prompt_template_versions";__table_args__=(UniqueConstraint("prompt_key","version_no",name="uq_prompt_key_version"),);id:Mapped[int]=mapped_column(Integer,primary_key=True);prompt_key:Mapped[str]=mapped_column(String(100),index=True);version_no:Mapped[int]=mapped_column(Integer);system_prompt:Mapped[str]=mapped_column(Text);user_prompt_template:Mapped[str]=mapped_column(Text);output_schema_json:Mapped[dict]=mapped_column(MutableDict.as_mutable(JSON),default=dict);enabled:Mapped[bool]=mapped_column(Boolean,default=True);change_note:Mapped[str|None]=mapped_column(Text);created_at:Mapped[object]=mapped_column(DateTime(timezone=True),server_default=func.now());created_by:Mapped[str|None]=mapped_column(String(100))

class RagEvaluationCase(Base,TimestampMixin):
    __tablename__="rag_evaluation_cases";id:Mapped[int]=mapped_column(Integer,primary_key=True);project_id:Mapped[int]=mapped_column(ForeignKey("projects.id"),index=True);case_name:Mapped[str]=mapped_column(String(255));case_type:Mapped[str]=mapped_column(String(50));query_text:Mapped[str]=mapped_column(Text);target_field_id:Mapped[int|None]=mapped_column(ForeignKey("target_fields.id"));scenario_id:Mapped[int|None]=mapped_column(ForeignKey("product_scenarios.id"));expected_knowledge_unit_ids_json:Mapped[list]=mapped_column(MutableList.as_mutable(JSON),default=list);expected_source_system:Mapped[str|None]=mapped_column(String(255));expected_table_name:Mapped[str|None]=mapped_column(String(255));expected_field_name:Mapped[str|None]=mapped_column(String(255));expected_answer_keywords_json:Mapped[list]=mapped_column(MutableList.as_mutable(JSON),default=list);enabled:Mapped[bool]=mapped_column(Boolean,default=True)

class RagEvaluationRun(Base):
    __tablename__="rag_evaluation_runs";id:Mapped[int]=mapped_column(Integer,primary_key=True);project_id:Mapped[int]=mapped_column(ForeignKey("projects.id"),index=True);run_name:Mapped[str]=mapped_column(String(255));model_profile_id:Mapped[int|None]=mapped_column(ForeignKey("model_profiles.id"));retrieval_config_json:Mapped[dict]=mapped_column(MutableDict.as_mutable(JSON),default=dict);status:Mapped[str]=mapped_column(String(50));started_at:Mapped[object|None]=mapped_column(DateTime(timezone=True));finished_at:Mapped[object|None]=mapped_column(DateTime(timezone=True));summary_metrics_json:Mapped[dict]=mapped_column(MutableDict.as_mutable(JSON),default=dict);created_at:Mapped[object]=mapped_column(DateTime(timezone=True),server_default=func.now());created_by:Mapped[str|None]=mapped_column(String(100))

class RagEvaluationResult(Base):
    __tablename__="rag_evaluation_results";id:Mapped[int]=mapped_column(Integer,primary_key=True);evaluation_run_id:Mapped[int]=mapped_column(ForeignKey("rag_evaluation_runs.id"),index=True);evaluation_case_id:Mapped[int]=mapped_column(ForeignKey("rag_evaluation_cases.id"),index=True);retrieved_unit_ids_json:Mapped[list]=mapped_column(MutableList.as_mutable(JSON),default=list);generated_answer:Mapped[str|None]=mapped_column(Text);citations_json:Mapped[list]=mapped_column(MutableList.as_mutable(JSON),default=list);recall_at_k:Mapped[float]=mapped_column(Float,default=0);reciprocal_rank:Mapped[float]=mapped_column(Float,default=0);source_hit:Mapped[bool]=mapped_column(Boolean,default=False);citation_coverage:Mapped[float]=mapped_column(Float,default=0);groundedness_score:Mapped[float]=mapped_column(Float,default=0);keyword_coverage:Mapped[float]=mapped_column(Float,default=0);latency_ms:Mapped[int]=mapped_column(Integer,default=0);error_message:Mapped[str|None]=mapped_column(Text);created_at:Mapped[object]=mapped_column(DateTime(timezone=True),server_default=func.now())

class AIUserFeedback(Base):
    __tablename__="ai_user_feedback";id:Mapped[int]=mapped_column(Integer,primary_key=True);project_id:Mapped[int]=mapped_column(ForeignKey("projects.id"),index=True);feedback_type:Mapped[str]=mapped_column(String(50));target_type:Mapped[str]=mapped_column(String(50));target_id:Mapped[int]=mapped_column(Integer);rating:Mapped[str]=mapped_column(String(50));correct_source_system:Mapped[str|None]=mapped_column(String(255));correct_table_name:Mapped[str|None]=mapped_column(String(255));correct_field_name:Mapped[str|None]=mapped_column(String(255));comment:Mapped[str|None]=mapped_column(Text);created_at:Mapped[object]=mapped_column(DateTime(timezone=True),server_default=func.now());created_by:Mapped[str|None]=mapped_column(String(100))

class ModelCallLog(Base):
    __tablename__="model_call_logs";id:Mapped[int]=mapped_column(Integer,primary_key=True);project_id:Mapped[int]=mapped_column(ForeignKey("projects.id"),index=True);model_profile_id:Mapped[int|None]=mapped_column(ForeignKey("model_profiles.id"));retrieval_log_id:Mapped[int|None]=mapped_column(ForeignKey("retrieval_logs.id"),index=True);prompt_key:Mapped[str]=mapped_column(String(100));prompt_version:Mapped[int]=mapped_column(Integer);request_hash:Mapped[str]=mapped_column(String(64));input_summary:Mapped[str|None]=mapped_column(Text);output_summary:Mapped[str|None]=mapped_column(Text);status:Mapped[str]=mapped_column(String(50));latency_ms:Mapped[int]=mapped_column(Integer);token_usage_json:Mapped[dict]=mapped_column(MutableDict.as_mutable(JSON),default=dict);confidentiality_level:Mapped[str]=mapped_column(String(50));created_at:Mapped[object]=mapped_column(DateTime(timezone=True),server_default=func.now());created_by:Mapped[str|None]=mapped_column(String(100))


class SqlFile(Base):
    __tablename__ = "sql_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    raw_sql: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())

    parse_result: Mapped["SqlParseResult"] = relationship(back_populates="sql_file")


class SqlParseResult(Base):
    __tablename__ = "sql_parse_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    sql_file_id: Mapped[int] = mapped_column(ForeignKey("sql_files.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    parsed_success: Mapped[bool] = mapped_column(Boolean, default=False)
    source_tables_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    selected_fields_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    joins_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    where_conditions_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sql_file: Mapped[SqlFile] = relationship(back_populates="parse_result")


class FieldAnalysisTask(Base, TimestampMixin):
    __tablename__ = "field_analysis_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    target_field_id: Mapped[int] = mapped_column(ForeignKey("target_fields.id"), index=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    task_type: Mapped[str] = mapped_column(String(100), default="mapping_generation")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    error_message: Mapped[str | None] = mapped_column(Text)


class FieldMappingDraft(Base, TimestampMixin):
    __tablename__ = "field_mapping_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("field_analysis_tasks.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    target_field_id: Mapped[int] = mapped_column(ForeignKey("target_fields.id"), index=True)
    business_to_mart_rule: Mapped[str | None] = mapped_column(Text)
    mart_to_ybt_rule: Mapped[str | None] = mapped_column(Text)
    source_system_candidates_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    source_table_candidates_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    source_field_candidates_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    east_reference_summary: Mapped[str | None] = mapped_column(Text)
    sql_reference_summary: Mapped[str | None] = mapped_column(Text)
    validation_notes: Mapped[str | None] = mapped_column(Text)
    confidence_level: Mapped[str] = mapped_column(String(50), default="medium")
    review_status: Mapped[str] = mapped_column(String(50), default="pending")
    final_content: Mapped[str | None] = mapped_column(Text)
    risk_points_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    questions_for_human_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    template_reference_summary: Mapped[str | None] = mapped_column(Text)
    db_query_summary: Mapped[str | None] = mapped_column(Text)
    data_quality_notes: Mapped[str | None] = mapped_column(Text)
    evidence_completeness: Mapped[str] = mapped_column(String(50), default="medium")

    evidences: Mapped[list["EvidenceReference"]] = relationship(back_populates="draft")


class EvidenceReference(Base):
    __tablename__ = "evidence_references"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("field_mapping_drafts.id"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    location_text: Mapped[str] = mapped_column(String(255), nullable=False)
    quoted_content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())

    draft: Mapped[FieldMappingDraft] = relationship(back_populates="evidences")

    @staticmethod
    def supported_types() -> set[str]:
        return {
            "document_chunk",
            "sql_file",
            "sql_parse_result",
            "db_profile",
            "template_document",
            "template_parse_result",
            "natural_language_task",
            "sql_execution_log",
            "db_query_result",
            "datasource",
        }


class TemplateDocument(Base, TimestampMixin):
    __tablename__ = "template_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    sheet_names_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    parse_status: Mapped[str] = mapped_column(String(50), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text)

    parse_results: Mapped[list["TemplateParseResult"]] = relationship(back_populates="template_document")


class TemplateParseResult(Base, TimestampMixin):
    __tablename__ = "template_parse_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    template_document_id: Mapped[int] = mapped_column(ForeignKey("template_documents.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    sheet_name: Mapped[str] = mapped_column(String(255), nullable=False)
    table_code: Mapped[str | None] = mapped_column(String(100))
    table_name: Mapped[str | None] = mapped_column(String(200))
    field_count: Mapped[int] = mapped_column(Integer, default=0)
    raw_header_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    parsed_rows_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    warnings_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)

    template_document: Mapped[TemplateDocument] = relationship(back_populates="parse_results")


class DataSource(Base, TimestampMixin):
    __tablename__ = "data_sources"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_data_sources_project_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    db_type: Mapped[str] = mapped_column(String(50), nullable=False)
    host: Mapped[str | None] = mapped_column(String(255))
    port: Mapped[int | None] = mapped_column(Integer)
    database_name: Mapped[str | None] = mapped_column(String(255))
    service_name: Mapped[str | None] = mapped_column(String(255))
    schema_name: Mapped[str | None] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(255))
    encrypted_password: Mapped[str | None] = mapped_column(Text)
    connection_params_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    readonly_flag: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_test_status: Mapped[str | None] = mapped_column(String(50))
    last_test_message: Mapped[str | None] = mapped_column(Text)
    last_test_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))

    @property
    def password_configured(self) -> bool:
        return bool(self.encrypted_password)


class SqlExecutionLog(Base):
    __tablename__ = "sql_execution_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    datasource_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("natural_language_tasks.id"))
    profile_task_id: Mapped[int | None] = mapped_column(ForeignKey("column_profile_tasks.id"), index=True)
    sql_text: Mapped[str] = mapped_column(Text, nullable=False)
    sanitized_sql_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    execution_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class NaturalLanguageTask(Base, TimestampMixin):
    __tablename__ = "natural_language_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    datasource_id: Mapped[int | None] = mapped_column(ForeignKey("data_sources.id"))
    datasource_name: Mapped[str | None] = mapped_column(String(64))
    intent: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    extracted_table_name: Mapped[str | None] = mapped_column(String(255))
    extracted_field_name: Mapped[str | None] = mapped_column(String(255))
    generated_sql_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    result_summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class DbProfileTask(Base, TimestampMixin):
    __tablename__ = "db_profile_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    target_field_id: Mapped[int | None] = mapped_column(ForeignKey("target_fields.id"))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    connection_name: Mapped[str | None] = mapped_column(String(100))
    table_name: Mapped[str | None] = mapped_column(String(200))
    field_name: Mapped[str | None] = mapped_column(String(200))
    profile_result_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)


class MetadataSyncTask(Base, TimestampMixin):
    __tablename__ = "metadata_sync_tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    datasource_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    sync_mode: Mapped[str] = mapped_column(String(50), default="full")
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    started_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    schema_count: Mapped[int] = mapped_column(Integer, default=0)
    table_count: Mapped[int] = mapped_column(Integer, default=0)
    column_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    warnings_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    created_by: Mapped[str | None] = mapped_column(String(100))


class CatalogSchema(Base, TimestampMixin):
    __tablename__ = "catalog_schemas"
    __table_args__ = (UniqueConstraint("datasource_id", "schema_name", name="uq_catalog_schema_datasource_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    datasource_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    schema_name: Mapped[str] = mapped_column(String(255), index=True)
    schema_comment: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))


class CatalogTable(Base, TimestampMixin):
    __tablename__ = "catalog_tables"
    __table_args__ = (UniqueConstraint("datasource_id", "schema_name", "table_name", name="uq_catalog_table_datasource_schema_name"), Index("ix_catalog_tables_project_schema_table", "project_id", "schema_name", "table_name"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    datasource_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    catalog_schema_id: Mapped[int] = mapped_column(ForeignKey("catalog_schemas.id"), index=True)
    database_name: Mapped[str | None] = mapped_column(String(255), index=True)
    schema_name: Mapped[str] = mapped_column(String(255), index=True)
    table_name: Mapped[str] = mapped_column(String(255), index=True)
    table_comment: Mapped[str | None] = mapped_column(Text)
    table_type: Mapped[str] = mapped_column(String(50), default="unknown")
    estimated_row_count: Mapped[int | None] = mapped_column(Integer)
    primary_key_columns_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    metadata_hash: Mapped[str | None] = mapped_column(String(64), index=True)


class CatalogColumn(Base, TimestampMixin):
    __tablename__ = "catalog_columns"
    __table_args__ = (UniqueConstraint("catalog_table_id", "column_name", name="uq_catalog_column_table_name"), Index("ix_catalog_columns_project_lookup", "project_id", "schema_name", "table_name", "column_name"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    datasource_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    catalog_table_id: Mapped[int] = mapped_column(ForeignKey("catalog_tables.id"), index=True)
    database_name: Mapped[str | None] = mapped_column(String(255), index=True)
    schema_name: Mapped[str] = mapped_column(String(255), index=True)
    table_name: Mapped[str] = mapped_column(String(255), index=True)
    column_name: Mapped[str] = mapped_column(String(255), index=True)
    column_comment: Mapped[str | None] = mapped_column(Text)
    data_type: Mapped[str | None] = mapped_column(String(255))
    database_native_type: Mapped[str | None] = mapped_column(String(255))
    nullable: Mapped[bool] = mapped_column(Boolean, default=True)
    ordinal_position: Mapped[int] = mapped_column(Integer, default=0)
    is_primary_key: Mapped[bool] = mapped_column(Boolean, default=False)
    default_value: Mapped[str | None] = mapped_column(Text)
    character_max_length: Mapped[int | None] = mapped_column(Integer)
    numeric_precision: Mapped[int | None] = mapped_column(Integer)
    numeric_scale: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    metadata_hash: Mapped[str | None] = mapped_column(String(64), index=True)


class MetadataImportDocument(Base, TimestampMixin):
    __tablename__ = "metadata_import_documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    datasource_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(500))
    parse_status: Mapped[str] = mapped_column(String(50), default="pending")
    parse_summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    parsed_rows_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    warnings_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    error_message: Mapped[str | None] = mapped_column(Text)


class ColumnProfileTask(Base, TimestampMixin):
    __tablename__ = "column_profile_tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    datasource_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    catalog_column_id: Mapped[int] = mapped_column(ForeignKey("catalog_columns.id"), index=True)
    target_field_id: Mapped[int | None] = mapped_column(ForeignKey("target_fields.id"), index=True)
    scenario_id: Mapped[int | None] = mapped_column(ForeignKey("product_scenarios.id"), index=True)
    source_recommendation_id: Mapped[int | None] = mapped_column(ForeignKey("candidate_source_recommendations.id"), index=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    requested_metrics_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    generated_sql_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    profile_result_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(100))


class ColumnProfileSnapshot(Base):
    __tablename__ = "column_profile_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    profile_task_id: Mapped[int] = mapped_column(ForeignKey("column_profile_tasks.id"), index=True)
    datasource_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    catalog_column_id: Mapped[int] = mapped_column(ForeignKey("catalog_columns.id"), index=True)
    profile_date: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    total_count: Mapped[int | None] = mapped_column(Integer)
    null_count: Mapped[int | None] = mapped_column(Integer)
    null_rate: Mapped[float | None] = mapped_column(Float)
    distinct_count: Mapped[int | None] = mapped_column(Integer)
    min_value_text: Mapped[str | None] = mapped_column(Text)
    max_value_text: Mapped[str | None] = mapped_column(Text)
    min_length: Mapped[int | None] = mapped_column(Integer)
    max_length: Mapped[int | None] = mapped_column(Integer)
    average_length: Mapped[float | None] = mapped_column(Float)
    top_values_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    warnings_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalogImportBinding(Base):
    __tablename__ = "catalog_import_bindings"
    __table_args__ = (UniqueConstraint("catalog_column_id", "binding_type", name="uq_catalog_binding_column_type"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    catalog_table_id: Mapped[int] = mapped_column(ForeignKey("catalog_tables.id"), index=True)
    catalog_column_id: Mapped[int | None] = mapped_column(ForeignKey("catalog_columns.id"), index=True)
    binding_type: Mapped[str] = mapped_column(String(50), index=True)
    business_system_id: Mapped[int | None] = mapped_column(ForeignKey("business_systems.id"))
    source_table_id: Mapped[int | None] = mapped_column(ForeignKey("source_tables.id"))
    source_field_id: Mapped[int | None] = mapped_column(ForeignKey("source_fields.id"))
    mart_table_id: Mapped[int | None] = mapped_column(ForeignKey("mart_tables.id"))
    mart_field_id: Mapped[int | None] = mapped_column(ForeignKey("mart_fields.id"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str | None] = mapped_column(String(100))
