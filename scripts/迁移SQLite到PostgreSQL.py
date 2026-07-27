"""Copy application data from a SQLite database into an Alembic-initialized PostgreSQL database."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import Connection

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

import app.models  # noqa: E402,F401
from app.core.database import Base

ALEMBIC_SEED_TABLES = frozenset({"prompt_template_versions", "workflow_definitions"})


def populated_target_tables(
    target_url: str,
    *,
    ignored_tables: frozenset[str] = ALEMBIC_SEED_TABLES,
) -> list[str]:
    if not target_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ValueError("Target database must be PostgreSQL")
    engine = create_engine(target_url, pool_pre_ping=True)
    target_tables = set(inspect(engine).get_table_names())
    populated = []
    with engine.connect() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name in ignored_tables or table.name not in target_tables:
                continue
            if connection.scalar(select(func.count()).select_from(table)):
                populated.append(table.name)
    engine.dispose()
    return populated


def migrate(
    source_path: Path,
    target_url: str,
    *,
    batch_size: int = 1000,
    replace_target: bool = False,
) -> dict[str, int]:
    source_path = source_path.resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite source database not found: {source_path}")
    if not target_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ValueError("Target database must be PostgreSQL")
    if batch_size < 1:
        raise ValueError("Batch size must be positive")

    source_engine = create_engine(f"sqlite:///{source_path.as_posix()}")
    target_engine = create_engine(target_url, pool_pre_ping=True)
    source_tables = set(inspect(source_engine).get_table_names())
    target_tables = set(inspect(target_engine).get_table_names())
    application_tables = [
        table
        for table in Base.metadata.sorted_tables
        if table.name in source_tables and table.name in target_tables
    ]
    if not application_tables:
        raise RuntimeError("No application tables are shared by source and target databases")

    copied: dict[str, int] = {}
    with source_engine.connect() as source, target_engine.connect() as target:
        try:
            target.execute(text("SET session_replication_role = replica"))
            _prepare_target(target, application_tables, replace_target)
            for table in application_tables:
                count = _copy_table(source, target, table, batch_size)
                copied[table.name] = count
                print(f"{table.name}: {count}")
            _reset_sequences(target, application_tables)
            target.execute(text("SET session_replication_role = origin"))
            target.commit()
        except Exception:
            target.rollback()
            target.execute(text("SET session_replication_role = origin"))
            target.commit()
            raise
    source_engine.dispose()
    target_engine.dispose()
    return copied


def _prepare_target(connection: Connection, tables, replace_target: bool) -> None:
    populated = []
    for table in tables:
        if connection.scalar(select(func.count()).select_from(table)):
            populated.append(table.name)
    if populated and not replace_target:
        raise RuntimeError(
            "PostgreSQL target already contains application data: "
            + ", ".join(populated[:10])
        )
    if replace_target:
        quoted = ", ".join(
            connection.dialect.identifier_preparer.quote(table.name)
            for table in reversed(tables)
        )
        connection.exec_driver_sql(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE")


def _copy_table(
    source: Connection,
    target: Connection,
    table,
    batch_size: int,
) -> int:
    result = source.execution_options(stream_results=True).execute(select(table))
    count = 0
    while True:
        rows = result.fetchmany(batch_size)
        if not rows:
            break
        target.execute(table.insert(), [dict(row._mapping) for row in rows])
        count += len(rows)
    return count


def _reset_sequences(connection: Connection, tables) -> None:
    for table in tables:
        primary_keys = list(table.primary_key.columns)
        if len(primary_keys) != 1:
            continue
        column = primary_keys[0]
        sequence = connection.scalar(
            text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
            {"table_name": table.name, "column_name": column.name},
        )
        if not sequence:
            continue
        maximum = connection.scalar(select(func.max(column))) or 0
        connection.execute(
            text(
                "SELECT setval(CAST(:sequence AS regclass), :value, :is_called)"
            ),
            {
                "sequence": sequence,
                "value": max(int(maximum), 1),
                "is_called": bool(maximum),
            },
        )
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--replace-target", action="store_true")
    parser.add_argument("--inspect-target", action="store_true")
    args = parser.parse_args()
    target_url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    if args.inspect_target:
        print(json.dumps(populated_target_tables(target_url)))
        return
    if args.source is None:
        parser.error("--source is required unless --inspect-target is used")
    copied = migrate(
        args.source,
        target_url,
        batch_size=args.batch_size,
        replace_target=args.replace_target,
    )
    print(f"Migration completed: {sum(copied.values())} rows across {len(copied)} tables")


if __name__ == "__main__":
    main()
