"""W04 / B04+B06+B09: the safe-query contract must hold against real bypass attempts.

These tests reproduce the three reported risks instead of re-checking implementation strings:

* B06 - the row limit was decided by a regex over the rendered SQL, so a LIMIT inside a
  subquery or a string literal satisfied the check for the outer statement.
* B04 - ``_sanitize_rows`` skipped value screening when the *returned column name* looked like
  a statistic, so ``phone AS cnt`` leaked the phone values.
* B09 - Oracle / SQL Server / Db2 were rendered as PostgreSQL and emitted ``LIMIT`` even though
  their dialect, limit, timeout and read-only account are not verified.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

from app.services.connectors.registry import CONNECTORS
from app.services.db.safe_sql_executor import (
    SENSITIVE_FIELD_NAMES,
    SafeSqlExecutor,
    _safe_aggregate_aliases,
    _sanitize_rows,
)


def _outer_limit(sql: str) -> int | None:
    """The row limit attached to the outermost statement of the rendered SQL."""
    tree = sqlglot.parse_one(sql)
    limit = tree.args.get("limit")
    if limit is None:
        return None
    return int(limit.expression.this)


def test_an_outer_limit_is_added_when_the_statement_has_none():
    executor = SafeSqlExecutor()
    rendered = executor.validate_and_prepare("SELECT n FROM sample", max_rows=2, dialect="postgresql")
    assert _outer_limit(rendered) == 2


def test_a_subquery_limit_does_not_satisfy_the_outer_limit():
    executor = SafeSqlExecutor()
    rendered = executor.validate_and_prepare(
        "SELECT n FROM sample WHERE n IN (SELECT n FROM sample LIMIT 1) OR n > 1",
        max_rows=2,
        dialect="postgresql",
    )
    assert _outer_limit(rendered) == 2, rendered
    # the inner limit is preserved, it just no longer counts as the outer one
    assert "LIMIT 1" in rendered


def test_a_string_literal_containing_limit_does_not_satisfy_the_outer_limit():
    executor = SafeSqlExecutor()
    rendered = executor.validate_and_prepare("SELECT 'limit 1' AS marker, n FROM sample",
                                             max_rows=2, dialect="postgresql")
    assert _outer_limit(rendered) == 2, rendered


def test_cte_and_union_arms_do_not_satisfy_the_outer_limit():
    executor = SafeSqlExecutor()
    cte = executor.validate_and_prepare(
        "WITH recent AS (SELECT n FROM sample LIMIT 1) SELECT n FROM recent",
        max_rows=2, dialect="postgresql")
    assert _outer_limit(cte) == 2, cte

    union = executor.validate_and_prepare(
        "SELECT n FROM sample UNION ALL SELECT n FROM sample LIMIT 1",
        max_rows=2, dialect="postgresql")
    # A trailing LIMIT after UNION ALL belongs to the whole union, so it is a genuine outer
    # limit: it must be honoured (not raised), while the CTE's inner LIMIT above must not.
    assert _outer_limit(union) == 1, union


def test_a_tighter_requested_limit_is_not_raised_by_the_statement():
    executor = SafeSqlExecutor()
    rendered = executor.validate_and_prepare("SELECT n FROM sample LIMIT 1", max_rows=5,
                                             dialect="postgresql")
    assert _outer_limit(rendered) == 1


def test_the_limit_is_rendered_in_the_target_dialect():
    executor = SafeSqlExecutor()
    mysql = executor.validate_and_prepare("SELECT n FROM sample", max_rows=2, dialect="mysql_compatible")
    assert _outer_limit(mysql) == 2


def test_a_client_alias_cannot_exempt_a_sensitive_value():
    """``phone AS cnt`` must still have its values removed."""
    tree = sqlglot.parse_one("SELECT phone AS cnt, account_no AS total_count FROM customers")
    aliases = _safe_aggregate_aliases(tree)

    rows = [{"cnt": "13800001111", "total_count": "6222000012345678"}]
    columns, sanitized, warnings = _sanitize_rows(rows, safe_aggregate_aliases=aliases)
    assert columns == []
    assert sanitized == [{}]
    assert warnings, "removing sensitive fields must be reported"
    assert all(alias not in columns for alias in ("cnt", "total_count"))


def test_a_genuine_safe_statistic_keeps_its_exemption():
    tree = sqlglot.parse_one("SELECT count(*) AS cnt FROM customers")
    aliases = _safe_aggregate_aliases(tree)
    assert aliases["cnt"] is True

    columns, sanitized, _warnings = _sanitize_rows([{"cnt": 5}], safe_aggregate_aliases=aliases)
    assert columns == ["cnt"] and sanitized == [{"cnt": 5}]


def test_an_aggregate_over_a_sensitive_column_is_not_exempt():
    tree = sqlglot.parse_one("SELECT count(phone) AS cnt FROM customers")
    aliases = _safe_aggregate_aliases(tree)
    assert aliases["cnt"] is False


def test_an_expression_or_concatenation_is_not_exempt():
    tree = sqlglot.parse_one("SELECT phone || '-' || account_no AS total_count FROM customers")
    aliases = _safe_aggregate_aliases(tree)
    assert aliases["total_count"] is False
    _columns, sanitized, _warnings = _sanitize_rows(
        [{"total_count": "13800001111-6222000012345678"}], safe_aggregate_aliases=aliases)
    assert sanitized == [{}]

def test_a_subquery_count_alias_does_not_exempt_the_outer_sensitive_projection():
    """N01/BF01 trigger A: an inner ``COUNT(*) AS cnt`` must not lend its exemption outward."""
    tree = sqlglot.parse_one(
        "SELECT phone AS cnt FROM customers WHERE EXISTS (SELECT COUNT(*) AS cnt FROM customers)"
    )
    aliases = _safe_aggregate_aliases(tree)
    assert aliases["cnt"] is False
    columns, sanitized, warnings = _sanitize_rows(
        [{"cnt": "13800001111"}], safe_aggregate_aliases=aliases
    )
    assert columns == [] and sanitized == [{}]
    assert warnings, "the sensitive value must be removed and reported"


def test_a_sensitive_column_concatenated_with_count_is_not_exempt():
    """N01/BF01 trigger B: the whole expression decides, not only the aggregate's arguments."""
    tree = sqlglot.parse_one(
        "SELECT phone || '-' || CAST(COUNT(*) AS TEXT) AS cnt FROM customers GROUP BY phone"
    )
    aliases = _safe_aggregate_aliases(tree)
    assert aliases["cnt"] is False
    _columns, sanitized, _warnings = _sanitize_rows(
        [{"cnt": "13800001111-3"}], safe_aggregate_aliases=aliases
    )
    assert sanitized == [{}]


def test_a_union_arm_with_a_sensitive_projection_cancels_the_shared_alias_exemption():
    tree = sqlglot.parse_one(
        "SELECT count(*) AS cnt FROM customers UNION ALL SELECT phone AS cnt FROM customers"
    )
    aliases = _safe_aggregate_aliases(tree)
    assert aliases["cnt"] is False


def test_plain_aggregates_keep_their_exemption_after_the_n01_fix():
    for sql in (
        "SELECT count(*) AS cnt FROM customers",
        "SELECT SUM(n) AS cnt FROM sample",
        "SELECT CAST(COUNT(*) AS TEXT) AS cnt FROM customers",
    ):
        aliases = _safe_aggregate_aliases(sqlglot.parse_one(sql))
        assert aliases["cnt"] is True, sql

def test_an_unaliased_sensitive_column_is_still_removed_by_name():
    rows_by_name = [{"mobile": "13800001111", "客户姓名": "张三"}]
    columns, sanitized, warnings = _sanitize_rows(rows_by_name)
    assert columns == [] and sanitized == [{}]
    assert {"mobile", "客户姓名"} <= SENSITIVE_FIELD_NAMES
    assert warnings, "removing sensitive fields must be reported"


def test_an_unverified_dialect_is_refused_instead_of_rendered_as_postgres():
    executor = SafeSqlExecutor()
    for dialect in ("oracle", "sqlserver", "db2"):
        try:
            executor.validate_and_prepare("SELECT n FROM sample", max_rows=2, dialect=dialect)
        except ValueError as exc:
            assert "not supported" in str(exc)
        else:  # pragma: no cover - the guard must fire
            raise AssertionError(f"{dialect} must not be rendered as PostgreSQL")


def test_the_connector_matrix_no_longer_claims_safe_query_where_it_is_unverified():
    by_engine = {item["engine_type"]: item for item in CONNECTORS}
    for engine in ("oracle", "sqlserver", "db2"):
        assert by_engine[engine]["safe_query"] is False, engine
        assert by_engine[engine].get("safe_query_note"), engine
    for engine in ("postgresql", "mysql_compatible", "sqlite"):
        assert by_engine[engine]["safe_query"] is True, engine


def test_the_forced_limit_helper_still_caps_rendered_sql():
    """Kept for compatibility: it must also apply the AST limit, not a regex."""
    executor = SafeSqlExecutor()
    rendered = executor._force_limit("SELECT n FROM sample WHERE n IN (SELECT n FROM sample LIMIT 1)",
                                     max_rows=2)
    assert _outer_limit(rendered) == 2
