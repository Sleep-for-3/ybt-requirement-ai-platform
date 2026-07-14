from sqlalchemy import create_engine, inspect, text
from app.models import DataSource
from app.services.datasource_service import build_database_url
from app.services.metadata.base import ColumnMetadata, ConnectionTestResult, SchemaMetadata, TableMetadata

class SqlAlchemyMetadataAdapter:
    system_schemas: set[str] = set()

    def __init__(self, datasource: DataSource):
        self.datasource = datasource
        params = datasource.connection_params_json or {}
        self.whitelist = set(params.get("schema_whitelist") or [])
        self.blacklist = set(params.get("schema_blacklist") or []) | self.system_schemas

    def _engine(self):
        try: return create_engine(build_database_url(self.datasource), pool_pre_ping=True)
        except (ImportError, ModuleNotFoundError) as exc: raise RuntimeError(f"{self.datasource.db_type} 可选驱动未安装：{exc}") from exc

    def test_connection(self) -> ConnectionTestResult:
        try:
            with self._engine().connect() as connection: connection.execute(text("select 1"))
            return ConnectionTestResult(True, "连接测试成功")
        except Exception as exc: return ConnectionTestResult(False, str(exc))

    def list_schemas(self) -> list[SchemaMetadata]:
        names = inspect(self._engine()).get_schema_names()
        return [SchemaMetadata(name) for name in names if self._allowed(name)]

    def list_tables(self, schema_names=None, include_views=True) -> list[TableMetadata]:
        inspector = inspect(self._engine()); output = []
        schemas = schema_names or [item.schema_name for item in self.list_schemas()]
        for schema in schemas:
            if not self._allowed(schema): continue
            for name in inspector.get_table_names(schema=schema):
                output.append(self._table(inspector, schema, name, "table"))
            if include_views:
                for name in inspector.get_view_names(schema=schema): output.append(self._table(inspector, schema, name, "view"))
        return output

    def _table(self, inspector, schema, name, table_type):
        comment = None
        try: comment = (inspector.get_table_comment(name, schema=schema) or {}).get("text")
        except NotImplementedError: pass
        return TableMetadata(schema, name, comment, table_type, primary_key_columns=self.get_primary_keys(schema, name))

    def list_columns(self, schema_name, table_name):
        inspector = inspect(self._engine()); primary = set(self.get_primary_keys(schema_name, table_name))
        result = []
        for position, item in enumerate(inspector.get_columns(table_name, schema=schema_name), start=1):
            native = str(item.get("type") or "")
            result.append(ColumnMetadata(schema_name, table_name, item["name"], item.get("comment"), native, native, bool(item.get("nullable", True)), position, item["name"] in primary, None if item.get("default") is None else str(item["default"]), getattr(item.get("type"), "length", None), getattr(item.get("type"), "precision", None), getattr(item.get("type"), "scale", None)))
        return result

    def get_primary_keys(self, schema_name, table_name):
        return list((inspect(self._engine()).get_pk_constraint(table_name, schema=schema_name) or {}).get("constrained_columns") or [])

    def _allowed(self, name):
        return name not in self.blacklist and (not self.whitelist or name in self.whitelist)

class UnsupportedMetadataAdapter:
    def __init__(self, datasource): self.datasource = datasource
    def _error(self): raise RuntimeError(f"{self.datasource.db_type} 元数据适配器尚未启用；请通过连接参数指定未来 SQLAlchemy driver/url")
    def test_connection(self): return ConnectionTestResult(False, f"{self.datasource.db_type} 元数据适配器尚未启用")
    def list_schemas(self): return self._error()
    def list_tables(self, schema_names=None, include_views=True): return self._error()
    def list_columns(self, schema_name, table_name): return self._error()
    def get_primary_keys(self, schema_name, table_name): return self._error()
