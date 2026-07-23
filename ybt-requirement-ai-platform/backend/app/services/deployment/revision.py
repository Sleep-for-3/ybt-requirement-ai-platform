from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection


def database_revisions(connection: Connection) -> tuple[str | None, str | None]:
    """Return the database revision and repository head without exposing the database URL."""
    current = MigrationContext.configure(connection).get_current_revision()
    backend_root = Path(__file__).resolve().parents[3]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.set_main_option("path_separator", "os")
    return current, ScriptDirectory.from_config(config).get_current_head()
