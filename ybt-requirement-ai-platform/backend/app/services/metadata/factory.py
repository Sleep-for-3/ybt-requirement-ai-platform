from app.services.metadata.generic_adapter import UnsupportedMetadataAdapter
from app.services.metadata.mysql_compatible_adapter import MySQLCompatibleMetadataAdapter
from app.services.metadata.postgresql_adapter import PostgreSQLMetadataAdapter
from app.services.metadata.sqlite_adapter import SQLiteMetadataAdapter

def create_metadata_adapter(datasource):
    kind = datasource.db_type.lower()
    if kind == "sqlite": return SQLiteMetadataAdapter(datasource)
    if kind in {"postgresql", "postgres"}: return PostgreSQLMetadataAdapter(datasource)
    if kind in {"mysql", "mysql_compatible"}: return MySQLCompatibleMetadataAdapter(datasource)
    return UnsupportedMetadataAdapter(datasource)
