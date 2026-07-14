from sqlalchemy import text
from app.services.metadata.generic_adapter import SqlAlchemyMetadataAdapter

class PostgreSQLMetadataAdapter(SqlAlchemyMetadataAdapter):
    system_schemas = {"pg_catalog", "information_schema", "pg_toast"}

    def _table(self, inspector, schema, name, table_type):
        item = super()._table(inspector, schema, name, table_type)
        try:
            with self._engine().connect() as connection:
                row = connection.execute(text("""
                    select c.reltuples::bigint as estimated_rows, obj_description(c.oid, 'pg_class') as table_comment
                    from pg_catalog.pg_class c join pg_catalog.pg_namespace n on n.oid=c.relnamespace
                    where n.nspname=:schema and c.relname=:table
                """), {"schema": schema, "table": name}).mappings().first()
            if row:
                item.estimated_row_count = row["estimated_rows"]
                item.table_comment = row["table_comment"] or item.table_comment
        except Exception:
            pass
        return item
