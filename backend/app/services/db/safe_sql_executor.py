import re
import time
from contextlib import contextmanager, suppress
from typing import Any

import sqlglot
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlglot import exp

from app.core.settings import get_settings
from app.models import DataSource, SqlExecutionLog
from app.schemas import SafeSqlResponse
from app.services.datasource_service import build_database_url, ensure_readonly_datasource
from app.services.metadata.sensitivity import looks_sensitive_value

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

SAFE_STATISTIC_COLUMNS = {
    "total_count",
    "null_count",
    "distinct_count",
    "cnt",
    "min_length",
    "max_length",
    "average_length",
}

FORBIDDEN_SQL_NODES = (
    exp.Delete,
    exp.Insert,
    exp.Update,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,
    exp.Copy,
    exp.TruncateTable,
    exp.Into,
    exp.Grant,
    exp.Revoke,
)


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

    def validate_and_prepare(self, sql: str, max_rows: int | None = None, dialect: str | None = None) -> str:
        normalized = sql.strip().rstrip(";")
        if not normalized:
            raise ValueError("SQL is empty")
        expressions = sqlglot.parse(normalized)
        if len(expressions) != 1:
            raise ValueError("Multiple SQL statements are not allowed")
        tree = expressions[0]
        if tree is None or not self._is_select_statement(tree):
            raise ValueError("Only SELECT statements are allowed")
        if any(isinstance(node, FORBIDDEN_SQL_NODES) for node in tree.walk()):
            raise ValueError("DDL/DML statements are not allowed, including writable CTEs")
        if _has_select_star_projection(tree):
            raise ValueError("SELECT * is not allowed")
        resolved_dialect = _sqlglot_dialect(dialect)
        if resolved_dialect is None:
            raise ValueError(
                f"Safe SELECT is not supported for dialect '{dialect or 'unknown'}'"
            )
        limit = min(max_rows or self.default_limit, self.max_limit)
        existing = _existing_outer_limit(tree)
        if existing is not None:
            # Never raise a tighter limit the statement already applies.
            limit = min(limit, existing)
        # B06: the row limit is applied on the AST, so a subquery or a string literal that merely
        # contains LIMIT can no longer satisfy the check for the outer statement.
        limited = _apply_ast_limit(tree, limit)
        # The sanitizer needs to know which returned columns are genuinely safe aggregates.
        self._safe_aggregate_aliases = _safe_aggregate_aliases(tree)
        return limited.sql(dialect=resolved_dialect)

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
            ensure_readonly_datasource(datasource)
        except ValueError as exc:
            self._record_log(project_id=project_id,datasource_id=datasource.id,task_id=task_id,profile_task_id=profile_task_id,sql_text=sql,sanitized_sql_text=None,status="rejected",reject_reason=str(exc),execution_time_ms=_elapsed_ms(started),created_by=created_by)
            return SafeSqlResponse(status="rejected",reject_reason=str(exc),execution_time_ms=_elapsed_ms(started))
        try:
            sanitized_sql = self.validate_and_prepare(sql, max_rows=max_rows, dialect=datasource.db_type)
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
                with _statement_timeout(connection, datasource.db_type, self.timeout_seconds):
                    result = connection.execute(text(sanitized_sql))
                    # B06 second layer: never materialise an unbounded result set.
                    mappings = result.mappings()
                    fetchmany = getattr(mappings, "fetchmany", None)
                    if callable(fetchmany):
                        raw_rows = [dict(row) for row in fetchmany(self.max_limit + 1)]
                        if len(raw_rows) > self.max_limit:
                            raw_rows = raw_rows[: self.max_limit]
                    else:  # pragma: no cover - simple result doubles
                        raw_rows = [dict(row) for row in mappings.all()][: self.max_limit]
            engine.dispose()
            columns, rows, warnings = _sanitize_rows(
                raw_rows, safe_aggregate_aliases=getattr(self, "_safe_aggregate_aliases", None)
            )
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
        """Deprecated text-level fallback; kept only for callers that still hold rendered SQL.

        New code must go through the AST limit in ``validate_and_prepare`` (B06).
        """

        limit = min(max_rows or self.default_limit, self.max_limit)
        return _apply_ast_limit(sqlglot.parse_one(sql), limit).sql()


SAFE_QUERY_DIALECTS = {"postgresql", "mysql", "mysql_compatible", "sqlite"}


def _apply_ast_limit(tree: exp.Expression, limit: int) -> exp.Expression:
    """B06: set the row limit on the parsed statement itself.

    A subquery, CTE, UNION arm or a string literal containing ``LIMIT`` must never be mistaken
    for the outer statement's limit, and the rendered form uses the target dialect (TOP / FETCH
    for dialects that need it) instead of appending PostgreSQL-style ``LIMIT``.
    """

    try:
        limited = tree.limit(limit)
    except (AttributeError, TypeError) as exc:  # pragma: no cover - defensive
        raise ValueError("Unable to apply a row limit to this statement") from exc
    return limited


def _existing_outer_limit(tree: exp.Expression) -> int | None:
    limit = tree.args.get("limit")
    if limit is None:
        return None
    try:
        return int(limit.expression.this)
    except (AttributeError, TypeError, ValueError):  # pragma: no cover - defensive
        return None


_UNWRAP_TYPES = tuple(
    node_type
    for node_type in (getattr(exp, name, None) for name in ("Alias", "Cast", "TryCast", "Paren"))
    if node_type is not None
)
_SET_OPERATION_TYPES = tuple(
    getattr(exp, name) for name in ("Union", "Except", "Intersect") if hasattr(exp, name)
)


def _unwrap_projection(node: exp.Expression) -> exp.Expression:
    core = node
    while isinstance(core, _UNWRAP_TYPES):
        inner = core.this
        if not isinstance(inner, exp.Expression):
            break
        core = inner
    return core


def _output_scopes(tree: exp.Expression) -> list[exp.Select]:
    """The SELECTs that actually define the returned columns, never a nested subquery.

    ``tree.find_all(exp.Select)`` also walks ``WHERE EXISTS (...)`` / CTE bodies; an inner
    ``COUNT(*) AS cnt`` used to overwrite the outer ``phone AS cnt`` exemption.
    """
    if _SET_OPERATION_TYPES and isinstance(tree, _SET_OPERATION_TYPES):
        scopes: list[exp.Select] = []
        for side in (tree.left, tree.right):
            if isinstance(side, exp.Expression):
                scopes.extend(_output_scopes(side))
        return scopes
    if isinstance(tree, exp.Select):
        return [tree]
    found = tree.find(exp.Select)
    return [found] if found is not None else []


def _safe_aggregate_aliases(tree: exp.Expression) -> dict[str, bool]:
    """Map returned column name -> whether it is a genuinely safe statistic.

    B04 + N01/BF01: the exemption is decided **inside the outer output scope** and must hold
    for the whole projection expression:

    * a subquery's ``COUNT(*) AS cnt`` must not lend its exemption to an outer ``phone AS cnt``
      (previously the last projection visited won, across every nested SELECT);
    * the aggregate must be the projection itself, so ``phone || CAST(COUNT(*) AS TEXT) AS cnt``
      stays screened (previously only the aggregate's own arguments were inspected);
    * any sensitive column anywhere in the expression cancels the exemption.

    Anything that cannot be *proven* safe falls back to ordinary value screening (fail closed).
    """
    flags: dict[str, bool] = {}
    for scope in _output_scopes(tree):
        for projection in scope.expressions:
            name = (projection.alias_or_name or "").lower()
            if not name:
                continue
            core = _unwrap_projection(projection)
            referenced = {column.name.lower() for column in projection.find_all(exp.Column)}
            safe = isinstance(core, exp.AggFunc) and not (referenced & SENSITIVE_FIELD_NAMES)
            flags[name] = flags.get(name, True) and safe
    return flags


def _sanitize_rows(
    raw_rows: list[dict[str, Any]],
    safe_aggregate_aliases: dict[str, bool] | None = None,
) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    if not raw_rows:
        return [], [], []

    safe_aggregates = safe_aggregate_aliases or {}
    sensitive = {column for column in raw_rows[0] if column.lower() in SENSITIVE_FIELD_NAMES or column in SENSITIVE_FIELD_NAMES}
    value_sensitive = {
        column
        for column in raw_rows[0]
        if column not in sensitive
        # B04: the exemption needs a verified aggregate projection, not merely a safe-sounding
        # alias chosen by the client.
        and not (column.lower() in SAFE_STATISTIC_COLUMNS and safe_aggregates.get(column.lower(), False))
        and any(looks_sensitive_value(row.get(column)) for row in raw_rows)
    }
    sensitive.update(value_sensitive)
    rows = [{key: value for key, value in row.items() if key not in sensitive} for row in raw_rows]
    columns = list(rows[0].keys()) if rows else []
    warnings = [f"已移除敏感或疑似敏感结果字段: {', '.join(sorted(sensitive))}"] if sensitive else []
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


def _sqlglot_dialect(db_type: str | None) -> str | None:
    """Map a connector to a dialect we can safely rewrite, or None when unsupported.

    B09: Oracle / SQL Server / Db2 used to fall back to PostgreSQL and were emitted with
    ``LIMIT``. Those connectors are not verified for safe query yet, so they must be refused
    instead of silently producing a statement the target database cannot run.
    """

    if db_type is None:
        # No dialect given: keep the historical default (PostgreSQL rendering).
        return "postgres"

    if db_type in {"mysql", "mysql_compatible"}:
        return "mysql"
    if db_type == "sqlite":
        return "sqlite"
    if db_type in {"postgresql", "postgres"}:
        return "postgres"
    return None


@contextmanager
def _statement_timeout(connection: Any, db_type: str, timeout_seconds: float):
    milliseconds = max(1, int(timeout_seconds * 1000))
    if db_type == "sqlite":
        driver_connection = connection.connection.driver_connection
        deadline = time.monotonic() + timeout_seconds
        driver_connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        try:
            yield
        finally:
            driver_connection.set_progress_handler(None, 0)
        return
    if db_type == "postgresql":
        connection.exec_driver_sql(f"SET LOCAL statement_timeout = {milliseconds}")
        yield
        return
    if db_type in {"mysql", "mysql_compatible"}:
        connection.exec_driver_sql(f"SET SESSION MAX_EXECUTION_TIME = {milliseconds}")
        try:
            yield
        finally:
            with suppress(Exception):
                connection.exec_driver_sql("SET SESSION MAX_EXECUTION_TIME = 0")
        return
    yield
