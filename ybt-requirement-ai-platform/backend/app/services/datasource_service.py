import re
from datetime import datetime, timezone

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_secret, encrypt_secret
from app.models import DataSource
from app.schemas import DataSourceCreate, DataSourceUpdate

DATASOURCE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
SUPPORTED_TEST_TYPES = {"sqlite", "postgresql", "mysql", "mysql_compatible"}


def validate_datasource_name(name: str) -> None:
    if not DATASOURCE_NAME_PATTERN.match(name):
        raise ValueError("DataSource.name 只能包含小写字母、数字、下划线，必须以字母开头，长度 3 到 64")


def create_datasource(db: Session, project_id: int, payload: DataSourceCreate) -> DataSource:
    validate_datasource_name(payload.name)
    validate_connection_params(payload.connection_params_json)
    existing = db.scalar(select(DataSource).where(DataSource.project_id == project_id, DataSource.name == payload.name))
    if existing:
        raise ValueError("同一项目下 DataSource.name 不能重复")
    datasource = DataSource(
        project_id=project_id,
        name=payload.name,
        display_name=payload.display_name,
        description=payload.description,
        db_type=payload.db_type.lower(),
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
    if password:
        datasource.encrypted_password = encrypt_secret(password)
    for key, value in data.items():
        if key == "db_type" and value:
            value = value.lower()
        setattr(datasource, key, value)
    db.commit()
    db.refresh(datasource)
    return datasource


def delete_datasource(db: Session, datasource: DataSource) -> None:
    db.delete(datasource)
    db.commit()


def test_datasource_connection(db: Session, datasource: DataSource) -> tuple[str, str]:
    if datasource.db_type not in SUPPORTED_TEST_TYPES:
        status, message = "unsupported", f"{datasource.db_type} 数据源测试暂未启用"
    else:
        try:
            engine = create_engine(build_database_url(datasource), connect_args=_connect_args(datasource), pool_pre_ping=True)
            with engine.connect() as connection:
                connection.execute(text("select 1"))
            engine.dispose()
            status, message = "success", "连接测试成功"
        except Exception as exc:
            if "engine" in locals():
                engine.dispose()
            status, message = "failed", str(exc)
    datasource.last_test_status = status
    datasource.last_test_message = message
    datasource.last_test_at = datetime.now(timezone.utc)
    db.commit()
    return status, message


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
        return URL.create("postgresql+psycopg", username=username or None, password=password or None, host=host, port=port, database=database).render_as_string(hide_password=False)
    if datasource.db_type in {"mysql", "mysql_compatible"}:
        host = datasource.host or "localhost"
        port = datasource.port or 3306
        database = datasource.database_name or ""
        username = datasource.username or ""
        password = decrypt_secret(datasource.encrypted_password) or ""
        driver = (datasource.connection_params_json or {}).get("driver", "pymysql")
        return URL.create(f"mysql+{driver}", username=username or None, password=password or None, host=host, port=port, database=database).render_as_string(hide_password=False)
    raise ValueError(f"{datasource.db_type} 数据源测试暂未启用")


def _connect_args(datasource: DataSource) -> dict:
    if datasource.db_type == "sqlite":
        return {"check_same_thread": False}
    return {}


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
