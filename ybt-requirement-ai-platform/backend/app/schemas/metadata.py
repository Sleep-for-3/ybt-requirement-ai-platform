from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class OrmMetadataModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

class MetadataSyncRequest(BaseModel):
    sync_mode: str = "full"
    schema_names: list[str] = Field(default_factory=list)
    include_views: bool = True

class MetadataSyncTaskRead(OrmMetadataModel):
    id: int; project_id: int; datasource_id: int; sync_mode: str; status: str
    started_at: datetime | None; finished_at: datetime | None; schema_count: int; table_count: int; column_count: int
    error_message: str | None; warnings_json: list[Any]; created_at: datetime; updated_at: datetime; created_by: str | None

class CatalogSchemaRead(OrmMetadataModel):
    id: int; project_id: int; datasource_id: int; schema_name: str; schema_comment: str | None; enabled: bool; last_synced_at: datetime | None

class CatalogTableRead(OrmMetadataModel):
    id: int; project_id: int; datasource_id: int; catalog_schema_id: int; database_name: str | None; schema_name: str; table_name: str
    table_comment: str | None; table_type: str; estimated_row_count: int | None; primary_key_columns_json: list[Any]
    enabled: bool; last_synced_at: datetime | None; metadata_hash: str | None

class CatalogColumnRead(OrmMetadataModel):
    id: int; project_id: int; datasource_id: int; catalog_table_id: int; database_name: str | None; schema_name: str; table_name: str
    column_name: str; column_comment: str | None; data_type: str | None; database_native_type: str | None
    nullable: bool; ordinal_position: int; is_primary_key: bool; default_value: str | None
    character_max_length: int | None; numeric_precision: int | None; numeric_scale: int | None
    enabled: bool; last_synced_at: datetime | None; metadata_hash: str | None

class CatalogSearchRequest(BaseModel):
    datasource_ids: list[int] = Field(default_factory=list); schema_names: list[str] = Field(default_factory=list)
    query: str = ""; target_field_id: int | None = None; scenario_id: int | None = None
    top_k: int = Field(default=50, ge=1, le=100)

class CatalogSearchItem(BaseModel):
    catalog_column_id: int; datasource_id: int; datasource_name: str; database_name: str | None; schema_name: str; table_name: str
    table_comment: str | None; column_name: str; column_comment: str | None; data_type: str | None
    nullable: bool; is_primary_key: bool; score: float; match_reasons: list[str]
    imported_source_field_id: int | None = None; imported_mart_field_id: int | None = None

class CatalogSearchResponse(BaseModel):
    items: list[CatalogSearchItem]

class PaginatedCatalogTables(BaseModel):
    items: list[CatalogTableRead]; total: int; page: int; page_size: int

class PaginatedCatalogColumns(BaseModel):
    items: list[CatalogColumnRead]; total: int; page: int; page_size: int

class CatalogImportRequest(BaseModel):
    business_system_id: int | None = None; system_code: str | None = None; system_name: str | None = None

class CatalogImportResult(BaseModel):
    binding_id: int; binding_type: str; source_table_id: int | None = None; source_field_id: int | None = None
    mart_table_id: int | None = None; mart_field_id: int | None = None

class MetadataImportRead(OrmMetadataModel):
    id: int; project_id: int; datasource_id: int; file_name: str; parse_status: str
    parse_summary_json: dict[str, Any]; parsed_rows_json: list[Any]; warnings_json: list[Any]
    error_message: str | None; created_at: datetime; updated_at: datetime

class MetadataImportApplyResponse(BaseModel):
    document_id: int; schemas: int; tables: int; columns: int; warnings: list[str]

class ColumnProfileRequest(BaseModel):
    target_field_id: int; scenario_id: int; source_recommendation_id: int
    metrics: list[str] = Field(default_factory=lambda: ["null_rate", "distinct_count"])

class ColumnProfileTaskRead(OrmMetadataModel):
    id: int; project_id: int; datasource_id: int; catalog_column_id: int; target_field_id: int | None
    scenario_id: int | None; source_recommendation_id: int | None; status: str; requested_metrics_json: list[Any]
    generated_sql_json: list[Any]; profile_result_json: dict[str, Any]; error_message: str | None
    started_at: datetime | None; finished_at: datetime | None

class ColumnProfileSnapshotRead(OrmMetadataModel):
    id: int; project_id: int; profile_task_id: int; datasource_id: int; catalog_column_id: int; profile_date: datetime
    total_count: int | None; null_count: int | None; null_rate: float | None; distinct_count: int | None
    min_value_text: str | None; max_value_text: str | None; min_length: int | None; max_length: int | None
    average_length: float | None; top_values_json: list[Any]; warnings_json: list[Any]

class ProfileEvidenceBindRequest(BaseModel):
    mapping_type: str; mapping_id: int
