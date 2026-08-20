from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa


BACKEND_DIR = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "202607300014"
SEMANTIC_REVISION = "202608200015"


def test_semantic_migration_upgrade_downgrade_cycle(tmp_path: Path) -> None:
    database_path = tmp_path / "semantic-migration.db"
    _run_alembic(database_path, "upgrade", "head")
    _assert_semantic_schema(database_path)

    _run_alembic(database_path, "downgrade", PREVIOUS_REVISION)
    inspector = sa.inspect(sa.create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert "semantic_concepts" not in inspector.get_table_names()
    assert "embedding_index_versions" in inspector.get_table_names()

    _run_alembic(database_path, "upgrade", "head")
    _assert_semantic_schema(database_path)


def test_semantic_revision_is_additive_and_runtime_model_free() -> None:
    migration = (BACKEND_DIR / "alembic" / "versions" / f"{SEMANTIC_REVISION}_regulatory_semantic_layer.py").read_text(encoding="utf-8")
    assert "Base.metadata" not in migration
    assert "from app" not in migration
    assert "drop_table(\"embedding_index_versions\")" not in migration


def _run_alembic(database_path: Path, *arguments: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments], cwd=BACKEND_DIR, env=environment,
        capture_output=True, text=True, timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _assert_semantic_schema(database_path: Path) -> None:
    inspector = sa.inspect(sa.create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert {"semantic_concepts", "semantic_bindings", "semantic_relations"} <= set(inspector.get_table_names())
    concept_uniques = {item["name"] for item in inspector.get_unique_constraints("semantic_concepts")}
    relation_uniques = {item["name"] for item in inspector.get_unique_constraints("semantic_relations")}
    assert "uq_semantic_concept_project_type_code" in concept_uniques
    assert "uq_semantic_relation_triple" in relation_uniques
