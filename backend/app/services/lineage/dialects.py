"""Resolve caller-supplied SQL dialect names to a grammar sqlglot understands.

Script uploads carry a free-form ``dialect`` form field.  Banks in this project
speak GBase 8a (MySQL-compatible), Hive/Inceptor and a few RDBMS dialects, but
sqlglot only knows a subset of those names.  Passing an unknown name straight
through has two very different failure modes:

* :func:`app.services.lineage.sql_parser.parse_sql_lineage` catches the
  ``ValueError`` and reports ``parse_status="failed"`` — honest but useless.
* :func:`app.services.lineage.version_diff.compare_sql_versions` does **not**
  catch it, so uploading a second version of a GBase script used to raise a
  raw ``ValueError`` out of the ingestion service (HTTP 500) instead of
  degrading to "unattributed change".

This module maps known aliases (GBase -> mysql, Inceptor -> hive, ...) and
falls back to the generic grammar with an explicit warning for anything else,
so parsing degrades honestly and never invents a dialect.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot

#: Alias -> sqlglot dialect.  Keys are lower-cased and stripped.
_DIALECT_ALIASES: dict[str, str] = {
    "gbase": "mysql",
    "gbase8a": "mysql",
    "gbase_8a": "mysql",
    "gbase8s": "mysql",
    "gbase_s": "mysql",
    "mysql": "mysql",
    "mysql_compatible": "mysql",
    "mariadb": "mysql",
    "tidb": "mysql",
    "oceanbase": "mysql",
    "hive": "hive",
    "hiveql": "hive",
    "inceptor": "hive",
    "transwarp": "hive",
    "sparksql": "spark",
    "spark_sql": "spark",
    "postgres": "postgres",
    "postgresql": "postgres",
    "pg": "postgres",
    "greenplum": "postgres",
    "oracle": "oracle",
    "sqlserver": "tsql",
    "mssql": "tsql",
    "sql_server": "tsql",
    "db2": "db2",
    "sqlite": "sqlite",
    "clickhouse": "clickhouse",
    "duckdb": "duckdb",
}


@dataclass(frozen=True)
class DialectResolution:
    """Outcome of mapping one caller-supplied dialect name."""

    requested: str
    effective: str
    warning: str | None = None

    @property
    def degraded(self) -> bool:
        return bool(self.warning)


def resolve_dialect(raw: str | None) -> DialectResolution:
    """Return a dialect sqlglot can parse, plus a warning when it was unknown."""

    requested = (raw or "").strip()
    if not requested:
        return DialectResolution("", "")
    key = requested.lower()
    alias = _DIALECT_ALIASES.get(key, key)
    try:
        sqlglot.Dialect.get_or_raise(alias)
    except Exception:
        return DialectResolution(
            requested,
            "",
            f"Unsupported SQL dialect '{requested}' is parsed with the generic grammar; "
            "dialect-specific syntax may be reported as unparsed instead of being guessed.",
        )
    return DialectResolution(requested, alias)


def dialect_summary(resolution: DialectResolution) -> dict:
    """Stable JSON shape written into diff summaries and lineage warnings."""

    return {
        "requested": resolution.requested,
        "effective": resolution.effective,
        "degraded": resolution.degraded,
        "warning": resolution.warning,
    }
