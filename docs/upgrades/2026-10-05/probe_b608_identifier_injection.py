"""Triage probe for the bandit B608 findings on identifier interpolation.

Bandit flags string-built SQL. "Possible" is not "exploitable", so this probe tests the actual
boundary: the interpolated ``{table}`` / ``{field}`` reach ``SafeSqlExecutor.validate_and_prepare``,
which parses with sqlglot and enforces SELECT-only. The question is whether a crafted identifier can
escape that guard (multiple statements, DDL/DML, or a second result set).

Each case is classified as:
  * BLOCKED  - the guard rejected it (the finding is not exploitable through this path)
  * ESCAPED  - the guard accepted a statement that is not the intended single-column profile
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

from app.services.db.safe_sql_executor import SafeSqlExecutor  # noqa: E402

# Attack shapes an attacker could put into a "field name" or "table name" text box.
CASES = [
    ("statement chaining", "1) from t; drop table users; --", "t"),
    ("comment out tail", "1) from other_table --", "t"),
    ("union injection", "1) from t union select password from users --", "t"),
    ("subquery escape", "1) from (select 1) x --", "t"),
    ("ddl via field", "1); truncate table users; --", "t"),
    ("table drops tail", "t; drop table users", "1"),
    ("table with union", "t union select 1", "1"),
    ("star projection", "*", "t"),
    ("writable cte", "1) from (with x as (delete from users returning 1) select 1) y --", "t"),
    ("benign control", "amount", "orders"),
]


def main() -> int:
    executor = SafeSqlExecutor()
    escaped = 0
    for label, field_name, table_name in CASES:
        sql = (
            f"select count({field_name}) as non_null_count, "
            f"count(distinct {field_name}) as distinct_count from {table_name}"
        )
        try:
            prepared = executor.validate_and_prepare(sql)
            verdict = "ESCAPED"
            detail = prepared[:90]
            escaped += 1
        except Exception as exc:  # noqa: BLE001 - the guard's refusal is the expected outcome
            verdict = "BLOCKED"
            detail = f"{type(exc).__name__}: {str(exc)[:70]}"
        print(f"{verdict:8} | {label:18} | {detail}")

    print()
    print(f"cases={len(CASES)} escaped={escaped} blocked={len(CASES) - escaped}")
    print("REACHABLE_VIA_THIS_PATH=" + ("yes" if escaped > 1 else "no"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
