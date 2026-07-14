from sqlalchemy import create_engine, text
from app.models import DataSource
from app.services.datasource_service import build_database_url
from app.services.metadata.base import ColumnMetadata, ConnectionTestResult, SchemaMetadata, TableMetadata

class SQLiteMetadataAdapter:
    def __init__(self, datasource: DataSource):
        self.datasource = datasource
        self._engine_value = None

    def _engine(self):
        if self._engine_value is None:self._engine_value=create_engine(build_database_url(self.datasource), connect_args={"check_same_thread": False})
        return self._engine_value

    def close(self):
        if self._engine_value is not None:self._engine_value.dispose();self._engine_value=None

    def test_connection(self) -> ConnectionTestResult:
        try:
            with self._engine().connect() as connection: connection.execute(text("select 1"))
            return ConnectionTestResult(True, "连接测试成功")
        except Exception as exc: return ConnectionTestResult(False, str(exc))

    def list_schemas(self) -> list[SchemaMetadata]:
        return [SchemaMetadata("main")]

    def list_tables(self, schema_names=None, include_views=True) -> list[TableMetadata]:
        types = "('table','view')" if include_views else "('table')"
        with self._engine().connect() as connection:
            rows = connection.execute(text(f"select name, type from sqlite_master where type in {types} and name not like 'sqlite_%' order by name")).mappings().all()
        return [TableMetadata("main", row["name"], table_type="view" if row["type"] == "view" else "table", primary_key_columns=self.get_primary_keys("main", row["name"])) for row in rows]

    def list_columns(self, schema_name: str, table_name: str) -> list[ColumnMetadata]:
        safe_name = table_name.replace('"', '""')
        with self._engine().connect() as connection:
            rows = connection.execute(text(f'pragma table_info("{safe_name}")')).mappings().all()
        return [ColumnMetadata(schema_name, table_name, row["name"], data_type=row["type"] or None, database_native_type=row["type"] or None, nullable=not bool(row["notnull"]), ordinal_position=int(row["cid"]) + 1, is_primary_key=bool(row["pk"]), default_value=None if row["dflt_value"] is None else str(row["dflt_value"])) for row in rows]

    def get_primary_keys(self, schema_name: str, table_name: str) -> list[str]:
        return [item.column_name for item in self.list_columns(schema_name, table_name) if item.is_primary_key]
