import re
import time
from typing import Any

import sqlglot
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlglot import exp

from app.core.settings import get_settings
from app.models import DataSource, SqlExecutionLog
from app.schemas import SafeSqlResponse
from app.services.datasource_service import build_database_url

SENSITIVE_FIELD_NAMES = {
    "name",
    "customer_name",
    "cust_name",
    "id_no",
    "cert_no",
    "phone",
    "mobile",
    "address",
    "account_no",
    "card_no",
    "acct_no",
    "证件号",
    "手机号",
    "客户名称",
    "客户姓名",
    "账号",
    "卡号",
    "地址",
}


class SafeSqlExecutor:
    def __init__(
        self,
        db: Session | None = None,
        default_limit: int | None = None,
        max_limit: int | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        settings = get_settings()
        self.db = db
        self.default_limit = default_limit or settings.safe_sql_default_limit
        self.max_limit = max_limit or settings.safe_sql_max_limit
        self.timeout_seconds = timeout_seconds or settings.safe_sql_timeout_seconds

    def validate_and_prepare(self, sql: str, max_rows: int | None = None) -> str:
        normalized = sql.strip().rstrip(";")
        if not normalized:
            raise ValueError("SQL is empty")
        expressions = sqlglot.parse(normalized)
        if len(expressions) != 1:
            raise ValueError("Multiple SQL statements are not allowed")
        tree = expressions[0]
        if tree is None or not self._is_select_statement(tree):
            raise ValueError("Only SELECT statements are allowed")
        if _has_select_star_projection(tree):
            raise ValueError("SELECT * is not allowed")
        return self._force_limit(tree.sql(dialect="postgres"), max_rows)

    def execute(
        self,
        datasource: DataSource,
        sql: str,
        project_id: int,
        max_rows: int | None = None,
        task_id: int | None = None,
        profile_task_id: int | None = None,
        created_by: int | None = None,
    ) -> SafeSqlResponse:
        started = time.perf_counter()
        try:
            sanitized_sql = self.validate_and_prepare(sql, max_rows=max_rows)
        except Exception as exc:
            message = str(exc)
            self._record_log(
                project_id=project_id,
                datasource_id=datasource.id,
                task_id=task_id,
                profile_task_id=profile_task_id,
                sql_text=sql,
                sanitized_sql_text=None,
                status="rejected",
                reject_reason=message,
                execution_time_ms=_elapsed_ms(started),
                created_by=created_by,
            )
            return SafeSqlResponse(status="rejected", reject_reason=message, execution_time_ms=_elapsed_ms(started))

        try:
            engine = create_engine(build_database_url(datasource), connect_args=_connect_args(datasource))
            with engine.connect() as connection:
                result = connection.execute(text(sanitized_sql))
                raw_rows = [dict(row) for row in result.mappings().all()]
            engine.dispose()
            columns, rows, warnings = _sanitize_rows(raw_rows)
            response = SafeSqlResponse(
                status="success",
                columns=columns,
                rows=rows,
                row_count=len(rows),
                execution_time_ms=_elapsed_ms(started),
                warnings=warnings,
                sanitized_sql=sanitized_sql,
            )
            self._record_log(
                project_id=project_id,
                datasource_id=datasource.id,
                task_id=task_id,
                profile_task_id=profile_task_id,
                sql_text=sql,
                sanitized_sql_text=sanitized_sql,
                status="success",
                row_count=response.row_count,
                execution_time_ms=response.execution_time_ms,
                created_by=created_by,
            )
            return response
        except Exception as exc:
            if "engine" in locals():
                engine.dispose()
            message = str(exc)
            self._record_log(
                project_id=project_id,
                datasource_id=datasource.id,
                task_id=task_id,
                profile_task_id=profile_task_id,
                sql_text=sql,
                sanitized_sql_text=sanitized_sql,
                status="failed",
                error_message=message,
                execution_time_ms=_elapsed_ms(started),
                created_by=created_by,
            )
            return SafeSqlResponse(status="failed", error_message=message, sanitized_sql=sanitized_sql, execution_time_ms=_elapsed_ms(started))

    def profile_field(self, table_name: str, field_name: str) -> dict:
        query = self.validate_and_prepare(
            f"select count({field_name}) as non_null_count, "
            f"count(distinct {field_name}) as distinct_count from {table_name}"
        )
        return {
            "status": "reserved",
            "safe_sql": query,
            "timeout_seconds": self.timeout_seconds,
            "note": "MVP validates profiling SQL here; execution goes through execute().",
        }

    def _record_log(self, **kwargs: Any) -> None:
        if self.db is None:
            return
        self.db.add(SqlExecutionLog(**kwargs))
        self.db.commit()

    def _is_select_statement(self, tree: exp.Expression) -> bool:
        return isinstance(tree, (exp.Select, exp.Union, exp.With)) or tree.find(exp.Select) is not None and tree.key == "with"

    def _force_limit(self, sql: str, max_rows: int | None) -> str:
        limit = min(max_rows or self.default_limit, self.max_limit)
        match = re.search(r"\blimit\s+(\d+)\b", sql, flags=re.IGNORECASE)
        if match:
            existing = int(match.group(1))
            if existing > limit:
                return re.sub(r"\blimit\s+\d+\b", f"LIMIT {limit}", sql, flags=re.IGNORECASE)
            return sql
        return f"{sql} LIMIT {limit}"


def _sanitize_rows(raw_rows: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    if not raw_rows:
        return [], [], []
    sensitive = {column for column in raw_rows[0] if column.lower() in SENSITIVE_FIELD_NAMES or column in SENSITIVE_FIELD_NAMES}
    rows = [{key: value for key, value in row.items() if key not in sensitive} for row in raw_rows]
    columns = list(rows[0].keys()) if rows else []
    warnings = [f"已移除敏感字段: {', '.join(sorted(sensitive))}"] if sensitive else []
    return columns, rows, warnings


def _has_select_star_projection(tree: exp.Expression) -> bool:
    for select in tree.find_all(exp.Select):
        for projection in select.expressions:
            projection_sql = projection.sql(dialect="postgres").strip()
            if projection_sql == "*" or projection_sql.endswith(".*"):
                return True
    return False


def _connect_args(datasource: DataSource) -> dict:
    if datasource.db_type == "sqlite":
        return {"check_same_thread": False}
    return {}


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
