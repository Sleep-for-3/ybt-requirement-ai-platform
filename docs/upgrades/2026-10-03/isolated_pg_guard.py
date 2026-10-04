"""N13 isolation guard for the destructive PostgreSQL acceptance scripts.

The 2026-10-03 acceptance scripts run ``Base.metadata.drop_all`` / ``create_all``
(or insert rows) against whatever ``--database`` they are handed.  A mistyped or
copy-pasted argument could therefore wipe the schema of a real database.  This
module makes the "only touch my own throw-away database" claim *enforced by
code*, not by documentation.

Every destructive script must call :func:`require_isolated_target` **before** it
opens the connection that performs DDL or writes rows.

Rules (all automatic; no CLI flag can switch them off):

* the database name must carry an isolation prefix and a run marker;
* it must not be the configured business database (``backend/.env``
  ``DATABASE_URL``), nor a server/system database;
* the server must be loopback (these are local acceptance scripts);
* a pre-existing, non-empty database is refused unless the caller explicitly
  opted in (``allow_existing=True`` for scripts that only add their own rows);
* the run emits a JSON record of the target it created/used.

Importing this module has no side effects.

Tests: ``backend/tests/test_isolated_script_guard.py`` covers the pure name rules
and the refusal-before-DDL behaviour with a stubbed server probe.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

# Prefixes reserved for throw-away acceptance targets.
ISOLATED_PREFIXES = ("ybt_upgrade_", "ybt_iso_", "w10_iso_")

# ``<prefix><marker>``; the marker must start with a letter/digit and is lower-case.
ISOLATED_NAME_RE = re.compile(
    r"^(?P<prefix>" + "|".join(ISOLATED_PREFIXES) + r")(?P<marker>[a-z0-9][a-z0-9_]{0,47})$"
)

# Names that must never be a destructive target, whatever the caller passes.
RESERVED_DATABASES = frozenset(
    {"postgres", "template0", "template1", "ybt_dsh_handoff_v2"}
)

# The scripts are local acceptance tools: only loopback is accepted.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", ""})


class IsolationError(SystemExit):
    """Raised when a destructive script targets an unsafe database.

    Subclasses ``SystemExit`` so an uncaught raise aborts the script with a
    non-zero status *before* any DDL runs.
    """

    def __init__(self, message: str) -> None:
        super().__init__(f"[N13 isolation guard] REFUSED: {message}")


def _env_database_name(repo_root: Path | None = None) -> str | None:
    """Return the database name configured in ``backend/.env`` (no app import)."""
    root = repo_root or Path(__file__).resolve().parents[3]
    env_path = root / "backend" / ".env"
    try:
        text = env_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("DATABASE_URL"):
            continue
        _, _, value = line.partition("=")
        name = value.strip().rsplit("/", 1)[-1].split("?", 1)[0].strip()
        if name:
            return name
    return None


def validate_isolated_name(database: str, *, business_name: str | None = None) -> str:
    """Pure name check. Returns the normalised name or raises :class:`IsolationError`."""
    name = (database or "").strip()
    if not name:
        raise IsolationError("empty --database; a dedicated throw-away database is required")
    if name != database:
        raise IsolationError(f"database name {database!r} has surrounding whitespace")
    lowered = name.lower()
    configured = (business_name if business_name is not None else _env_database_name()) or ""
    if lowered in RESERVED_DATABASES:
        raise IsolationError(
            f"{name!r} is a reserved/system/business database; the business database is never a target"
        )
    if configured and lowered == configured.lower():
        raise IsolationError(
            f"{name!r} is the database configured in backend/.env; refuse to run destructive DDL on it"
        )
    match = ISOLATED_NAME_RE.match(lowered)
    if not match:
        raise IsolationError(
            f"{name!r} does not look like a throw-away target; use one of the prefixes "
            f"{', '.join(ISOLATED_PREFIXES)} plus a run marker (e.g. ybt_upgrade_w02_iso)"
        )
    if not match.group("marker"):
        raise IsolationError(f"{name!r} is missing a run marker after the isolation prefix")
    if lowered != name and name.lower() != name:
        raise IsolationError(f"{name!r} must be lower-case")
    return name


def _server_reports_existing_non_empty(
    *, host: str, port: int, user: str, password: str, database: str
) -> bool:
    """True when the target already exists and holds at least one user table.

    Uses a short-lived SQLAlchemy engine against the maintenance database so the
    target itself is never opened for DDL before this check.
    """
    from sqlalchemy import create_engine, text  # imported lazily: keeps import side-effect free

    admin_url = f"postgresql+psycopg://{user}:{password}@{host}:{port}/postgres"
    engine = create_engine(admin_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": database}
            ).scalar()
            if not exists:
                return False
    finally:
        engine.dispose()

    target_url = f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database}"
    engine = create_engine(target_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            count = conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema NOT IN ('pg_catalog', 'information_schema')"
                )
            ).scalar()
            return bool(count)
    finally:
        engine.dispose()


def require_isolated_target(
    database: str,
    *,
    script: str,
    host: str = "127.0.0.1",
    port: int = 5432,
    user: str = "postgres",
    password: str | None = None,
    allow_existing: bool = False,
    probe: Callable[..., bool] | None = None,
    emit: bool = True,
) -> dict[str, Any]:
    """Validate the target database and refuse unsafe ones before any DDL.

    ``probe`` is injectable for tests; it defaults to
    :func:`_server_reports_existing_non_empty`.
    """
    if host not in LOOPBACK_HOSTS:
        raise IsolationError(f"host {host!r} is not loopback; local acceptance scripts stay on 127.0.0.1")

    name = validate_isolated_name(database)

    resolved_password = password if password is not None else ""
    if not resolved_password:
        import os

        resolved_password = os.environ.get("PGPASSWORD") or ""
    if not resolved_password:
        raise IsolationError("PGPASSWORD is not set; cannot verify the target database")

    check = probe or _server_reports_existing_non_empty
    if check(host=host, port=port, user=user, password=resolved_password, database=name):
        if not allow_existing:
            raise IsolationError(
                f"database {name!r} already exists and is not empty; refusing drop_all/create_all on it"
            )

    record = {
        "script": script,
        "database": name,
        "isolation_prefix": next(p for p in ISOLATED_PREFIXES if name.startswith(p)),
        "host": host,
        "port": port,
        "user": user,
        "existing_non_empty_target_allowed": bool(allow_existing),
    }
    if emit:
        print(json.dumps({"n13_isolated_target": record}, ensure_ascii=False), file=sys.stderr)
    return record


__all__ = [
    "ISOLATED_PREFIXES",
    "IsolationError",
    "require_isolated_target",
    "validate_isolated_name",
]
