from dataclasses import dataclass, field
from typing import Protocol

@dataclass
class ConnectionTestResult:
    success: bool
    message: str

@dataclass
class SchemaMetadata:
    schema_name: str
    schema_comment: str | None = None

@dataclass
class TableMetadata:
    schema_name: str
    table_name: str
    table_comment: str | None = None
    table_type: str = "table"
    estimated_row_count: int | None = None
    primary_key_columns: list[str] = field(default_factory=list)

@dataclass
class ColumnMetadata:
    schema_name: str
    table_name: str
    column_name: str
    column_comment: str | None = None
    data_type: str | None = None
    database_native_type: str | None = None
    nullable: bool = True
    ordinal_position: int = 0
    is_primary_key: bool = False
    default_value: str | None = None
    character_max_length: int | None = None
    numeric_precision: int | None = None
    numeric_scale: int | None = None

class MetadataAdapter(Protocol):
    def test_connection(self) -> ConnectionTestResult: ...
    def list_schemas(self) -> list[SchemaMetadata]: ...
    def list_tables(self, schema_names: list[str] | None = None, include_views: bool = True) -> list[TableMetadata]: ...
    def list_columns(self, schema_name: str, table_name: str) -> list[ColumnMetadata]: ...
    def get_primary_keys(self, schema_name: str, table_name: str) -> list[str]: ...
