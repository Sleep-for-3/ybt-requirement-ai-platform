from app.services.metadata.generic_adapter import SqlAlchemyMetadataAdapter

class MySQLCompatibleMetadataAdapter(SqlAlchemyMetadataAdapter):
    system_schemas = {"information_schema", "mysql", "performance_schema", "sys"}
