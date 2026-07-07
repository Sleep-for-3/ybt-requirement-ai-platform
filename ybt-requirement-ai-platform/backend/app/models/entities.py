from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, func
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
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
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
    source_tables_json: Mapped[list] = mapped_column(JSON, default=list)
    selected_fields_json: Mapped[list] = mapped_column(JSON, default=list)
    joins_json: Mapped[list] = mapped_column(JSON, default=list)
    where_conditions_json: Mapped[list] = mapped_column(JSON, default=list)
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
    source_system_candidates_json: Mapped[list] = mapped_column(JSON, default=list)
    source_table_candidates_json: Mapped[list] = mapped_column(JSON, default=list)
    source_field_candidates_json: Mapped[list] = mapped_column(JSON, default=list)
    east_reference_summary: Mapped[str | None] = mapped_column(Text)
    sql_reference_summary: Mapped[str | None] = mapped_column(Text)
    validation_notes: Mapped[str | None] = mapped_column(Text)
    confidence_level: Mapped[str] = mapped_column(String(50), default="medium")
    review_status: Mapped[str] = mapped_column(String(50), default="pending")
    final_content: Mapped[str | None] = mapped_column(Text)
    risk_points_json: Mapped[list] = mapped_column(JSON, default=list)
    questions_for_human_json: Mapped[list] = mapped_column(JSON, default=list)

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


class DbProfileTask(Base, TimestampMixin):
    __tablename__ = "db_profile_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    target_field_id: Mapped[int | None] = mapped_column(ForeignKey("target_fields.id"))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    connection_name: Mapped[str | None] = mapped_column(String(100))
    table_name: Mapped[str | None] = mapped_column(String(200))
    field_name: Mapped[str | None] = mapped_column(String(200))
    profile_result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
