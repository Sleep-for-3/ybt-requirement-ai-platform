from __future__ import annotations

import os
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa


BACKEND_DIR = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "202607300014"
LEGACY_SEMANTIC_REVISION = "202608200015"
SEMANTIC_REVISION = "202608200016"


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
    migration = (BACKEND_DIR / "alembic" / "versions" / f"{SEMANTIC_REVISION}_semantic_concept_versions.py").read_text(encoding="utf-8")
    assert "Base.metadata" not in migration
    assert "from app" not in migration
    assert "drop_table(\"embedding_index_versions\")" not in migration


def test_semantic_version_migration_bootstraps_one_v1_per_legacy_concept_and_downgrades_safely(tmp_path: Path) -> None:
    database_path = tmp_path / "semantic-version-bootstrap.db"
    _run_alembic(database_path, "upgrade", LEGACY_SEMANTIC_REVISION)
    engine = sa.create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(sa.text(
            "INSERT INTO projects (name, project_status, confidentiality_level, governance_workflow_enabled) "
            "VALUES (:name, 'active', 'internal', 0)"
        ), {"name": "legacy semantic project"})
        project_id = connection.execute(sa.text("SELECT id FROM projects ORDER BY id DESC LIMIT 1")).scalar_one()
        connection.execute(sa.text(
            "INSERT INTO semantic_concepts "
            "(project_id, concept_type, concept_code, concept_name, aliases_json, status, confidence_level, "
            "version, source_type, created_at, updated_at) "
            "VALUES (:project_id, 'business_term', :code, :name, :aliases, 'confirmed', 'high', :version, 'manual', :created_at, :updated_at)"
        ), [
            {
                "project_id": project_id, "code": "LEGACY_ONE", "name": "历史口径一",
                "aliases": json.dumps(["旧口径"]), "version": 1,
                "created_at": datetime(2026, 1, 15), "updated_at": datetime(2026, 1, 15),
            },
            {
                "project_id": project_id, "code": "LEGACY_EDITED", "name": "历史多次编辑口径",
                "aliases": json.dumps([]), "version": 7,
                "created_at": datetime(2026, 2, 20), "updated_at": datetime(2026, 2, 20),
            },
        ])

    _run_alembic(database_path, "upgrade", "head")
    with engine.connect() as connection:
        rows = connection.execute(sa.text(
            "SELECT semantic_concept_id, version_no, effective_from, provenance_json "
            "FROM semantic_concept_versions ORDER BY semantic_concept_id"
        )).mappings().all()
        assert len(rows) == 2
        assert [row["version_no"] for row in rows] == [1, 1]
        assert [row["effective_from"] for row in rows] == ["2026-01-15", "2026-02-20"]
        provenance = [json.loads(row["provenance_json"]) if isinstance(row["provenance_json"], str) else row["provenance_json"] for row in rows]
        assert [item["source"] for item in provenance] == ["legacy_concept_bootstrap", "legacy_concept_bootstrap"]
        assert all(item["legacy_concept_id"] == row["semantic_concept_id"] for item, row in zip(provenance, rows))

    _run_alembic(database_path, "downgrade", LEGACY_SEMANTIC_REVISION)
    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    assert "semantic_concept_versions" not in tables
    assert {"semantic_concepts", "semantic_bindings", "semantic_relations", "embedding_index_versions"} <= tables


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
