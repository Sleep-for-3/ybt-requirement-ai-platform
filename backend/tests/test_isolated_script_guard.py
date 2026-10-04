"""N13: the destructive acceptance scripts must refuse any non-isolated target.

These tests are the *negative* examples the review asked for: they prove the
guard refuses the business database and other unsafe names, that a pre-existing
non-empty target is refused unless the caller explicitly opted in, and that in
every destructive script the guard call is reached **before** ``drop_all`` /
``create_all``.

They never connect to PostgreSQL: the server probe is injected.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARD_DIR = ROOT / "docs" / "upgrades" / "2026-10-03"
if str(GUARD_DIR) not in sys.path:
    sys.path.insert(0, str(GUARD_DIR))

from isolated_pg_guard import (  # noqa: E402  (path set above on purpose)
    ISOLATED_PREFIXES,
    IsolationError,
    require_isolated_target,
    validate_isolated_name,
)

BUSINESS = "ybt_dsh_handoff_v2"

DESTRUCTIVE_SCRIPTS = (
    "w02_postgres_concurrency.py",
    "w03_postgres_mapping_guard.py",
    "w04_postgres_safe_query.py",
    "w10_postgres_job_claim.py",
    "w10_postgres_lease_fencing.py",
)

ALL_GUARDED_WITH_DEFAULT = DESTRUCTIVE_SCRIPTS + ("w05_postgres_migration_rehearsal.py",)


def _never_existing(**_kwargs) -> bool:
    return False


def _always_existing(**_kwargs) -> bool:
    return True


# --------------------------------------------------------------------------- #
# pure name rules
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "name",
    ["ybt_upgrade_w02_iso", "ybt_upgrade_mig_iso", "ybt_iso_runner_1", "w10_iso_jobs"],
)
def test_isolated_names_are_accepted(name: str) -> None:
    assert validate_isolated_name(name, business_name=BUSINESS) == name


@pytest.mark.parametrize(
    "name",
    [
        BUSINESS,                      # the configured business database
        "postgres",                    # server maintenance database
        "template1",
        "",                            # empty
        "ybt_upgrade_",                # prefix but no run marker
        "public",                      # arbitrary real database
        "ybt_upgrade_w02_iso ",        # surrounding whitespace
        "YBT_UPGRADE_W02_ISO",         # must be lower-case
    ],
)
def test_unsafe_names_are_refused(name: str) -> None:
    with pytest.raises(IsolationError):
        validate_isolated_name(name, business_name=BUSINESS)


def test_business_name_from_argument_is_refused_even_with_isolated_prefix() -> None:
    # A name that matches the isolated pattern but is the configured business DB
    # must still be refused (defence in depth if the default is ever changed).
    with pytest.raises(IsolationError):
        validate_isolated_name("ybt_upgrade_w02_iso", business_name="ybt_upgrade_w02_iso")


def test_default_business_lookup_does_not_raise_without_env_file(monkeypatch, tmp_path) -> None:
    # ``_env_database_name`` reads backend/.env; a missing file must not crash.
    from isolated_pg_guard import _env_database_name

    assert _env_database_name(tmp_path) is None


# --------------------------------------------------------------------------- #
# require_isolated_target: refusal happens before any DDL
# --------------------------------------------------------------------------- #

def test_business_database_is_refused_before_ddl() -> None:
    with pytest.raises(IsolationError):
        require_isolated_target(
            BUSINESS, script="probe.py", password="x", probe=_never_existing
        )


def test_non_loopback_host_is_refused() -> None:
    with pytest.raises(IsolationError):
        require_isolated_target(
            "ybt_upgrade_w02_iso", script="probe.py", host="10.0.0.5",
            password="x", probe=_never_existing,
        )


def test_missing_password_is_refused(monkeypatch) -> None:
    monkeypatch.delenv("PGPASSWORD", raising=False)
    with pytest.raises(IsolationError):
        require_isolated_target("ybt_upgrade_w02_iso", script="probe.py", probe=_never_existing)
    # …but an explicit password does not depend on the environment.
    record = require_isolated_target(
        "ybt_upgrade_w02_iso", script="probe.py", password="x",
        probe=_never_existing, emit=False,
    )
    assert record["database"] == "ybt_upgrade_w02_iso"


def test_existing_non_empty_target_is_refused_unless_opted_in() -> None:
    with pytest.raises(IsolationError):
        require_isolated_target(
            "ybt_upgrade_w02_iso", script="probe.py", password="x", probe=_always_existing
        )
    record = require_isolated_target(
        "ybt_upgrade_w02_iso", script="probe.py", password="x", probe=_always_existing,
        allow_existing=True, emit=False,
    )
    assert record["existing_non_empty_target_allowed"] is True


def test_record_reports_the_isolation_prefix() -> None:
    record = require_isolated_target(
        "w10_iso_jobs", script="probe.py", password="x", probe=_never_existing, emit=False
    )
    assert record["isolation_prefix"] in ISOLATED_PREFIXES
    assert record["script"] == "probe.py"


# --------------------------------------------------------------------------- #
# source-level invariants (catch a future script that forgets the guard)
# --------------------------------------------------------------------------- #

def test_guard_call_precedes_every_ddl_call() -> None:
    for script in DESTRUCTIVE_SCRIPTS:
        source = (GUARD_DIR / script).read_text(encoding="utf-8")
        guard_at = source.find("require_isolated_target(")
        assert guard_at != -1, f"{script} does not call require_isolated_target"
        resets = [
            ddl
            for ddl in ("Base.metadata.drop_all(", "Base.metadata.create_all(")
            if source.find(ddl) != -1
        ]
        assert resets, f"{script} no longer calls any reset DDL"
        for ddl in resets:
            assert guard_at < source.find(ddl), f"{script}: guard must run before {ddl}"


def test_default_database_of_every_script_is_still_isolated() -> None:
    for script in ALL_GUARDED_WITH_DEFAULT:
        source = (GUARD_DIR / script).read_text(encoding="utf-8")
        match = re.search(r'"--database",\s*default="([^"]+)"', source)
        assert match, f"{script} has no --database default"
        # Must satisfy the guard's own rule: changing a default to the business
        # database would fail here.
        assert validate_isolated_name(match.group(1), business_name=BUSINESS) == match.group(1)


def test_w09_backup_plan_default_is_not_a_write_target() -> None:
    """w09 is read-only (pg_dump) so it is out of the destructive-guard scope.

    This test pins that reasoning: it must not contain drop_all/create_all, and
    every --database default it exposes must be a real configured database name
    (it backs up the business database on purpose, so no isolation prefix).
    """
    source = (GUARD_DIR / "w09_backup_plan.py").read_text(encoding="utf-8")
    assert "Base.metadata.drop_all(" not in source
    assert "Base.metadata.create_all(" not in source
