"""Run the PostgreSQL migration matrix on a disposable database.

The release gate for R1 requires evidence that the migration chain works on a
real PostgreSQL server, not only on SQLite:

* empty database -> ``head``;
* production baseline (``202608290021``) -> ``head``;
* ``head`` -> baseline -> ``head`` (rollback rehearsal);
* full teardown (``downgrade base``) -> ``head`` again;
* ``upgrade head`` on an already migrated database (no-op / idempotent);
* every state that ends ``at head`` must satisfy the ORM contract (no missing
  table or column, no nullability drift); a downgraded intermediate state only
  has to be reachable, because it legitimately lacks the objects that later
  revisions add.

The script creates its own throw-away database and drops it again, so it never
touches application data.

Usage (inside the development container)::

    cd /workspace/backend
    python /workspace/scripts/migration/verify_migration_matrix.py \
        --admin-url postgresql+psycopg://ybt:ybtdev@ybt-dev-pg:5432/postgres \
        --report /workspace/docs/upgrade/R1-迁移矩阵报告.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa


BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
PRODUCTION_BASELINE = "202608290021"
BOOKKEEPING_TABLES = {"alembic_version", "structured_requirement_snapshot_migration_state"}

_TYPE_ALIASES = {
    "VARCHAR": "STRING",
    "CHARACTER VARYING": "STRING",
    "TEXT": "TEXT",
    "INTEGER": "INTEGER",
    "BIGINT": "BIGINT",
    "SMALLINT": "SMALLINT",
    "BOOLEAN": "BOOLEAN",
    "JSON": "JSON",
    "JSONB": "JSON",
    "TIMESTAMP": "DATETIME",
    "TIMESTAMP WITH TIME ZONE": "DATETIME",
    "DATE": "DATE",
    "TIME": "TIME",
    "NUMERIC": "NUMERIC",
    "DOUBLE PRECISION": "FLOAT",
    "REAL": "FLOAT",
    "FLOAT": "FLOAT",
    "BYTEA": "LARGEBINARY",
}


def _normalise_type(type_name: str) -> str:
    base = type_name.split("(")[0].strip().upper()
    return _TYPE_ALIASES.get(base, base)


def _database_url(admin_url: str, database: str) -> str:
    return f"{admin_url.rsplit('/', 1)[0]}/{database}"


def _run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["DATABASE_URL"] = database_url
    environment["AUTH_MODE"] = "optional"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
    )


def _orm_metadata():
    sys.path.insert(0, str(BACKEND_DIR))
    from app import models  # noqa: F401
    from app.core.database import Base

    return Base.metadata


def _inspect(database_url: str) -> tuple[dict, list[str], str]:
    metadata = _orm_metadata()
    engine = sa.create_engine(database_url)
    problems: list[str] = []
    fingerprint_lines: list[str] = []
    try:
        inspector = sa.inspect(engine)
        database_tables = set(inspector.get_table_names())
        model_tables = set(metadata.tables)
        problems.extend(sorted(f"missing table: {name}" for name in model_tables - database_tables))
        problems.extend(
            sorted(
                f"unexpected table: {name}"
                for name in database_tables - model_tables - BOOKKEEPING_TABLES
            )
        )
        for table in sorted(model_tables & database_tables):
            columns = {column["name"]: column for column in inspector.get_columns(table)}
            for column in metadata.tables[table].columns:
                if column.name not in columns:
                    problems.append(f"missing column: {table}.{column.name}")
                    continue
                reflected = columns[column.name]
                if not column.primary_key and bool(reflected["nullable"]) != bool(column.nullable):
                    problems.append(
                        f"nullability drift: {table}.{column.name} "
                        f"(orm nullable={bool(column.nullable)}, db nullable={bool(reflected['nullable'])})"
                    )
                model_type = _normalise_type(str(column.type))
                database_type = _normalise_type(str(reflected["type"]))
                if model_type != database_type and {model_type, database_type} != {"STRING", "TEXT"}:
                    problems.append(
                        f"type drift: {table}.{column.name} (orm={model_type}, db={database_type})"
                    )
            for column in sorted(columns):
                fingerprint_lines.append(
                    f"{table}.{column}:{_normalise_type(str(columns[column]['type']))}"
                    f":{bool(columns[column]['nullable'])}"
                )
        with engine.connect() as connection:
            revision = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        engine.dispose()
    fingerprint = hashlib.sha256("\n".join(sorted(fingerprint_lines)).encode("utf-8")).hexdigest()
    return {"tables": len(database_tables), "revision": revision}, problems, fingerprint


def _create_database(admin_url: str, database: str) -> None:
    engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        connection.execute(sa.text(f'CREATE DATABASE "{database}"'))
    engine.dispose()


def _drop_database(admin_url: str, database: str) -> None:
    engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
    engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--admin-url",
        default=os.environ.get(
            "MIGRATION_MATRIX_ADMIN_URL", "postgresql+psycopg://ybt:ybtdev@ybt-dev-pg:5432/postgres"
        ),
    )
    parser.add_argument("--report", type=Path)
    parser.add_argument("--keep", action="store_true", help="keep the disposable database for debugging")
    args = parser.parse_args()

    database = f"ybt_matrix_{dt.datetime.now().strftime('%Y%m%d%H%M%S')}"
    database_url = _database_url(args.admin_url, database)
    print(f"ephemeral database: {database}")

    steps: list[dict] = []
    failures: list[str] = []

    def record(
        label: str, arguments: tuple[str, ...], *, at_head: bool, expect_success: bool = True
    ) -> None:
        result = _run_alembic(database_url, *arguments)
        entry = {
            "step": label,
            "command": "alembic " + " ".join(arguments),
            "exit_code": result.returncode,
        }
        if result.returncode != 0:
            entry["error"] = (result.stderr or result.stdout).strip().splitlines()[-1:] or [""]
            failures.append(f"{label}: exit {result.returncode}")
        steps.append(entry)
        print(f"  {label}: exit={result.returncode}")
        if expect_success and result.returncode != 0:
            raise SystemExit(f"step {label!r} failed:\n{result.stderr}")
        state, problems, fingerprint = _inspect(database_url)
        entry["revision"] = state["revision"]
        entry["table_count"] = state["tables"]
        entry["at_head"] = at_head
        # A downgraded database intentionally lacks the objects that later
        # revisions add, so the ORM contract only applies to head states.
        entry["contract_problems"] = problems if at_head else []
        if at_head:
            entry["schema_fingerprint"] = fingerprint
            if problems:
                failures.append(f"{label}: {len(problems)} contract problems")
        else:
            entry["schema_fingerprint"] = None
        return None

    try:
        _create_database(args.admin_url, database)
        record("空库 -> head", ("upgrade", "head"), at_head=True)
        record("head -> 202608290021（降级演练）", ("downgrade", PRODUCTION_BASELINE), at_head=False)
        record("202608290021 -> head（存量库升级）", ("upgrade", "head"), at_head=True)
        record("head -> head（幂等）", ("upgrade", "head"), at_head=True)
        record("head -> base（完全拆除）", ("downgrade", "base"), at_head=False)
        record("base -> head（重建）", ("upgrade", "head"), at_head=True)
    finally:
        if args.keep:
            print(f"kept database: {database}")
        else:
            _drop_database(args.admin_url, database)

    fingerprints = {step["schema_fingerprint"] for step in steps if step.get("schema_fingerprint")}
    head_steps = [step for step in steps if step.get("at_head")]
    if len(fingerprints) > 1:
        failures.append(f"head 状态之间结构指纹不一致：{len(fingerprints)} 个不同取值")

    lines = [
        "# R1 迁移矩阵报告（真实 PostgreSQL）",
        "",
        f"日期：{dt.date.today().isoformat()}",
        f"数据库：临时库 `{database}`（运行后已删除）",
        f"服务端：`{args.admin_url.rsplit('@', 1)[-1]}`",
        "",
        "## 步骤",
        "",
        "| 步骤 | 命令 | 退出码 | 版本 | 表数 | 是否 head | 契约问题 |",
        "|---|---|---|---|---|---|---|",
    ]
    for step in steps:
        lines.append(
            f"| {step['step']} | `{step['command']}` | {step['exit_code']} | "
            f"{step.get('revision')} | {step.get('table_count')} | "
            f"{'是' if step.get('at_head') else '否'} | {len(step.get('contract_problems') or [])} |"
        )
    lines.append("")
    lines.append("## 结论")
    lines.append("")
    if failures:
        lines.append("未通过：")
        lines.extend(f"- {item}" for item in failures)
    else:
        lines.append("全部步骤退出码为 0。")
        lines.append(
            f"{len(head_steps)} 个 head 状态均满足 ORM 契约（无缺表、无缺列、无类型/可空性漂移），"
            f"且结构指纹完全一致：`{sorted(fingerprints)[0]}`。"
        )
        lines.append("降级中间态（202608290021 / base）不适用 ORM 契约，仅用于验证可回滚。")
    lines.append("")
    report = "\n".join(lines)

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
        print(f"wrote {args.report}")
    print(report)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
