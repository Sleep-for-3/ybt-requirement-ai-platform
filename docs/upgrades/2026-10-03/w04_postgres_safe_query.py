"""W04 acceptance: the safe-query contract against a real PostgreSQL server.

The unit tests prove the AST limit and the rejection rules on SQLite, where the server adds no
row-count semantics of its own. This script puts 50 real rows in PostgreSQL, then checks that a
query whose outer statement has no LIMIT still returns at most ``max_rows`` - even when a subquery,
a CTE or a string literal carries its own LIMIT - and that writes and multi-statements are refused
before any SQL reaches the server.

Safety: uses the dedicated throw-away database (default ``ybt_upgrade_w02_iso``), creates and drops
only its own table, never prints credentials, and never touches the business databases.

Usage (from ``ai-platform/backend``):

    $env:PGPASSWORD = (Get-Content C:\\Users\\admin\\dsh-pg18\\.admin-pw.txt -Raw).Trim()
    .venv\\Scripts\\python.exe ..\\docs\\upgrades\\2026-10-03\\w04_postgres_safe_query.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

TABLE = "w04_iso_rows"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="ybt_upgrade_w02_iso")
    parser.add_argument("--rows", type=int, default=50)
    parser.add_argument("--max-rows", type=int, default=5)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--allow-reset-existing", action="store_true",
                        help="N13: allow resetting an existing non-empty isolated DB (the business DB is always refused)")
    args = parser.parse_args()

    password = os.environ.get("PGPASSWORD") or ""
    if not password:
        print(json.dumps({"ok": False, "error": "PGPASSWORD is not set"}, ensure_ascii=False))
        return 2

    # N13: refuse any target that is not this run's throw-away isolated database, before any DDL.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from isolated_pg_guard import require_isolated_target

    require_isolated_target(
        args.database,
        script="w04_postgres_safe_query.py",
        host=args.host,
        port=args.port,
        user=args.user,
        password=password,
        allow_existing=args.allow_reset_existing,
    )
    url = f"postgresql+psycopg://{args.user}:{password}@{args.host}:{args.port}/{args.database}"
    os.environ["DATABASE_URL"] = url

    from sqlalchemy import create_engine, select, text
    from sqlalchemy.orm import sessionmaker

    from app.core.crypto import encrypt_secret
    from app.core.database import Base
    from app.models import DataSource, Institution, Project
    from app.services.db.safe_sql_executor import SafeSqlExecutor

    engine = create_engine(url, pool_size=5, max_overflow=5)
    Base.metadata.create_all(engine)

    # 50 real rows, so an unbounded query would return more than max_rows if the limit leaked.
    CUSTOMERS = "w04_iso_customers"
    SYNTHETIC_PHONE = "13800001111"
    SYNTHETIC_ACCOUNT = "6222000012345678"
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
        conn.execute(text(f"CREATE TABLE {TABLE} (n integer, marker text)"))
        for start in range(0, args.rows, 10):
            values = ", ".join(f"({i}, 'limit 1')" for i in range(start, min(start + 10, args.rows)))
            conn.execute(text(f"INSERT INTO {TABLE} (n, marker) VALUES {values}"))
        # N01: synthetic sensitive values plus a non-sensitive column to group by.
        conn.execute(text(f"DROP TABLE IF EXISTS {CUSTOMERS}"))
        conn.execute(text(f"CREATE TABLE {CUSTOMERS} (phone text, account_no text, n integer)"))
        conn.execute(
            text(
                f"INSERT INTO {CUSTOMERS} (phone, account_no, n) VALUES "
                f"('{SYNTHETIC_PHONE}', '{SYNTHETIC_ACCOUNT}', 1), "
                f"('{SYNTHETIC_PHONE}', '{SYNTHETIC_ACCOUNT}', 2)"
            )
        )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        # Idempotent: reuse the fixture rows if a previous run left them behind.
        institution = db.scalar(select(Institution).where(Institution.institution_code == "W04ISO"))
        if institution is None:
            institution = Institution(institution_code="W04ISO", institution_name="W04", institution_type="bank", status="active")
            db.add(institution); db.flush()
        project = db.scalar(select(Project).where(Project.name == "W04 iso"))
        if project is None:
            project = Project(name="W04 iso", institution_id=institution.id)
            db.add(project); db.flush()
        datasource = db.scalar(select(DataSource).where(DataSource.name == "w04_iso_ds"))
        if datasource is not None:
            # refresh the stored secret so a re-run can connect
            datasource.encrypted_password = encrypt_secret(password)
            db.commit()
        if datasource is None:
            datasource = DataSource(
                project_id=project.id, name="w04_iso_ds", db_type="postgresql",
                host=args.host, port=args.port, database_name=args.database, username=args.user,
                encrypted_password=encrypt_secret(password), connection_params_json={},
                readonly_flag=True, enabled=True,
            )
            db.add(datasource); db.commit()
        datasource_id = int(datasource.id)

    executor = SafeSqlExecutor(db=None, default_limit=args.max_rows, max_limit=args.max_rows, timeout_seconds=15)

    cases = {
        "plain": f"SELECT n FROM {TABLE}",
        "subquery_limit": f"SELECT n FROM {TABLE} WHERE n IN (SELECT n FROM {TABLE} LIMIT 1) OR n > 1",
        "string_limit": f"SELECT 'limit 1' AS marker, n FROM {TABLE}",
        "cte_limit": f"WITH recent AS (SELECT n FROM {TABLE} LIMIT 1) SELECT n FROM recent",
    }

    # N01/BF01: the aggregate exemption must be decided in the outer output scope, for the
    # whole projection. Both triggers previously returned the synthetic phone verbatim with
    # no warning; the plain COUNT control must keep its exemption.
    n01_cases = {
        "n01_subquery_alias": (
            f"SELECT phone AS cnt FROM {CUSTOMERS} "
            f"WHERE EXISTS (SELECT COUNT(*) AS cnt FROM {CUSTOMERS})"
        ),
        "n01_concat_count": (
            f"SELECT phone || '-' || CAST(COUNT(*) AS TEXT) AS cnt FROM {CUSTOMERS} GROUP BY phone"
        ),
        "n01_plain_count": f"SELECT COUNT(*) AS cnt FROM {CUSTOMERS}",
    }

    results: dict[str, object] = {}
    for name, sql in cases.items():
        with factory() as db:
            datasource = db.get(DataSource, datasource_id)
            response = executor.execute(
                datasource, sql, project_id=project.id, max_rows=args.max_rows,
                task_id=None, profile_task_id=None, created_by=None,
            )
        results[name] = {"status": response.status, "row_count": response.row_count,
                         "sanitized_sql": response.sanitized_sql}

    n01: dict[str, object] = {}
    for name, sql in n01_cases.items():
        with factory() as db:
            datasource = db.get(DataSource, datasource_id)
            response = executor.execute(
                datasource, sql, project_id=project.id, max_rows=args.max_rows,
                task_id=None, profile_task_id=None, created_by=None,
            )
        leaked = json.dumps(response.rows, ensure_ascii=False, default=str)
        n01[name] = {
            "status": response.status,
            "columns": list(response.columns or []),
            "rows": [dict(row) for row in (response.rows or [])],
            "warnings": list(response.warnings or []),
            "synthetic_phone_returned": SYNTHETIC_PHONE in leaked,
            "synthetic_account_returned": SYNTHETIC_ACCOUNT in leaked,
        }

    # The two triggers must not return the synthetic raw values and must warn; the plain
    # COUNT control must still be returned as a genuine statistic.
    n01_ok = (
        n01["n01_subquery_alias"]["synthetic_phone_returned"] is False
        and n01["n01_subquery_alias"]["warnings"]
        and n01["n01_concat_count"]["synthetic_phone_returned"] is False
        and n01["n01_concat_count"]["synthetic_account_returned"] is False
        and n01["n01_concat_count"]["warnings"]
        and n01["n01_plain_count"]["columns"] == ["cnt"]
        and n01["n01_plain_count"]["synthetic_phone_returned"] is False
    )
    # Refusals that must happen before any SQL reaches the server.
    refusals: dict[str, str] = {}
    for name, sql in {
        "insert": f"INSERT INTO {TABLE} (n, marker) VALUES (999, 'x')",
        "update": f"UPDATE {TABLE} SET marker = 'y'",
        "delete": f"DELETE FROM {TABLE}",
        "drop": f"DROP TABLE {TABLE}",
        "multi_statement": f"SELECT n FROM {TABLE}; DROP TABLE {TABLE}",
        "cte_write": f"WITH gone AS (DELETE FROM {TABLE} RETURNING n) SELECT n FROM gone",
        "select_star": f"SELECT * FROM {TABLE}",
    }.items():
        with factory() as db:
            datasource = db.get(DataSource, datasource_id)
            response = executor.execute(
                datasource, sql, project_id=project.id, max_rows=args.max_rows,
                task_id=None, profile_task_id=None, created_by=None,
            )
        refusals[name] = f"{response.status}:{response.reject_reason}"

    with engine.begin() as conn:
        actual_rows = int(conn.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one())
        conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
        conn.execute(text(f"DROP TABLE IF EXISTS {CUSTOMERS}"))

    capped = all(int(item["row_count"] or 0) <= args.max_rows for item in results.values())
    all_success = all(item["status"] == "success" for item in results.values())
    all_refused = all(value.startswith("rejected") for value in refusals.values())
    untouched = actual_rows == args.rows

    result = {
        "ok": capped and all_success and all_refused and untouched and n01_ok,
        "database": args.database,
        "rows_available": args.rows,
        "max_rows": args.max_rows,
        "queries": results,
        "refusals": refusals,
        "n01_aggregate_exemption": n01,
        "n01_ok": n01_ok,
        "table_row_count_unchanged": untouched,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    engine.dispose()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
