"""W02 / B05: one refresh token must rotate exactly once, atomically.

The original defect issued the replacement (create_session committed internally) and only then
revoked the original, with no lock or conditional update. Two concurrent requests carrying the
same refresh token could therefore both succeed, and a failure while issuing the replacement
could leave extra active tokens behind.

These tests run on SQLite and cover the deterministic interleaving, replay and rollback
semantics. The true multi-connection concurrency check runs against an isolated PostgreSQL
database in docs/upgrades/2026-10-03/w02-postgres-concurrency.md.
"""
from __future__ import annotations

import threading

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import RefreshToken, User
from app.services.auth import authentication
from app.services.auth.authentication import (
    AuthenticationError,
    create_session,
    rotate_refresh_token,
)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A file-backed SQLite so independent sessions see the same rows."""
    url = "sqlite:///" + (tmp_path / "refresh-rotation.db").as_posix()
    engine = create_engine(url, connect_args={"check_same_thread": False})
    from app.core.database import Base

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        user = User(username="rotate_user", display_name="Rotate", status="active")
        db.add(user)
        db.commit()
        user_id = int(user.id)
    yield factory, user_id
    engine.dispose()


def _active_replacements(factory, user_id: int) -> int:
    with factory() as db:
        return int(db.scalar(select(func.count(RefreshToken.id)).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )) or 0)


def test_a_rotated_token_cannot_be_rotated_again(env):
    factory, user_id = env
    with factory() as db:
        user = db.get(User, user_id)
        original = str(create_session(db, user)["refresh_token"])

    with factory() as db:
        replacement = rotate_refresh_token(db, original)
        assert replacement["refresh_token"] and replacement["refresh_token"] != original

    # Replay of the already-consumed original must fail and must not mint a second successor.
    with factory() as db:
        with pytest.raises(AuthenticationError):
            rotate_refresh_token(db, original)
    assert _active_replacements(factory, user_id) == 1


def test_concurrent_rotations_of_one_token_yield_exactly_one_success(env):
    """Independent sessions racing on the same token: the conditional claim lets one win."""
    factory, user_id = env
    with factory() as db:
        user = db.get(User, user_id)
        original = str(create_session(db, user)["refresh_token"])

    successes: list[str] = []
    failures: list[Exception] = []
    barrier = threading.Barrier(8)

    def attempt() -> None:
        barrier.wait()
        with factory() as db:
            try:
                result = rotate_refresh_token(db, original)
            except Exception as exc:  # noqa: BLE001 - the losers are expected to fail
                failures.append(exc)
            else:
                successes.append(str(result["refresh_token"]))

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(successes) == 1, f"expected exactly one successful rotation, got {len(successes)}"
    assert len(failures) == len(threads) - 1
    assert _active_replacements(factory, user_id) == 1


def test_a_failure_while_issuing_the_replacement_rolls_the_rotation_back(env, monkeypatch):
    factory, user_id = env
    with factory() as db:
        user = db.get(User, user_id)
        original = str(create_session(db, user)["refresh_token"])

    def boom(*args, **kwargs):
        raise RuntimeError("token issuance failed")

    monkeypatch.setattr(authentication, "create_session", boom)
    with factory() as db:
        with pytest.raises(RuntimeError):
            rotate_refresh_token(db, original)

    # The original token was not consumed and no partial successor is left active.
    assert _active_replacements(factory, user_id) == 1
    with factory() as db:
        stored = db.scalar(select(RefreshToken).where(RefreshToken.revoked_at.is_(None)))
        assert stored is not None and stored.replaced_by_jti is None
    monkeypatch.undo()

    # Recovery: the same token can still be rotated afterwards.
    with factory() as db:
        result = rotate_refresh_token(db, original)
        assert result["refresh_token"]
    assert _active_replacements(factory, user_id) == 1


def test_a_disabled_user_does_not_consume_the_token(env):
    factory, user_id = env
    with factory() as db:
        user = db.get(User, user_id)
        original = str(create_session(db, user)["refresh_token"])
        user.status = "disabled"
        db.commit()

    with factory() as db:
        with pytest.raises(AuthenticationError):
            rotate_refresh_token(db, original)

    with factory() as db:
        stored = db.scalar(select(RefreshToken).where(RefreshToken.token_jti.is_not(None),
                                                      RefreshToken.revoked_at.is_(None)))
        assert stored is not None, "a rejected rotation must not consume the token"


def test_a_tampered_token_is_rejected_without_consuming_the_real_one(env):
    factory, user_id = env
    with factory() as db:
        user = db.get(User, user_id)
        original = str(create_session(db, user)["refresh_token"])

    tampered = original[:-3] + ("aaa" if not original.endswith("aaa") else "bbb")
    with factory() as db:
        with pytest.raises(AuthenticationError):
            rotate_refresh_token(db, tampered)
    assert _active_replacements(factory, user_id) == 1

    with factory() as db:
        assert rotate_refresh_token(db, original)["refresh_token"]
