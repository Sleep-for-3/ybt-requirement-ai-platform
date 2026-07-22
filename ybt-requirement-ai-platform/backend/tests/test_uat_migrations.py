from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest
import sqlalchemy as sa


BACKEND_DIR = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "202607200010"
UAT_REVISION = "202607220011"


def _run_alembic(database_path: Path, *arguments: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    completed = subprocess.run([sys.executable, "-m", "alembic", *arguments], cwd=BACKEND_DIR, env=environment, capture_output=True, text=True, timeout=90)
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize("commands", [
    (("upgrade", "head"),),
    (("upgrade", PREVIOUS_REVISION), ("upgrade", "head")),
    (("upgrade", "head"), ("downgrade", "-1"), ("upgrade", "head")),
], ids=["empty-to-head", "010-to-head", "head-down-one-up"])
def test_uat_migration_is_deterministic_and_reversible(tmp_path: Path, commands: tuple[tuple[str, str], ...]) -> None:
    database_path = tmp_path / "uat-migration.db"
    for command in commands:
        _run_alembic(database_path, *command)
    inspector = sa.inspect(sa.create_engine(f"sqlite:///{database_path.as_posix()}"))
    assert {"uat_suites", "uat_cases", "uat_runs", "uat_case_results", "uat_findings", "uat_signoffs", "uat_packs", "uat_pack_items"} <= set(inspector.get_table_names())
    assert {"project_id", "uat_run_id", "signoff_role", "signoff_status"} <= {column["name"] for column in inspector.get_columns("uat_signoffs")}


def test_uat_revision_uses_explicit_alembic_operations() -> None:
    text = (BACKEND_DIR / "alembic" / "versions" / f"{UAT_REVISION}_uat_productization.py").read_text(encoding="utf-8")
    assert "op.create_table" in text
    assert "Base.metadata" not in text
    assert "from app" not in text
