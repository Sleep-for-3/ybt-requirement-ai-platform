from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa


BACKEND_DIR = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "202607150009"
DELIVERABLE_REVISION = "202607200010"


def _run_alembic(database_path: Path, *arguments: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _assert_deliverable_schema(database_path: Path) -> None:
    inspector = sa.inspect(sa.create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert "deliverable_packages" in inspector.get_table_names()
    assert "deliverable_package_versions" in inspector.get_table_names()

    package_columns = {column["name"] for column in inspector.get_columns("deliverable_packages")}
    assert {
        "generation_job_id",
        "render_job_id",
        "generation_fingerprint",
        "render_fingerprint",
    } <= package_columns

    version_columns = {column["name"] for column in inspector.get_columns("deliverable_package_versions")}
    assert {
        "workflow_instance_id",
        "review_snapshot_hash",
        "review_submission_hash",
    } <= version_columns

    constraints = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("deliverable_package_versions")
    }
    assert constraints["uq_deliverable_package_version"] == ("deliverable_package_id", "version_no")
    assert constraints["uq_deliverable_package_workflow"] == ("deliverable_package_id", "workflow_instance_id")
    assert constraints["uq_deliverable_package_review_snapshot"] == (
        "deliverable_package_id",
        "review_snapshot_hash",
    )


@pytest.mark.parametrize(
    "migration_path",
    [
        ("upgrade", "head"),
        ("upgrade", PREVIOUS_REVISION, "upgrade", "head"),
        ("upgrade", "head", "downgrade", "-1", "upgrade", "head"),
        ("upgrade", "head", "downgrade", PREVIOUS_REVISION, "upgrade", "head"),
    ],
    ids=["empty-to-head", "009-to-head", "head-down-one-up", "head-down-to-009-up"],
)
def test_deliverable_migration_paths_are_reversible_and_deterministic(
    tmp_path: Path,
    migration_path: tuple[str, ...],
) -> None:
    database_path = tmp_path / "migration.db"
    for command, revision in zip(migration_path[::2], migration_path[1::2], strict=True):
        _run_alembic(database_path, command, revision)
        if command == "downgrade":
            inspector = sa.inspect(sa.create_engine(f"sqlite:///{database_path.as_posix()}"))
            if revision == PREVIOUS_REVISION:
                assert "deliverable_packages" not in inspector.get_table_names()
            else:
                assert revision == "-1"
                assert "deliverable_packages" in inspector.get_table_names()

    _assert_deliverable_schema(database_path)


def test_deliverable_revision_does_not_depend_on_runtime_models() -> None:
    migration = (BACKEND_DIR / "alembic" / "versions" / f"{DELIVERABLE_REVISION}_caliber_document_production.py").read_text(
        encoding="utf-8"
    )
    assert "Base.metadata" not in migration
    assert "from app" not in migration
    assert ".__table__" not in migration
