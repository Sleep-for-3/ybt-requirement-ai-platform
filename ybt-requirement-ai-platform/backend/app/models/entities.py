from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
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


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    bank_name: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)

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
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())

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
