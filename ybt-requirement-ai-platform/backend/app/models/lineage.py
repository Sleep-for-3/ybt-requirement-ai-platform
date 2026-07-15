from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class CodeRepository(Base, TimestampMixin):
    __tablename__ = "code_repositories"
    __table_args__ = (UniqueConstraint("project_id", "repository_name", name="uq_code_repository_project_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    repository_name: Mapped[str] = mapped_column(String(255), nullable=False)
    repository_type: Mapped[str] = mapped_column(String(50), default="git_repository", index=True)
    repository_url: Mapped[str | None] = mapped_column(String(1000))
    default_branch: Mapped[str] = mapped_column(String(255), default="main")
    credential_env_name: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_commit: Mapped[str | None] = mapped_column(String(64))
    last_synced_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)


class ScriptFile(Base, TimestampMixin):
    __tablename__ = "script_files"
    __table_args__ = (
        UniqueConstraint("project_id", "code_repository_id", "relative_path", name="uq_script_file_project_repo_path"),
        Index("ix_script_files_project_type_path", "project_id", "file_type", "relative_path"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    code_repository_id: Mapped[int | None] = mapped_column(ForeignKey("code_repositories.id"), index=True)
    relative_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    logical_target_name: Mapped[str | None] = mapped_column(String(255), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    current_version_no: Mapped[int] = mapped_column(Integer, default=0)


class ScriptFileVersion(Base):
    __tablename__ = "script_file_versions"
    __table_args__ = (
        UniqueConstraint("script_file_id", "version_no", name="uq_script_file_version_no"),
        UniqueConstraint("script_file_id", "file_hash", name="uq_script_file_version_hash"),
        Index("ix_script_versions_project_created", "project_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    script_file_id: Mapped[int] = mapped_column(ForeignKey("script_files.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    git_commit_sha: Mapped[str | None] = mapped_column(String(64), index=True)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    normalized_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    raw_content_storage_file_id: Mapped[int] = mapped_column(ForeignKey("stored_files.id"), index=True)
    parse_status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    dialect: Mapped[str | None] = mapped_column(String(50))
    change_note: Mapped[str | None] = mapped_column(Text)
    warnings_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TemplateVariable(Base, TimestampMixin):
    __tablename__ = "template_variables"
    __table_args__ = (UniqueConstraint("project_id", "variable_name", name="uq_template_variable_project_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    variable_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    variable_type: Mapped[str] = mapped_column(String(50), default="identifier_or_value")
    example_value: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class ScriptDependency(Base):
    __tablename__ = "script_dependencies"
    __table_args__ = (Index("ix_script_dependencies_project_parent", "project_id", "parent_script_file_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    parent_script_file_id: Mapped[int] = mapped_column(ForeignKey("script_files.id"), index=True)
    child_script_file_id: Mapped[int | None] = mapped_column(ForeignKey("script_files.id"), index=True)
    dependency_type: Mapped[str] = mapped_column(String(50), index=True)
    call_expression: Mapped[str] = mapped_column(Text)
    condition_expression: Mapped[str | None] = mapped_column(Text)
    source_line_start: Mapped[int | None] = mapped_column(Integer)
    source_line_end: Mapped[int | None] = mapped_column(Integer)
    confidence_level: Mapped[str] = mapped_column(String(50), default="medium")
    warnings_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SqlStatement(Base):
    __tablename__ = "sql_statements"
    __table_args__ = (UniqueConstraint("script_file_version_id", "statement_index", name="uq_sql_statement_version_index"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    script_file_version_id: Mapped[int] = mapped_column(ForeignKey("script_file_versions.id"), index=True)
    statement_index: Mapped[int] = mapped_column(Integer)
    statement_type: Mapped[str] = mapped_column(String(50), index=True)
    raw_sql_hash: Mapped[str] = mapped_column(String(64), index=True)
    normalized_sql: Mapped[str] = mapped_column(Text)
    dialect: Mapped[str | None] = mapped_column(String(50))
    parse_status: Mapped[str] = mapped_column(String(50), index=True)
    source_line_start: Mapped[int | None] = mapped_column(Integer)
    source_line_end: Mapped[int | None] = mapped_column(Integer)
    warnings_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LineageNode(Base, TimestampMixin):
    __tablename__ = "lineage_nodes"
    __table_args__ = (Index("ix_lineage_nodes_project_lookup", "project_id", "node_type", "schema_name", "table_name", "column_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    node_type: Mapped[str] = mapped_column(String(50), index=True)
    logical_name: Mapped[str] = mapped_column(String(1000), index=True)
    database_name: Mapped[str | None] = mapped_column(String(255), index=True)
    schema_name: Mapped[str | None] = mapped_column(String(255), index=True)
    table_name: Mapped[str | None] = mapped_column(String(255), index=True)
    column_name: Mapped[str | None] = mapped_column(String(255), index=True)
    catalog_table_id: Mapped[int | None] = mapped_column(ForeignKey("catalog_tables.id"), index=True)
    catalog_column_id: Mapped[int | None] = mapped_column(ForeignKey("catalog_columns.id"), index=True)
    source_table_id: Mapped[int | None] = mapped_column(ForeignKey("source_tables.id"), index=True)
    source_field_id: Mapped[int | None] = mapped_column(ForeignKey("source_fields.id"), index=True)
    mart_table_id: Mapped[int | None] = mapped_column(ForeignKey("mart_tables.id"), index=True)
    mart_field_id: Mapped[int | None] = mapped_column(ForeignKey("mart_fields.id"), index=True)
    target_table_id: Mapped[int | None] = mapped_column(ForeignKey("target_tables.id"), index=True)
    target_field_id: Mapped[int | None] = mapped_column(ForeignKey("target_fields.id"), index=True)
    script_file_id: Mapped[int | None] = mapped_column(ForeignKey("script_files.id"), index=True)
    script_file_version_id: Mapped[int | None] = mapped_column(ForeignKey("script_file_versions.id"), index=True)
    temporary_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    unresolved_flag: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    metadata_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)


class LineageEdge(Base, TimestampMixin):
    __tablename__ = "lineage_edges"
    __table_args__ = (
        Index("ix_lineage_edges_project_source", "project_id", "source_node_id", "enabled"),
        Index("ix_lineage_edges_project_target", "project_id", "target_node_id", "enabled"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    script_file_version_id: Mapped[int] = mapped_column(ForeignKey("script_file_versions.id"), index=True)
    statement_id: Mapped[int | None] = mapped_column(ForeignKey("sql_statements.id"), index=True)
    source_node_id: Mapped[int] = mapped_column(ForeignKey("lineage_nodes.id"), index=True)
    target_node_id: Mapped[int] = mapped_column(ForeignKey("lineage_nodes.id"), index=True)
    edge_type: Mapped[str] = mapped_column(String(50), index=True)
    transformation_type: Mapped[str | None] = mapped_column(String(50), index=True)
    transformation_expression: Mapped[str | None] = mapped_column(Text)
    join_condition: Mapped[str | None] = mapped_column(Text)
    filter_condition: Mapped[str | None] = mapped_column(Text)
    aggregation_rule: Mapped[str | None] = mapped_column(Text)
    code_mapping_rule: Mapped[str | None] = mapped_column(Text)
    source_line_start: Mapped[int | None] = mapped_column(Integer)
    source_line_end: Mapped[int | None] = mapped_column(Integer)
    confidence_level: Mapped[str] = mapped_column(String(50), default="medium", index=True)
    evidence_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class LineageResolutionCandidate(Base):
    __tablename__ = "lineage_resolution_candidates"
    __table_args__ = (UniqueConstraint("lineage_node_id", "candidate_type", "candidate_id", name="uq_lineage_resolution_candidate"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    lineage_node_id: Mapped[int] = mapped_column(ForeignKey("lineage_nodes.id"), index=True)
    candidate_type: Mapped[str] = mapped_column(String(50), index=True)
    candidate_id: Mapped[int] = mapped_column(Integer, index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    match_reason: Mapped[str] = mapped_column(Text)
    selected_flag: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScriptChangeSet(Base):
    __tablename__ = "script_change_sets"
    __table_args__ = (UniqueConstraint("script_file_id", "from_version_id", "to_version_id", name="uq_script_change_version_pair"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    script_file_id: Mapped[int] = mapped_column(ForeignKey("script_files.id"), index=True)
    from_version_id: Mapped[int | None] = mapped_column(ForeignKey("script_file_versions.id"), index=True)
    to_version_id: Mapped[int | None] = mapped_column(ForeignKey("script_file_versions.id"), index=True)
    change_type: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(50), default="completed", index=True)
    summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)


class ScriptChangeItem(Base):
    __tablename__ = "script_change_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    change_set_id: Mapped[int] = mapped_column(ForeignKey("script_change_sets.id"), index=True)
    change_category: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(50), index=True)
    old_value_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    new_value_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    severity: Mapped[str] = mapped_column(String(50), index=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ImpactAnalysis(Base):
    __tablename__ = "impact_analyses"
    __table_args__ = (Index("ix_impact_analyses_project_severity", "project_id", "severity", "status"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    change_set_id: Mapped[int] = mapped_column(ForeignKey("script_change_sets.id"), index=True)
    status: Mapped[str] = mapped_column(String(50), default="completed", index=True)
    severity: Mapped[str] = mapped_column(String(50), default="low", index=True)
    affected_target_field_ids_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    affected_mart_field_ids_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    affected_mapping_ids_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    affected_scenario_mapping_ids_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    affected_lineage_edge_ids_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    summary_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    open_questions_json: Mapped[list] = mapped_column(MutableList.as_mutable(JSON), default=list)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
