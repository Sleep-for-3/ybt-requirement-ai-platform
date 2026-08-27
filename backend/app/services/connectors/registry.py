from __future__ import annotations

from importlib.util import find_spec
from typing import Any

from app.core.settings import get_settings


CONNECTORS: tuple[dict[str, Any], ...] = (
    {
        "engine_type": "sqlite", "label": "SQLite", "aliases": [], "setting": "enable_sqlite_datasource",
        "drivers": (("sqlite3", "Python 内置 sqlite3", True),), "default_port": None,
        "required_fields": ["name", "database_name"], "optional_fields": ["display_name", "description"],
        "database_label": "数据库文件", "schema_label": "main", "service_name_mode": "unsupported",
        "ssl_tls_capability": "not_applicable", "metadata_discovery": True, "safe_query": True,
        "readonly_validation": "safe_query_guard", "implementation": "native",
    },
    {
        "engine_type": "postgresql", "label": "PostgreSQL", "aliases": ["postgres"], "setting": "enable_postgres_datasource",
        "drivers": (("psycopg", "psycopg 3", False),), "default_port": 5432,
        "required_fields": ["name", "host", "port", "database_name", "username", "password"],
        "optional_fields": ["display_name", "description", "schema_name", "ssl_mode"],
        "database_label": "Database", "schema_label": "Schema", "service_name_mode": "unsupported",
        "ssl_tls_capability": "supported", "metadata_discovery": True, "safe_query": True,
        "readonly_validation": "policy_and_server_signal", "implementation": "native",
    },
    {
        "engine_type": "mysql_compatible", "label": "MySQL / MySQL-compatible", "aliases": ["mysql", "mariadb"], "setting": "enable_mysql_datasource",
        "drivers": (("pymysql", "PyMySQL", False),), "default_port": 3306,
        "required_fields": ["name", "host", "port", "database_name", "username", "password"],
        "optional_fields": ["display_name", "description", "ssl_mode"],
        "database_label": "Database", "schema_label": "Database", "service_name_mode": "unsupported",
        "ssl_tls_capability": "driver_configurable", "metadata_discovery": True, "safe_query": True,
        "readonly_validation": "policy_and_server_signal", "implementation": "native",
    },
    {
        "engine_type": "oracle", "label": "Oracle", "aliases": [], "setting": "enable_oracle_datasource",
        "drivers": (("oracledb", "python-oracledb", False),), "default_port": 1521,
        "required_fields": ["name", "host", "port", "service_name", "username", "password"],
        "optional_fields": ["display_name", "description", "schema_name", "sid", "ssl_mode"],
        "database_label": "Service Name / SID", "schema_label": "Schema", "service_name_mode": "service_name_or_sid",
        "ssl_tls_capability": "driver_configurable", "metadata_discovery": True, "safe_query": True,
        "readonly_validation": "policy_only", "implementation": "sqlalchemy_generic",
    },
    {
        "engine_type": "sqlserver", "label": "SQL Server", "aliases": ["mssql"], "setting": "enable_sqlserver_datasource",
        "drivers": (("pyodbc", "pyodbc", False),), "default_port": 1433,
        "required_fields": ["name", "host", "port", "database_name", "username", "password"],
        "optional_fields": ["display_name", "description", "schema_name", "odbc_driver", "ssl_mode"],
        "database_label": "Database / Catalog", "schema_label": "Schema", "service_name_mode": "unsupported",
        "ssl_tls_capability": "driver_configurable", "metadata_discovery": True, "safe_query": True,
        "readonly_validation": "policy_only", "implementation": "sqlalchemy_generic",
    },
    {
        "engine_type": "db2", "label": "IBM Db2", "aliases": [], "setting": "enable_db2_datasource",
        "drivers": (("ibm_db", "ibm-db + ibm-db-sa", False),), "default_port": 50000,
        "required_fields": ["name", "host", "port", "database_name", "username", "password"],
        "optional_fields": ["display_name", "description", "schema_name", "ssl_mode"],
        "database_label": "Database", "schema_label": "Schema", "service_name_mode": "unsupported",
        "ssl_tls_capability": "driver_configurable", "metadata_discovery": True, "safe_query": True,
        "readonly_validation": "policy_only", "implementation": "sqlalchemy_generic",
    },
    {
        "engine_type": "gbase", "label": "GBase（扩展位）", "aliases": [], "setting": "enable_gbase_datasource",
        "drivers": (), "default_port": None,
        "required_fields": ["name"], "optional_fields": ["display_name", "description"],
        "database_label": "待具体产品确认", "schema_label": "待具体产品确认", "service_name_mode": "product_specific",
        "ssl_tls_capability": "product_specific", "metadata_discovery": False, "safe_query": False,
        "readonly_validation": "unsupported", "implementation": "extension_only",
    },
)


def connector_registry() -> list[dict[str, Any]]:
    settings = get_settings()
    output: list[dict[str, Any]] = []
    for definition in CONNECTORS:
        item = {key: value for key, value in definition.items() if key not in {"setting", "drivers"}}
        enabled = bool(getattr(settings, definition["setting"], False))
        drivers = [
            {"module": module, "label": label, "installed": builtin or _installed(module)}
            for module, label, builtin in definition["drivers"]
        ]
        installed = any(driver["installed"] for driver in drivers)
        if definition["implementation"] == "extension_only":
            status = "extension_only"
        elif not enabled:
            status = "disabled"
        elif not installed:
            status = "driver_missing"
        else:
            status = "available"
        item.update({"enabled": enabled, "status": status, "drivers": drivers})
        output.append(item)
    return output


def get_connector(engine_type: str) -> dict[str, Any] | None:
    normalized = engine_type.strip().lower()
    return next((item for item in connector_registry() if normalized == item["engine_type"] or normalized in item["aliases"]), None)


def canonical_engine_type(engine_type: str) -> str:
    connector = get_connector(engine_type)
    return connector["engine_type"] if connector else engine_type.strip().lower()


def _installed(module: str) -> bool:
    try:
        return find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False
