import re

import sqlglot
from sqlglot import exp


class SafeSqlExecutor:
    """Validate read-only profiling SQL before any future database execution."""

    def __init__(self, default_limit: int = 200, timeout_seconds: int = 10) -> None:
        self.default_limit = default_limit
        self.timeout_seconds = timeout_seconds

    def validate_and_prepare(self, sql: str) -> str:
        normalized = sql.strip().rstrip(";")
        if not normalized:
            raise ValueError("SQL is empty")
        if not re.match(r"^\s*(select|with)\b", normalized, flags=re.IGNORECASE):
            raise ValueError("Only SELECT statements are allowed for profiling")

        tree = sqlglot.parse_one(normalized)
        if tree is None or not isinstance(tree, (exp.Select, exp.With)):
            raise ValueError("Only SELECT statements are allowed for profiling")
        if any(isinstance(node, exp.Star) for node in tree.walk()):
            raise ValueError("SELECT * is not allowed for profiling")

        prepared = tree.sql(dialect="postgres")
        if " LIMIT " not in prepared.upper():
            prepared = f"{prepared} LIMIT {self.default_limit}"
        return prepared

    def profile_field(self, table_name: str, field_name: str) -> dict:
        query = self.validate_and_prepare(
            f"select count({field_name}) as non_null_count, "
            f"count(distinct {field_name}) as distinct_count "
            f"from {table_name}"
        )
        return {
            "status": "reserved",
            "safe_sql": query,
            "timeout_seconds": self.timeout_seconds,
            "note": "MVP only validates profiling SQL and does not connect to bank databases.",
        }
