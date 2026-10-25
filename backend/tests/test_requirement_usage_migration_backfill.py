"""存量数据上加“非空 JSON 列”的迁移行为（离线、sqlite 文件库）。

背景：本轮给三张**已可能存有数据**的表新增了 JSON 列，并且按 ORM 契约把列声明为
`nullable=False`（ORM 侧 `Mapped[dict]/Mapped[list]` + `default=dict/list`）：

- `template_versions.parse_report_json`（迁移 202611010002）
- `requirement_generation_items.usage_json`（迁移 202611010004）
- `embedding_records.vector_record_ids_json`（迁移 202611010005）

如果只测“空库 upgrade head”，就测不到真正危险的情形：**表里已经有行**时执行
`ALTER TABLE ... ADD COLUMN ... NOT NULL DEFAULT`。本文件先停在新增列之前，插入一行，
再 upgrade，断言存量行拿到默认空值（而不是 NULL 或迁移失败）。
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
HASH64 = "a" * 64


def _alembic(database: Path, *arguments: str) -> None:
    env = dict(
        os.environ,
        PYTHONPATH=".",
        DATABASE_URL=f"sqlite:///{database.as_posix()}",
        AUTH_MODE="optional",
        ENVIRONMENT="test",
    )
    env.pop("TEST_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"alembic {' '.join(arguments)} failed:\n{result.stdout}\n{result.stderr}"


def _fetch(database: Path, query: str) -> list[tuple]:
    with sqlite3.connect(database) as connection:
        return connection.execute(query).fetchall()


def _column(database: Path, table: str, column: str) -> tuple:
    rows = _fetch(database, f"PRAGMA table_info('{table}')")
    for row in rows:
        if row[1] == column:
            return row
    raise AssertionError(f"{table}.{column} 不存在：{[row[1] for row in rows]}")


@pytest.fixture()
def database(tmp_path: Path) -> Path:
    return tmp_path / "backfill.db"


def test_template_versions_existing_row_gets_empty_report(database: Path) -> None:
    _alembic(database, "upgrade", "202611010001")
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO template_versions
                (template_document_id, project_id, version_no, template_code,
                 file_name, file_type, storage_path, file_hash)
            VALUES (1, 1, 1, 'EAST_CUSTOMER', 't.xlsx', 'xlsx', '/tmp/t.xlsx', ?)
            """,
            (HASH64,),
        )
    _alembic(database, "upgrade", "head")

    column = _column(database, "template_versions", "parse_report_json")
    assert column[3] == 1, "parse_report_json 应当是非空列"
    rows = _fetch(database, "SELECT parse_report_json FROM template_versions")
    assert rows == [("{}",)], rows


def test_generation_items_existing_row_gets_empty_usage(database: Path) -> None:
    _alembic(database, "upgrade", "202611010003")
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO requirement_generation_items (input_id, field_id, section, status)
            VALUES (1, 1, 'business', 'pending')
            """
        )
    _alembic(database, "upgrade", "head")

    column = _column(database, "requirement_generation_items", "usage_json")
    assert column[3] == 1, "usage_json 应当是非空列"
    rows = _fetch(database, "SELECT usage_json FROM requirement_generation_items")
    assert rows == [("{}",)], rows


def test_embedding_records_existing_row_gets_empty_vector_ids(database: Path) -> None:
    _alembic(database, "upgrade", "202611010004")
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO embedding_records
                (project_id, knowledge_unit_id, embedding_provider, embedding_model,
                 vector_store_provider, vector_record_id, embedding_dimension,
                 content_hash, status)
            VALUES (1, 1, 'mock', 'mock-embedding', 'mock', 'rec-1', 3, ?, 'indexed')
            """,
            (HASH64,),
        )
    _alembic(database, "upgrade", "head")

    column = _column(database, "embedding_records", "vector_record_ids_json")
    assert column[3] == 1, "vector_record_ids_json 应当是非空列"
    rows = _fetch(database, "SELECT vector_record_ids_json FROM embedding_records")
    assert rows == [("[]",)], rows


def test_downgrade_from_head_removes_the_new_columns(database: Path) -> None:
    _alembic(database, "upgrade", "head")
    _alembic(database, "downgrade", "202611010001")

    columns = {row[1] for row in _fetch(database, "PRAGMA table_info('template_versions')")}
    assert "parse_report_json" not in columns
    columns = {row[1] for row in _fetch(database, "PRAGMA table_info('requirement_generation_items')")}
    assert "usage_json" not in columns
    columns = {row[1] for row in _fetch(database, "PRAGMA table_info('embedding_records')")}
    assert "vector_record_ids_json" not in columns
