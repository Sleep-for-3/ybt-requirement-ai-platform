"""Release gates for a reproducible migration chain.

Revision ``202607070001`` used to call ``Base.metadata.create_all()``.  A fresh
installation therefore received the schema of *the working tree* while every
later revision silently became a no-op.  These tests lock the replacement:
table definitions come from ``app.schema_freeze`` (reconstructed from git
history) and the resulting schema must still satisfy the ORM contract.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.core.database import Base
from app.schema_freeze import FROZEN_REVISIONS
from app.schema_freeze import data as frozen_data
from app import models as _models  # noqa: F401  - populates Base.metadata


BACKEND_DIR = Path(__file__).resolve().parents[1]
VERSIONS_DIR = BACKEND_DIR / "alembic" / "versions"

# Tables that only exist for migration bookkeeping, not for the application.
BOOKKEEPING_TABLES = {"alembic_version", "structured_requirement_snapshot_migration_state"}

PRODUCTION_BASELINE_REVISION = "202608290021"


def _dotted(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _orm_dependencies(source: str) -> set[str]:
    """Code-level (not comment-level) usage of the live ORM inside a migration."""

    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app.models"):
                    found.add(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("app.models"):
                found.add(f"from {module} import ...")
            elif module == "app" and any(alias.name == "models" for alias in node.names):
                found.add("from app import models")
        elif isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Name) and function.id == "globals":
                found.add("globals()")
        elif isinstance(node, ast.Attribute):
            dotted = _dotted(node)
            if dotted.startswith("Base.metadata"):
                found.add("Base.metadata")
            if dotted == "Base.metadata.create_all":
                found.add("Base.metadata.create_all")
    return found


def _migration_chain() -> dict[str, str | None]:
    """revision -> down_revision, read straight from the migration files."""

    chain: dict[str, str | None] = {}
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        revision = down_revision = None
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            if target.id == "revision" and isinstance(node.value, ast.Constant):
                revision = node.value.value
            elif target.id == "down_revision" and isinstance(node.value, ast.Constant):
                down_revision = node.value.value
        if revision:
            chain[revision] = down_revision
    return chain


def _chain_head() -> str:
    chain = _migration_chain()
    parents = {value for value in chain.values() if value}
    heads = sorted(revision for revision in chain if revision not in parents)
    assert len(heads) == 1, f"expected exactly one migration head, found {heads}"
    return heads[0]


def test_no_migration_uses_the_live_orm_metadata() -> None:
    offenders: dict[str, list[str]] = {}
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        hits = sorted(_orm_dependencies(path.read_text(encoding="utf-8")))
        if hits:
            offenders[path.name] = hits
    assert offenders == {}, (
        "migration files must describe their own historical schema instead of "
        f"reading the current models: {offenders}"
    )


def test_frozen_schema_data_matches_the_migration_chain() -> None:
    assert isinstance(frozen_data.CREATED_BY_REVISION, dict)
    assert tuple(frozen_data.CREATED_BY_REVISION) == FROZEN_REVISIONS

    owner: dict[str, str] = {}
    for revision in FROZEN_REVISIONS:
        for table in frozen_data.CREATED_BY_REVISION[revision]:
            assert table in frozen_data.TABLES, f"{table} has no frozen definition"
            assert table not in owner, f"{table} is frozen twice ({owner.get(table)} and {revision})"
            owner[table] = revision

    chain = _migration_chain()
    for index, revision in enumerate(FROZEN_REVISIONS):
        assert revision in chain, f"frozen revision {revision} has no migration file"
        expected_parent = FROZEN_REVISIONS[index - 1] if index else None
        assert chain[revision] == expected_parent, f"{revision} is not chained to {expected_parent}"


def _run_alembic(database: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["DATABASE_URL"] = f"sqlite:///{database}"
    environment["AUTH_MODE"] = "optional"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"alembic {' '.join(arguments)} failed:\n{result.stdout}\n{result.stderr}"
    return result


def _assert_matches_orm_contract(database: Path) -> None:
    engine = sa.create_engine(f"sqlite:///{database}")
    try:
        inspector = sa.inspect(engine)
        database_tables = set(inspector.get_table_names())
        model_tables = set(Base.metadata.tables)

        assert model_tables - database_tables == set(), "migrated schema is missing ORM tables"
        assert database_tables - model_tables <= BOOKKEEPING_TABLES, (
            "migrated schema created tables that the ORM does not know about"
        )

        for table in sorted(model_tables):
            database_columns = {column["name"]: column for column in inspector.get_columns(table)}
            for column in Base.metadata.tables[table].columns:
                assert column.name in database_columns, f"{table}.{column.name} is missing"
                if column.primary_key:
                    continue
                assert bool(database_columns[column.name]["nullable"]) == bool(column.nullable), (
                    f"{table}.{column.name} nullability differs from the ORM contract"
                )
    finally:
        engine.dispose()


def test_fresh_install_then_downgrade_then_upgrade(tmp_path: Path) -> None:
    database = tmp_path / "fresh.db"
    _run_alembic(database, "upgrade", "head")
    _assert_matches_orm_contract(database)

    engine = sa.create_engine(f"sqlite:///{database}")
    with engine.connect() as connection:
        head = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
    engine.dispose()
    assert head == _chain_head()

    # An existing installation is upgraded from the production baseline; a
    # downgrade must be replayable because the release rollback relies on it.
    _run_alembic(database, "downgrade", PRODUCTION_BASELINE_REVISION)
    _run_alembic(database, "upgrade", "head")
    _assert_matches_orm_contract(database)
