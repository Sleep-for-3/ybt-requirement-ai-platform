"""Incremental migration contract; no existing database is opened."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_reverse_batch_and_uat_migrations_preserve_existing_rows():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        metadata = sa.MetaData()
        for name in ("projects", "users", "requirements", "requirement_revisions", "resource_import_batches", "uat_suites"):
            table = sa.Table(name, metadata, sa.Column("id", sa.Integer(), primary_key=True),
                sa.Column("legacy_marker", sa.String(40)))
        metadata.create_all(connection)
        for table in metadata.tables.values():
            connection.execute(table.insert().values(id=1, legacy_marker="preserve-user-data"))
        with Operations.context(MigrationContext.configure(connection)):
            for name in ("202609180036_requirement_script_batches.py", "202609180037_requirement_uat_links.py",
                         "202609180038_requirement_rechecks.py"):
                spec = importlib.util.spec_from_file_location(name[:-3], Path(__file__).parents[1] / "alembic" / "versions" / name)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.upgrade()
        inspector = sa.inspect(connection)
        for name, expected in (("requirement_script_batches", {"uq_requirement_script_batch_request"}),
                               ("requirement_uat_links", {"uq_requirement_uat_revision", "uq_requirement_uat_suite"}),
                               ("requirement_rechecks", {"uq_requirement_recheck_change"})):
            assert expected <= {c["name"] for c in inspector.get_unique_constraints(name)}
            assert inspector.get_foreign_keys(name)
        for table in metadata.tables.values():
            assert connection.execute(sa.select(table.c.legacy_marker)).scalar_one() == "preserve-user-data"
    engine.dispose()
