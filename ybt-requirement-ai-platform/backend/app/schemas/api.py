from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    name: str
    bank_name: str | None = None
    description: str | None = None


class ProjectRead(OrmModel):
    id: int
    name: str
    bank_name: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime


class TargetTableCreate(BaseModel):
    project_id: int
    table_code: str
    table_name: str
    description: str | None = None


class TargetTableRead(OrmModel):
    id: int
    project_id: int
    table_code: str
    table_name: str
    description: str | None


class TargetFieldCreate(BaseModel):
    project_id: int
    target_table_id: int
    field_code: str
    field_name: str
    field_type: str | None = None
    required_flag: bool = False
    field_definition: str | None = None
    regulatory_description: str | None = None


class TargetFieldRead(OrmModel):
    id: int
    project_id: int
    target_table_id: int
    field_code: str
    field_name: str
    field_type: str | None
    required_flag: bool
    field_definition: str | None
    regulatory_description: str | None
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentRead(OrmModel):
    id: int
    project_id: int
    file_name: str
    file_type: str
    source_type: str
    storage_path: str
    created_at: datetime


class KnowledgeChunkRead(OrmModel):
    id: int
    document_id: int
    project_id: int
    chunk_index: int
    content: str
    metadata_json: dict[str, Any]
    embedding_id: str | None
    created_at: datetime


class SqlParseResultRead(OrmModel):
    id: int
    sql_file_id: int
    project_id: int
    parsed_success: bool
    source_tables_json: list[Any]
    selected_fields_json: list[Any]
    joins_json: list[Any]
    where_conditions_json: list[Any]
    error_message: str | None
    created_at: datetime


class SqlFileRead(OrmModel):
    id: int
    project_id: int
    file_name: str
    storage_path: str
    raw_sql: str
    created_at: datetime
    parse_result: SqlParseResultRead | None = None


class RetrievalSearchRequest(BaseModel):
    project_id: int
    query: str
    top_k: int = Field(default=10, ge=1, le=50)
    filters: dict[str, Any] = Field(default_factory=dict)


class RetrievalSource(BaseModel):
    document_id: int
    file_name: str
    source_type: str
    chunk_index: int


class RetrievalResult(BaseModel):
    content: str
    score: float
    source: RetrievalSource


class RetrievalSearchResponse(BaseModel):
    results: list[RetrievalResult]


class FieldAnalysisTaskRead(OrmModel):
    id: int
    project_id: int
    target_field_id: int
    status: str
    task_type: str
    created_by: int | None
    created_at: datetime
    updated_at: datetime
    error_message: str | None


class EvidenceReferenceRead(OrmModel):
    id: int
    draft_id: int
    evidence_type: str
    source_id: int
    source_name: str
    location_text: str
    quoted_content: str
    created_at: datetime


class FieldMappingDraftRead(OrmModel):
    id: int
    task_id: int
    project_id: int
    target_field_id: int
    business_to_mart_rule: str | None
    mart_to_ybt_rule: str | None
    source_system_candidates_json: list[Any]
    source_table_candidates_json: list[Any]
    source_field_candidates_json: list[Any]
    east_reference_summary: str | None
    sql_reference_summary: str | None
    validation_notes: str | None
    confidence_level: str
    review_status: str
    final_content: str | None
    risk_points_json: list[Any]
    questions_for_human_json: list[Any]
    template_reference_summary: str | None = None
    db_query_summary: str | None = None
    data_quality_notes: str | None = None
    evidence_completeness: str = "medium"
    created_at: datetime
    updated_at: datetime
    evidences: list[EvidenceReferenceRead] = Field(default_factory=list)


class GenerateMappingRequest(BaseModel):
    include_template: bool = True
    include_documents: bool = True
    include_sql_parse_results: bool = True
    include_nl_task_results: bool = True


class GenerateMappingResponse(BaseModel):
    task: FieldAnalysisTaskRead
    draft: FieldMappingDraftRead


class ReviewDraftRequest(BaseModel):
    review_status: str
    final_content: str | None = None


class DbProfileTaskCreate(BaseModel):
    project_id: int
    target_field_id: int | None = None
    connection_name: str | None = None
    table_name: str | None = None
    field_name: str | None = None


class DbProfileTaskRead(OrmModel):
    id: int
    project_id: int
    target_field_id: int | None
    status: str
    connection_name: str | None
    table_name: str | None
    field_name: str | None
    profile_result_json: dict[str, Any]
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class TemplatePreviewItem(BaseModel):
    sheet_name: str
    table_code: str | None
    table_name: str | None
    field_count: int


class TemplateUploadResponse(BaseModel):
    template_id: int
    file_name: str
    parse_status: str
    sheet_count: int
    table_count: int
    field_count: int
    warnings: list[str]
    preview: list[TemplatePreviewItem]


class TemplateDocumentRead(OrmModel):
    id: int
    project_id: int
    file_name: str
    file_type: str
    storage_path: str
    sheet_names_json: list[Any]
    parse_status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class TemplateParseResultRead(OrmModel):
    id: int
    template_document_id: int
    project_id: int
    sheet_name: str
    table_code: str | None
    table_name: str | None
    field_count: int
    raw_header_json: list[Any]
    parsed_rows_json: list[Any]
    warnings_json: list[Any]
    created_at: datetime
    updated_at: datetime


class TemplateApplyResponse(BaseModel):
    template_id: int
    created_tables: int
    updated_tables: int
    created_fields: int
    updated_fields: int
    skipped_rows: int
    warnings: list[str]


class DataSourceCreate(BaseModel):
    name: str
    display_name: str | None = None
    description: str | None = None
    db_type: str
    host: str | None = None
    port: int | None = None
    database_name: str | None = None
    service_name: str | None = None
    schema_name: str | None = None
    username: str | None = None
    password: str | None = None
    connection_params_json: dict[str, Any] = Field(default_factory=dict)
    readonly_flag: bool = True
    enabled: bool = True


class DataSourceUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    db_type: str | None = None
    host: str | None = None
    port: int | None = None
    database_name: str | None = None
    service_name: str | None = None
    schema_name: str | None = None
    username: str | None = None
    password: str | None = None
    connection_params_json: dict[str, Any] | None = None
    readonly_flag: bool | None = None
    enabled: bool | None = None


class DataSourceRead(OrmModel):
    id: int
    project_id: int
    name: str
    display_name: str | None
    description: str | None
    db_type: str
    host: str | None
    port: int | None
    database_name: str | None
    service_name: str | None
    schema_name: str | None
    username: str | None
    connection_params_json: dict[str, Any]
    readonly_flag: bool
    enabled: bool
    password_configured: bool
    last_test_status: str | None
    last_test_message: str | None
    last_test_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DataSourceTestResponse(BaseModel):
    status: str
    message: str


class SafeSqlRequest(BaseModel):
    sql: str
    max_rows: int = 100


class SafeSqlResponse(BaseModel):
    status: str
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    execution_time_ms: int = 0
    warnings: list[str] = Field(default_factory=list)
    sanitized_sql: str | None = None
    reject_reason: str | None = None
    error_message: str | None = None


class NaturalLanguageTaskCreate(BaseModel):
    project_id: int
    text: str


class NaturalLanguageTaskCreateResponse(BaseModel):
    task_id: int
    status: str
    datasource_name: str | None = None
    intent: str | None = None
    extracted_table_name: str | None = None
    extracted_field_name: str | None = None
    message: str
    available_datasources: list[str] = Field(default_factory=list)


class NaturalLanguageTaskRead(OrmModel):
    id: int
    project_id: int
    raw_text: str
    datasource_id: int | None
    datasource_name: str | None
    intent: str | None
    status: str
    extracted_table_name: str | None
    extracted_field_name: str | None
    generated_sql_json: list[Any]
    result_summary_json: dict[str, Any]
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    created_by: int | None


class BusinessSystemCreate(BaseModel):
    system_code: str
    system_name: str
    description: str | None = None
    owner_department: str | None = None
    enabled: bool = True


class BusinessSystemUpdate(BaseModel):
    system_code: str | None = None
    system_name: str | None = None
    description: str | None = None
    owner_department: str | None = None
    enabled: bool | None = None


class BusinessSystemRead(OrmModel):
    id: int
    project_id: int
    system_code: str
    system_name: str
    description: str | None
    owner_department: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class SourceTableCreate(BaseModel):
    table_code: str
    table_name: str
    table_comment: str | None = None
    datasource_id: int | None = None
    schema_name: str | None = None
    physical_table_name: str | None = None
    description: str | None = None


class SourceTableUpdate(BaseModel):
    table_code: str | None = None
    table_name: str | None = None
    table_comment: str | None = None
    datasource_id: int | None = None
    schema_name: str | None = None
    physical_table_name: str | None = None
    description: str | None = None


class SourceTableRead(OrmModel):
    id: int
    project_id: int
    business_system_id: int
    table_code: str
    table_name: str
    table_comment: str | None
    datasource_id: int | None
    schema_name: str | None
    physical_table_name: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime


class SourceFieldCreate(BaseModel):
    field_code: str
    field_name: str
    field_type: str | None = None
    field_comment: str | None = None
    physical_column_name: str | None = None
    description: str | None = None


class SourceFieldUpdate(BaseModel):
    field_code: str | None = None
    field_name: str | None = None
    field_type: str | None = None
    field_comment: str | None = None
    physical_column_name: str | None = None
    description: str | None = None


class SourceFieldRead(OrmModel):
    id: int
    project_id: int
    source_table_id: int
    field_code: str
    field_name: str
    field_type: str | None
    field_comment: str | None
    physical_column_name: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime


class MartTableCreate(BaseModel):
    table_code: str
    table_name: str
    subject_area: str | None = None
    table_comment: str | None = None
    datasource_id: int | None = None
    schema_name: str | None = None
    physical_table_name: str | None = None
    is_existing: bool = True
    description: str | None = None


class MartTableUpdate(BaseModel):
    table_code: str | None = None
    table_name: str | None = None
    subject_area: str | None = None
    table_comment: str | None = None
    datasource_id: int | None = None
    schema_name: str | None = None
    physical_table_name: str | None = None
    is_existing: bool | None = None
    description: str | None = None


class MartTableRead(OrmModel):
    id: int
    project_id: int
    table_code: str
    table_name: str
    subject_area: str | None
    table_comment: str | None
    datasource_id: int | None
    schema_name: str | None
    physical_table_name: str | None
    is_existing: bool
    description: str | None
    created_at: datetime
    updated_at: datetime


class MartFieldCreate(BaseModel):
    field_code: str
    field_name: str
    field_type: str | None = None
    field_comment: str | None = None
    physical_column_name: str | None = None
    is_existing: bool = True
    description: str | None = None


class MartFieldUpdate(BaseModel):
    field_code: str | None = None
    field_name: str | None = None
    field_type: str | None = None
    field_comment: str | None = None
    physical_column_name: str | None = None
    is_existing: bool | None = None
    description: str | None = None


class MartFieldRead(OrmModel):
    id: int
    project_id: int
    mart_table_id: int
    field_code: str
    field_name: str
    field_type: str | None
    field_comment: str | None
    physical_column_name: str | None
    is_existing: bool
    description: str | None
    created_at: datetime
    updated_at: datetime


class SourceToMartMappingCreate(BaseModel):
    mapping_name: str | None = None
    source_system_summary: str | None = None
    source_tables_summary: str | None = None
    source_fields_summary: str | None = None
    business_rule: str | None = None
    filter_condition: str | None = None
    join_condition: str | None = None
    priority_rule: str | None = None
    merge_rule: str | None = None
    code_mapping_rule: str | None = None
    null_handling_rule: str | None = None
    exception_rule: str | None = None
    quality_check_rule: str | None = None
    open_questions: str | None = None
    final_content: str | None = None
    confidence_level: str = "medium"
    created_by: str | None = None


class SourceToMartMappingUpdate(BaseModel):
    mapping_name: str | None = None
    mapping_status: str | None = None
    source_system_summary: str | None = None
    source_tables_summary: str | None = None
    source_fields_summary: str | None = None
    business_rule: str | None = None
    filter_condition: str | None = None
    join_condition: str | None = None
    priority_rule: str | None = None
    merge_rule: str | None = None
    code_mapping_rule: str | None = None
    null_handling_rule: str | None = None
    exception_rule: str | None = None
    quality_check_rule: str | None = None
    open_questions: str | None = None
    ai_generated_content: str | None = None
    final_content: str | None = None
    confidence_level: str | None = None


class SourceToMartMappingRead(OrmModel):
    id: int
    project_id: int
    mart_field_id: int
    mapping_name: str | None
    mapping_status: str
    source_system_summary: str | None
    source_tables_summary: str | None
    source_fields_summary: str | None
    business_rule: str | None
    filter_condition: str | None
    join_condition: str | None
    priority_rule: str | None
    merge_rule: str | None
    code_mapping_rule: str | None
    null_handling_rule: str | None
    exception_rule: str | None
    quality_check_rule: str | None
    open_questions: str | None
    ai_generated_content: str | None
    final_content: str | None
    confidence_level: str
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None


class MartToYbtMappingCreate(BaseModel):
    mart_field_id: int | None = None
    mapping_name: str | None = None
    mart_table_summary: str | None = None
    mart_field_summary: str | None = None
    business_rule: str | None = None
    filter_condition: str | None = None
    join_condition: str | None = None
    code_mapping_rule: str | None = None
    null_handling_rule: str | None = None
    reporting_condition: str | None = None
    validation_rule: str | None = None
    open_questions: str | None = None
    final_content: str | None = None
    confidence_level: str = "medium"
    created_by: str | None = None


class MartToYbtMappingUpdate(BaseModel):
    mart_field_id: int | None = None
    mapping_name: str | None = None
    mapping_status: str | None = None
    mart_table_summary: str | None = None
    mart_field_summary: str | None = None
    business_rule: str | None = None
    filter_condition: str | None = None
    join_condition: str | None = None
    code_mapping_rule: str | None = None
    null_handling_rule: str | None = None
    reporting_condition: str | None = None
    validation_rule: str | None = None
    open_questions: str | None = None
    ai_generated_content: str | None = None
    final_content: str | None = None
    confidence_level: str | None = None


class MartToYbtMappingRead(OrmModel):
    id: int
    project_id: int
    target_field_id: int
    mart_field_id: int | None
    mapping_name: str | None
    mapping_status: str
    mart_table_summary: str | None
    mart_field_summary: str | None
    business_rule: str | None
    filter_condition: str | None
    join_condition: str | None
    code_mapping_rule: str | None
    null_handling_rule: str | None
    reporting_condition: str | None
    validation_rule: str | None
    open_questions: str | None
    ai_generated_content: str | None
    final_content: str | None
    confidence_level: str
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None


class MappingEvidenceCreate(BaseModel):
    evidence_type: str
    evidence_id: int | None = None
    source_name: str
    location_text: str | None = None
    quoted_content: str | None = None
    evidence_summary: str | None = None


class MappingEvidenceRead(OrmModel):
    id: int
    project_id: int
    mapping_type: str
    mapping_id: int
    evidence_type: str
    evidence_id: int | None
    source_name: str
    location_text: str | None
    quoted_content: str | None
    evidence_summary: str | None
    created_at: datetime


class MappingReviewRequest(BaseModel):
    reviewed_by: str | None = None
    final_content: str | None = None
    change_note: str | None = None


class MappingVersionCreate(BaseModel):
    content_snapshot: str | None = None
    change_note: str | None = None
    created_by: str | None = None


class MappingVersionRead(OrmModel):
    id: int
    project_id: int
    mapping_type: str
    mapping_id: int
    version_no: int
    content_snapshot: str
    change_note: str | None
    created_at: datetime
    created_by: str | None


class MappingDocumentExportRead(BaseModel):
    format: str
    scope: str
    scope_id: int
    file_name: str
    content: str
