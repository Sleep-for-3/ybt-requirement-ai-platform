"""Exercise additive migrations on an isolated SQLite predecessor schema."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


def test_generation_migrations_upgrade_from_revision_predecessor():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        metadata = sa.MetaData()
        for name in ("projects", "users", "requirements", "stored_files", "workflow_instances"):
            sa.Table(name, metadata, sa.Column("id", sa.Integer(), primary_key=True))
        sa.Table("requirement_deliveries", metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("requirement_id", sa.Integer()),
            sa.Column("requirement_version", sa.Integer()),
            sa.Column("content_hash", sa.String(64)))
        metadata.create_all(connection)
        with Operations.context(MigrationContext.configure(connection)):
            for filename in ("202609140029_requirement_revisions.py", "202609140030_requirement_generation_inputs.py",
                             "202609140031_requirement_generation_items.py",
                             "202609140032_requirement_review_delivery.py"):
                path = Path(__file__).parents[1] / "alembic" / "versions" / filename
                spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.upgrade()
        inspector = sa.inspect(connection)
        for table, constraint in (("requirement_revisions", "uq_requirement_content_version"),
                                  ("requirement_generation_inputs", "uq_requirement_generation_input_key"),
                                  ("requirement_generation_items", "uq_requirement_generation_item"),
                                  ("requirement_deliveries", "uq_requirement_draft_snapshot"),
                                  ("requirement_review_submissions", "uq_requirement_review_revision"),
                                  ("requirement_formal_deliveries", "uq_requirement_formal_review")):
            assert constraint in {item["name"] for item in inspector.get_unique_constraints(table)}
        assert "lease_until" in {column["name"] for column in inspector.get_columns("requirement_generation_items")}
    engine.dispose()
