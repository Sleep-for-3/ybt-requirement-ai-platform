"""Frozen historical schema used by the Alembic migration chain.

The migration chain must never depend on ``app.models``: a migration has to
describe the schema of *its own date*, not the schema of whatever the working
tree happens to contain when it is executed.  ``app.schema_freeze.data`` holds
the metadata that really existed in the commit that introduced every historical
revision (reconstructed from git history), and this package turns that data
into real SQLAlchemy tables at migration time.
"""

from app.schema_freeze.runtime import (
    FROZEN_REVISIONS,
    build_table,
    create_frozen_table,
    create_frozen_tables,
    drop_frozen_tables,
    frozen_table_names,
    frozen_table_names_until,
)

__all__ = [
    "FROZEN_REVISIONS",
    "build_table",
    "create_frozen_table",
    "create_frozen_tables",
    "drop_frozen_tables",
    "frozen_table_names",
    "frozen_table_names_until",
]
