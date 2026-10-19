"""④ audit hash chain: chaining, tamper detection, migration coverage."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.settings import get_settings
from app.models import AuditLog
from app.services.governance import (
    AuditChainVerification,
    audit_chain_scope,
    canonical_entry_payload,
    compute_entry_hash,
    record_audit,
    verify_audit_chain,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
CHAIN_REVISION = "202611010001"
PREVIOUS_REVISION = "202610060001"
TAIL_INDEX = "ix_audit_logs_chain_tail"


def _entries(db: Session, count: int = 3, institution_id: int | None = 1) -> list[AuditLog]:
    rows = [
        record_audit(
            db,
            action=f"action_{index}",
            resource_type="document",
            resource_id=index,
            institution_id=institution_id,
            project_id=7,
            actor_user_id=11,
            before={"step": index},
            after={"step": index + 1},
        )
        for index in range(count)
    ]
    db.commit()
    return rows


def test_chain_is_built_and_verifies(db_session: Session) -> None:
    rows = _entries(db_session, 4)

    assert rows[0].prev_hash is None
    assert all(row.entry_hash for row in rows)
    for previous, current in zip(rows, rows[1:]):
        assert current.prev_hash == previous.entry_hash

    result = verify_audit_chain(db_session)
    assert isinstance(result, AuditChainVerification)
    assert result.intact is True
    assert result.checked == 4
    assert result.chains_checked == 1
    assert result.first_broken_id is None
    assert result.affected_range is None
    assert result.as_dict()["break_ids"] == []


def test_digest_is_deterministic_and_covers_call_fields(db_session: Session) -> None:
    first = record_audit(db_session, action="export", resource_type="report", institution_id=5, after={"b": 1, "a": 2})
    db_session.commit()
    assert first.entry_hash == compute_entry_hash(
        canonical_entry_payload(
            action="export",
            resource_type="report",
            institution_id=5,
            after_summary={"a": 2, "b": 1},
        ),
        None,
    )

    # Key order must not leak into the digest: redaction sorts nothing, so the
    # canonical serializer is what makes the payload byte-stable.
    db_session.add(first.__class__(action="noop", resource_type="t"))
    same = canonical_entry_payload(action="x", resource_type="y", after_summary={"a": 1, "b": 2})
    reordered = canonical_entry_payload(action="x", resource_type="y", after_summary={"b": 2, "a": 1})
    assert same == reordered


def test_tampering_with_a_middle_row_is_detected(db_session: Session) -> None:
    rows = _entries(db_session, 4)
    victim = rows[2]
    victim.after_summary_json = {"step": "tampered"}
    db_session.commit()

    result = verify_audit_chain(db_session)
    assert result.intact is False
    assert result.first_broken_id == victim.id
    assert "entry_hash" in (result.first_broken_reason or "")
    # The break also propagates to every later row, because they were chained
    # to the replayed digest rather than to the stored one.
    assert victim.id in result.break_ids
    assert rows[3].id in result.break_ids
    assert result.affected_range is not None
    assert result.affected_range[0] == victim.id


def test_rewriting_a_stored_hash_is_detected(db_session: Session) -> None:
    rows = _entries(db_session, 3)
    rows[1].entry_hash = "0" * 64
    db_session.commit()

    result = verify_audit_chain(db_session)
    assert result.intact is False
    assert result.first_broken_id == rows[1].id


def test_a_stale_writer_is_reported_as_a_break(db_session: Session) -> None:
    """Concurrent/out-of-order writers cannot be serialized, only detected.

    ``record_audit`` never commits, nor takes a lock, so two sessions can read
    the same chain tail.  The design is therefore best-effort append plus
    detectable: whichever entry ends up with the lower id keeps the chain
    consistent, and the displaced one is reported by ``verify_audit_chain``.
    """

    rows = _entries(db_session, 3)
    stale = AuditLog(
        institution_id=1,
        action="stale",
        resource_type="document",
        result="success",
        prev_hash=rows[0].entry_hash,  # tail read before rows 1 and 2 landed
    )
    stale.entry_hash = compute_entry_hash(
        canonical_entry_payload(action="stale", resource_type="document", institution_id=1),
        stale.prev_hash,
    )
    db_session.add(stale)
    db_session.commit()

    result = verify_audit_chain(db_session)
    assert result.intact is False
    assert result.first_broken_id == stale.id
    assert "prev_hash" in (result.first_broken_reason or "")


def test_pending_rows_chain_before_flush(db_session: Session) -> None:
    """Rows queued in one session chain together without an explicit flush."""

    first = record_audit(db_session, action="one", resource_type="t", institution_id=2)
    second = record_audit(db_session, action="two", resource_type="t", institution_id=2)
    assert first.prev_hash is None
    assert second.prev_hash == first.entry_hash
    db_session.commit()

    assert verify_audit_chain(db_session).intact is True


def test_disabled_switch_writes_no_hash(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUDIT_CHAIN_ENABLED", "false")
    get_settings.cache_clear()
    try:
        log = record_audit(db_session, action="legacy", resource_type="t", institution_id=3, after={"a": 1})
        db_session.commit()
        assert log.prev_hash is None
        assert log.entry_hash is None
        # The remaining behaviour of record_audit is unchanged.
        assert log.action == "legacy"
        assert log.institution_id == 3
        assert log.after_summary_json == {"a": 1}
        assert log.result == "success"
        # ... and once re-enabled the chain restarts without a break.
        assert verify_audit_chain(db_session).intact is True
    finally:
        # Drop the override before clearing the cache: a Settings object built
        # from the disabled switch would otherwise leak into later tests.
        monkeypatch.delenv("AUDIT_CHAIN_ENABLED", raising=False)
        get_settings.cache_clear()

    resumed = record_audit(db_session, action="after", resource_type="t", institution_id=3)
    db_session.commit()
    assert resumed.prev_hash is None
    assert resumed.entry_hash is not None
    assert verify_audit_chain(db_session).intact is True


def test_chains_are_isolated_per_institution(db_session: Session) -> None:
    first = record_audit(db_session, action="a", resource_type="t", institution_id=1)
    other = record_audit(db_session, action="b", resource_type="t", institution_id=2)
    glob = record_audit(db_session, action="c", resource_type="t")
    db_session.commit()

    assert first.prev_hash is None
    assert other.prev_hash is None
    assert glob.prev_hash is None
    assert audit_chain_scope(None) != audit_chain_scope(1)

    everything = verify_audit_chain(db_session)
    assert everything.intact is True
    assert everything.checked == 3
    assert everything.chains_checked == 3

    scoped = verify_audit_chain(db_session, institution_id=1)
    assert scoped.checked == 1
    assert scoped.chains_checked == 1


def test_verify_chain_reports_the_first_break_in_range(db_session: Session) -> None:
    rows = _entries(db_session, 3)
    rows[0].result = "failure"
    db_session.commit()

    result = verify_audit_chain(db_session, limit=2)
    assert result.intact is False
    assert result.first_broken_id == rows[0].id
    assert result.checked == 2


def test_orm_declares_the_chain_columns_and_tail_index() -> None:
    table = AuditLog.__table__
    assert table.c.prev_hash.type.length == 64
    assert table.c.entry_hash.type.length == 64
    assert table.c.prev_hash.nullable is True
    assert table.c.entry_hash.nullable is True
    assert TAIL_INDEX in {index.name for index in table.indexes}


def _run_alembic(database: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["DATABASE_URL"] = f"sqlite:///{database}"
    environment["AUTH_MODE"] = "optional"
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed


@pytest.mark.parametrize(
    "steps",
    [
        (("upgrade", "head"),),
        (("upgrade", PREVIOUS_REVISION), ("upgrade", "head")),
        (("upgrade", "head"), ("downgrade", "-1"), ("upgrade", "head")),
    ],
    ids=["empty-to-head", "previous-to-head", "head-down-one-up"],
)
def test_audit_chain_migration_is_reversible(tmp_path: Path, steps: tuple[tuple[str, str], ...]) -> None:
    database = tmp_path / "audit-chain.db"
    for step in steps:
        _run_alembic(database, *step)

    inspector = sa.inspect(sa.create_engine(f"sqlite:///{database}"))
    columns = {column["name"]: column for column in inspector.get_columns("audit_logs")}
    assert columns["prev_hash"]["nullable"] is True
    assert columns["entry_hash"]["nullable"] is True
    assert TAIL_INDEX in {index["name"] for index in inspector.get_indexes("audit_logs")}

    with sa.create_engine(f"sqlite:///{database}").begin() as connection:
        head = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
    assert head == CHAIN_REVISION


def test_step_back_removes_the_chain_state(tmp_path: Path) -> None:
    database = tmp_path / "audit-chain-down.db"
    _run_alembic(database, "upgrade", "head")
    _run_alembic(database, "downgrade", PREVIOUS_REVISION)

    inspector = sa.inspect(sa.create_engine(f"sqlite:///{database}"))
    columns = {column["name"] for column in inspector.get_columns("audit_logs")}
    assert "prev_hash" not in columns
    assert "entry_hash" not in columns
    assert TAIL_INDEX not in {index["name"] for index in inspector.get_indexes("audit_logs")}


def test_the_chain_migration_uses_explicit_alembic_operations() -> None:
    text = (BACKEND_DIR / "alembic" / "versions" / f"{CHAIN_REVISION}_audit_log_chain.py").read_text(
        encoding="utf-8"
    )
    assert "op.add_column" in text
    assert "revision = " in text
    assert "from app" not in text
    assert "Base.metadata" not in text


def test_single_head_after_the_change() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1, f"expected exactly one alembic head, got {sorted(heads)}"
    assert heads[0] == CHAIN_REVISION


def test_audit_rows_created_without_the_helper_stay_readable(db_session: Session) -> None:
    """Legacy rows built directly (no record_audit) keep NULL hashes."""

    legacy = AuditLog(project_id=1, action="generate_business_draft", resource_type="x", result="success")
    db_session.add(legacy)
    db_session.commit()

    assert legacy.prev_hash is None
    assert legacy.entry_hash is None
    assert verify_audit_chain(db_session).intact is True
    assert db_session.scalars(select(AuditLog).where(AuditLog.id == legacy.id)).one() is legacy


def test_base_metadata_creates_the_columns() -> None:
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    columns = {column["name"] for column in sa.inspect(engine).get_columns("audit_logs")}
    assert {"prev_hash", "entry_hash"} <= columns
