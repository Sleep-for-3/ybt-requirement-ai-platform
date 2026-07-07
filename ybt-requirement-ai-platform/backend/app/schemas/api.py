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
    created_at: datetime
    updated_at: datetime
    evidences: list[EvidenceReferenceRead] = Field(default_factory=list)


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
