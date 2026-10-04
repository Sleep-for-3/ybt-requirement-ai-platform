"""W05 migration rehearsal on real PostgreSQL: upgrade, verify, downgrade, upgrade again.

The migration was previously covered by ORM/schema-freeze tests on SQLite, which cannot show that
the DDL lands on PostgreSQL. This rehearses it on a dedicated throw-away database so the release
step (``alembic upgrade head``) is proven before anyone points it at the business database.

Safety: it only ever touches the database named by ``--database`` (default ``ybt_upgrade_mig_iso``),
refuses to run when the resolved target is not that database, never prints credentials, and leaves
the business databases untouched. It does not drop anything.

Usage (from ``ai-platform/backend``):

    $env:PGPASSWORD = (Get-Content C:\\Users\\admin\\dsh-pg18\\.admin-pw.txt -Raw).Trim()
    .venv\\Scripts\\python.exe ..\\docs\\upgrades\\2026-10-03\\w05_postgres_migration_rehearsal.py
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
PG_BIN = Path(r"C:\Users\admin\dsh-pg18\pgsql\bin")
REVISION = "202610030001"
PREVIOUS = "202610020051"
NEW_COLUMNS = ("lease_owner", "lease_expires_at")
NEW_INDEX = "ix_background_jobs_lease_expires_at"


def _psql(database: str, statement: str) -> str:
    completed = subprocess.run(
        [str(PG_BIN / "psql.exe"), "-h", "127.0.0.1", "-U", "postgres", "-d", database,
         "-tAc", statement],
        capture_output=True, text=True, env=os.environ, check=False,
    )
    return completed.stdout.strip()


def _alembic(args: list[str], env: dict[str, str]) -> str:
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True, text=True, env=env, cwd=str(BACKEND), check=False,
    )
    return (completed.stdout + completed.stderr).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="ybt_upgrade_mig_iso")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    args = parser.parse_args()

    password = os.environ.get("PGPASSWORD") or ""
    if not password:
        print(json.dumps({"ok": False, "error": "PGPASSWORD is not set"}, ensure_ascii=False))
        return 2
    if args.database not in {"ybt_upgrade_mig_iso", "ybt_upgrade_w02_iso"}:
        print(json.dumps({"ok": False, "error": f"refusing to rehearse against {args.database!r}"},
                         ensure_ascii=False))
        return 2

    env = {**os.environ,
           "DATABASE_URL": f"postgresql+psycopg://{args.user}:{password}@{args.host}:{args.port}/{args.database}"}

    # Safety: prove the settings actually resolved to the isolated database before running any DDL.
    probe = subprocess.run(
        [sys.executable, "-c",
         "from sqlalchemy import make_url;from app.core.settings import get_settings;"
         "print(make_url(str(get_settings().database_url)).database)"],
        capture_output=True, text=True, env=env, cwd=str(BACKEND), check=False,
    ).stdout.strip()
    if probe != args.database:
        print(json.dumps({"ok": False, "error": f"resolved target is {probe!r}, refusing to continue"},
                         ensure_ascii=False))
        return 2

    up1 = _alembic(["upgrade", "head"], env)
    current1 = _alembic(["current"], env)
    columns_up = _psql(args.database, "select count(*) from information_schema.columns "
                                      "where table_name='background_jobs' and column_name in "
                                      "('lease_owner','lease_expires_at')")
    index_up = _psql(args.database, "select count(*) from pg_indexes where tablename='background_jobs' "
                                    f"and indexname='{NEW_INDEX}'")

    down = _alembic(["downgrade", "-1"], env)
    current2 = _alembic(["current"], env)
    columns_down = _psql(args.database, "select count(*) from information_schema.columns "
                                        "where table_name='background_jobs' and column_name in "
                                        "('lease_owner','lease_expires_at')")
    index_down = _psql(args.database, "select count(*) from pg_indexes where tablename='background_jobs' "
                                      f"and indexname='{NEW_INDEX}'")

    up2 = _alembic(["upgrade", "head"], env)
    current3 = _alembic(["current"], env)

    result = {
        "ok": (REVISION in current1 and PREVIOUS in current2 and REVISION in current3
               and columns_up == "2" and index_up == "1"
               and columns_down == "0" and index_down == "0"),
        "database": args.database,
        "upgrade_reached_head": REVISION in current1,
        "columns_present_after_upgrade": int(columns_up or 0),
        "index_present_after_upgrade": int(index_up or 0),
        "downgrade_returned_to": current2.split()[0] if current2 else None,
        "columns_after_downgrade": int(columns_down or 0),
        "index_after_downgrade": int(index_down or 0),
        "reupgrade_returned_to": current3.split()[0] if current3 else None,
        "downgrade_logged": "Running downgrade" in down,
        "reupgrade_logged": "Running upgrade" in up2,
        "business_databases_touched": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
