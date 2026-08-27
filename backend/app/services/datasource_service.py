import re
from datetime import datetime, timezone

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_secret, encrypt_secret
from app.models import DataSource
from app.schemas import DataSourceCreate, DataSourceUpdate
from app.services.connectors.registry import canonical_engine_type, get_connector

DATASOURCE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


def ensure_readonly_datasource(datasource: DataSource) -> None:
    if not datasource.enabled:
        raise ValueError("数据源已禁用，不能执行连接、同步、查询或探查")
    if not datasource.readonly_flag:
        raise ValueError("数据源未标记为只读，拒绝执行连接、同步、查询或探查")


def validate_datasource_name(name: str) -> None:
    if not DATASOURCE_NAME_PATTERN.match(name):
        raise ValueError("DataSource.name 只能包含小写字母、数字、下划线，必须以字母开头，长度 3 到 64")


def create_datasource(db: Session, project_id: int, payload: DataSourceCreate) -> DataSource:
    validate_datasource_name(payload.name)
    validate_connection_params(payload.connection_params_json)
    engine_type = canonical_engine_type(payload.db_type)
    _require_available_connector(engine_type)
    existing = db.scalar(select(DataSource).where(DataSource.project_id == project_id, DataSource.name == payload.name))
    if existing:
        raise ValueError("同一项目下 DataSource.name 不能重复")
    datasource = DataSource(
        project_id=project_id,
        name=payload.name,
        display_name=payload.display_name,
        description=payload.description,
        db_type=engine_type,
        host=payload.host,
        port=payload.port,
        database_name=payload.database_name,
        service_name=payload.service_name,
        schema_name=payload.schema_name,
        username=payload.username,
        encrypted_password=encrypt_secret(payload.password),
        connection_params_json=payload.connection_params_json,
        readonly_flag=payload.readonly_flag,
        enabled=payload.enabled,
    )
    db.add(datasource)
    db.commit()
    db.refresh(datasource)
    return datasource


def update_datasource(db: Session, datasource: DataSource, payload: DataSourceUpdate) -> DataSource:
    data = payload.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    if data.get("connection_params_json") is not None:
        validate_connection_params(data["connection_params_json"])
    if data.get("db_type"):
        data["db_type"] = canonical_engine_type(data["db_type"])
        _require_available_connector(data["db_type"])
    if password:
        datasource.encrypted_password = encrypt_secret(password)
    for key, value in data.items():
        setattr(datasource, key, value)
    db.commit()
    db.refresh(datasource)
    return datasource


def delete_datasource(db: Session, datasource: DataSource) -> None:
    db.delete(datasource)
    db.commit()


def test_datasource_connection(db: Session, datasource: DataSource) -> dict:
    from app.services.connectors.diagnostics import diagnose_datasource

    ensure_readonly_datasource(datasource)
    result = diagnose_datasource(datasource)
    datasource.last_test_status = result["status"]
    datasource.last_test_message = result["message"]
    datasource.last_test_at = datetime.now(timezone.utc)
    datasource.last_database_version = result.get("database_version")
    datasource.last_discovered_schemas_json = result.get("schemas") or []
    db.commit()
    return result


def build_database_url(datasource: DataSource) -> str:
    configured_url = (datasource.connection_params_json or {}).get("sqlalchemy_url")
    if configured_url:
        validate_connection_params(datasource.connection_params_json)
        url = make_url(str(configured_url))
        if datasource.username:
            url = url.set(username=datasource.username, password=decrypt_secret(datasource.encrypted_password))
        return url.render_as_string(hide_password=False)
    if datasource.db_type == "sqlite":
        database_name = datasource.database_name or ":memory:"
        return "sqlite:///:memory:" if database_name == ":memory:" else f"sqlite:///{database_name}"
    if datasource.db_type == "postgresql":
        host = datasource.host or "localhost"
        port = datasource.port or 5432
        database = datasource.database_name or ""
        username = datasource.username or ""
        password = decrypt_secret(datasource.encrypted_password) or ""
        query = _tls_query(datasource, "sslmode")
        return URL.create("postgresql+psycopg", username=username or None, password=password or None, host=host, port=port, database=database, query=query).render_as_string(hide_password=False)
    # Existing installations may still persist the public ``mysql`` alias.
    # New writes are canonicalized, but connection execution must remain
    # backward-compatible with already stored datasource rows.
    if datasource.db_type in {"mysql", "mysql_compatible"}:
        host = datasource.host or "localhost"
        port = datasource.port or 3306
        database = datasource.database_name or ""
        username = datasource.username or ""
        password = decrypt_secret(datasource.encrypted_password) or ""
        driver = (datasource.connection_params_json or {}).get("driver", "pymysql")
        return URL.create(f"mysql+{driver}", username=username or None, password=password or None, host=host, port=port, database=database).render_as_string(hide_password=False)
    if datasource.db_type == "oracle":
        params = datasource.connection_params_json or {}
        identifier_type = params.get("oracle_identifier_type", "service_name")
        service = datasource.service_name or datasource.database_name or ""
        query = {"service_name": service} if identifier_type != "sid" and service else {}
        return URL.create("oracle+oracledb", username=datasource.username or None, password=decrypt_secret(datasource.encrypted_password) or None, host=datasource.host or "localhost", port=datasource.port or 1521, database=service if identifier_type == "sid" else None, query=query).render_as_string(hide_password=False)
    if datasource.db_type == "sqlserver":
        params = datasource.connection_params_json or {}
        query = {"driver": str(params.get("odbc_driver") or "ODBC Driver 18 for SQL Server")}
        if params.get("ssl_mode") == "disable": query["Encrypt"] = "no"
        return URL.create("mssql+pyodbc", username=datasource.username or None, password=decrypt_secret(datasource.encrypted_password) or None, host=datasource.host or "localhost", port=datasource.port or 1433, database=datasource.database_name or "", query=query).render_as_string(hide_password=False)
    if datasource.db_type == "db2":
        return URL.create("db2+ibm_db", username=datasource.username or None, password=decrypt_secret(datasource.encrypted_password) or None, host=datasource.host or "localhost", port=datasource.port or 50000, database=datasource.database_name or "").render_as_string(hide_password=False)
    raise ValueError(f"{datasource.db_type} 数据源测试暂未启用")


def _connect_args(datasource: DataSource) -> dict:
    if datasource.db_type == "sqlite":
        return {"check_same_thread": False}
    return {}


def _tls_query(datasource: DataSource, key: str) -> dict[str, str]:
    mode = (datasource.connection_params_json or {}).get("ssl_mode")
    return {key: str(mode)} if mode else {}


def _require_available_connector(engine_type: str) -> None:
    connector = get_connector(engine_type)
    if connector is None:
        raise ValueError(f"未注册的数据源类型: {engine_type}")
    if connector["status"] == "available":
        return
    if connector["status"] == "driver_missing":
        raise ValueError(f"{connector['label']} Driver 未安装")
    if connector["status"] == "extension_only":
        raise ValueError("GBase 具体产品未确定，仅保留扩展位，不能创建连接")
    raise ValueError(f"{connector['label']} Connector 当前未启用")


def validate_connection_params(params: dict | None) -> None:
    """Keep credentials on encrypted datasource fields, never in plaintext JSON."""
    params = params or {}
    configured_url = params.get("sqlalchemy_url")
    if configured_url:
        try:
            url = make_url(str(configured_url))
        except Exception as exc:
            raise ValueError("connection_params_json.sqlalchemy_url 格式无效") from exc
        if url.username or url.password:
            raise ValueError("SQLAlchemy URL 不得包含用户名或密码等凭据，请使用数据源凭据字段")
        if _contains_secret_parameter(dict(url.query)):
            raise ValueError("SQLAlchemy URL 查询参数不得包含密码、令牌或密钥等明文凭据")
    if _contains_secret_parameter(params):
        raise ValueError("connection_params_json 不得包含密码、令牌或密钥等明文凭据")


def _contains_secret_parameter(value: object) -> bool:
    secret_fragments = ("password", "passwd", "pwd", "secret", "token", "credential", "api_key", "access_key")
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key).lower()
            if normalized_key != "sqlalchemy_url" and any(fragment in normalized_key for fragment in secret_fragments):
                if item not in (None, "", False):
                    return True
            if _contains_secret_parameter(item):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_secret_parameter(item) for item in value)
    return False
