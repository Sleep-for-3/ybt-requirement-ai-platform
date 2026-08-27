from __future__ import annotations

import socket
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError, OperationalError

from app.core.crypto import encrypt_secret
from app.models import DataSource
from app.schemas import DataSourceCreate
from app.services.connectors.registry import canonical_engine_type, get_connector
from app.services.datasource_service import _connect_args, build_database_url


def diagnose_payload(project_id: int, payload: DataSourceCreate) -> dict[str, Any]:
    datasource = DataSource(
        project_id=project_id,
        name=payload.name,
        display_name=payload.display_name,
        description=payload.description,
        db_type=canonical_engine_type(payload.db_type),
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
    return diagnose_datasource(datasource)


def diagnose_datasource(datasource: DataSource) -> dict[str, Any]:
    connector = get_connector(datasource.db_type)
    steps: list[dict[str, str]] = []
    if connector is None:
        return _failure("unsupported", "未注册的数据源类型", steps)
    if connector["status"] != "available":
        code = "driver_missing" if connector["status"] == "driver_missing" else "unsupported"
        return _failure(code, _status_message(connector), steps, connector=connector)
    driver = next((item["label"] for item in connector["drivers"] if item["installed"]), None)
    steps.append({"code": "driver", "status": "success", "message": f"已检测到 {driver}"})
    if not datasource.readonly_flag:
        return _failure("permission_denied", "必须启用只读策略后才能测试连接", steps, connector=connector, driver=driver)

    engine = None
    try:
        engine = create_engine(
            build_database_url(datasource),
            connect_args=_connect_args(datasource),
            pool_pre_ping=True,
            pool_recycle=300,
        )
        with engine.connect() as connection:
            connection.execute(text("select 1"))
            readonly_validation, readonly_step = _readonly_validation(connection, datasource.db_type)
            steps.extend([
                {"code": "network", "status": "success", "message": "网络连接已建立"},
                {"code": "authentication", "status": "success", "message": "认证成功"},
                readonly_step,
            ])
            version = _database_version(connection, datasource.db_type)
            steps.append({"code": "version", "status": "success", "message": "数据库版本已读取"})
        try:
            schemas = _schemas(engine, connector)
        except Exception as exc:
            code, message = classify_connection_error(exc)
            if code in {"permission_denied", "unsupported"}:
                code = "metadata_permission_missing"
                message = "数据库连接已建立，但账号缺少 Catalog/Schema 元数据读取权限"
            return _failure(code, message, steps, connector=connector, driver=driver)
        steps.append({"code": "metadata", "status": "success", "message": f"发现 {len(schemas)} 个可纳管范围"})
        return {
            "status": "success", "message": "连接、认证与元数据权限检查通过", "error_code": None,
            "driver": driver, "database_version": version, "schemas": schemas,
            "readonly_validation": readonly_validation, "steps": steps,
        }
    except Exception as exc:
        code, message = classify_connection_error(exc)
        return _failure(code, message, steps, connector=connector, driver=driver)
    finally:
        if engine is not None:
            engine.dispose()


def classify_connection_error(exc: Exception) -> tuple[str, str]:
    message = str(getattr(exc, "orig", exc)).lower()
    if isinstance(exc, (ModuleNotFoundError, ImportError)) or "no module named" in message or "can't load plugin" in message:
        return "driver_missing", "数据库 Driver 未安装或无法加载"
    if isinstance(exc, socket.gaierror) or any(value in message for value in ("name or service not known", "nodename nor servname", "getaddrinfo failed", "could not translate host name")):
        return "dns_failure", "无法解析数据库主机名"
    if isinstance(exc, TimeoutError) or "timed out" in message or "timeout expired" in message:
        return "connection_timeout", "数据库连接超时"
    if any(value in message for value in ("connection refused", "network is unreachable", "no route to host", "server closed the connection")):
        return "network_unreachable", "无法连接数据库网络地址"
    if any(value in message for value in ("password authentication failed", "access denied for user", "login failed for user", "invalid username/password", "ora-01017")):
        return "auth_failed", "数据库用户名或密码验证失败"
    if any(value in message for value in ("database does not exist", "unknown database", "cannot open database", "ora-12514")):
        return "database_not_found", "指定数据库或服务不存在"
    if any(value in message for value in ("service name", "sid", "ora-12154", "ora-12505")):
        return "service_name_invalid", "Oracle Service Name 或 SID 无效"
    if any(value in message for value in ("ssl", "tls", "certificate verify failed", "certificate_unknown")):
        return "tls_failed", "TLS/SSL 握手或证书验证失败"
    if any(value in message for value in ("permission denied", "not authorized", "insufficient privilege")):
        return "permission_denied", "数据库账号权限不足"
    if isinstance(exc, (OperationalError, DBAPIError)):
        return "network_unreachable", "数据库连接失败，请检查网络、地址和服务状态"
    return "unsupported", "连接检查失败，请核对 Connector 参数与 Driver"


def _database_version(connection, engine_type: str) -> str | None:
    statement = "select sqlite_version()" if engine_type == "sqlite" else "select version()"
    try:
        value = connection.execute(text(statement)).scalar_one_or_none()
        return str(value)[:300] if value is not None else None
    except Exception:
        return None


def _schemas(engine, connector: dict[str, Any]) -> list[str]:
    names = inspect(engine).get_schema_names()
    excluded = {
        "postgresql": {"pg_catalog", "information_schema", "pg_toast"},
        "mysql_compatible": {"information_schema", "mysql", "performance_schema", "sys"},
    }.get(connector["engine_type"], set())
    return sorted(name for name in names if name not in excluded)[:500]


def _readonly_validation(connection, engine_type: str) -> tuple[str, dict[str, str]]:
    statement = {
        "postgresql": "show transaction_read_only",
        "mysql_compatible": "select @@transaction_read_only",
    }.get(engine_type)
    if statement:
        try:
            value = connection.execute(text(statement)).scalar_one_or_none()
            verified = str(value).strip().lower() in {"1", "on", "true"}
            if verified:
                return "database_verified", {"code": "readonly", "status": "success", "message": "数据库返回只读事务信号；平台安全查询守卫同时启用"}
            return "policy_guard_only", {"code": "readonly", "status": "warning", "message": "数据库未返回全局只读信号；平台仍强制安全查询，账号 GRANT 需管理员复核"}
        except Exception:
            pass
    return "policy_guard_only", {"code": "readonly", "status": "warning", "message": "平台已强制只读策略与安全查询守卫；未通过写入探针伪造账号权限结论"}


def _failure(code: str, message: str, steps: list[dict[str, str]], *, connector=None, driver=None) -> dict[str, Any]:
    steps.append({"code": code, "status": "failed", "message": message})
    return {
        "status": "failed", "message": message, "error_code": code, "driver": driver,
        "database_version": None, "schemas": [],
        "readonly_validation": connector["readonly_validation"] if connector else "unsupported", "steps": steps,
    }


def _status_message(connector: dict[str, Any]) -> str:
    return {
        "disabled": f"{connector['label']} Connector 当前未启用",
        "driver_missing": f"{connector['label']} Connector 缺少可用 Driver",
        "extension_only": "GBase 具体产品未确定，仅保留扩展位，未声明兼容性",
    }.get(connector["status"], f"{connector['label']} Connector 当前不可用")
