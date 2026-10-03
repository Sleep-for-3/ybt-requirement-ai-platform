"""W01 / B18: every component must report the same release identity.

Without this, a release can silently mix an old frontend with a new API/worker, and readiness
cannot prove which migration the database is actually on.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.services.version_info import UNKNOWN, app_commit, build_time, schema_head, version_report, versions_match

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def _client() -> Iterator[tuple[TestClient, sessionmaker]]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_the_version_endpoint_reports_the_release_identity():
    with _client() as (client, _factory):
        response = client.get("/api/version")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["component"] == "api"
        assert set(payload) >= {"component", "app_commit", "build_time", "schema_head", "image_digest"}
        assert "password" not in response.text.lower() and "secret" not in response.text.lower()


def test_environment_supplied_identity_is_reported(monkeypatch):
    monkeypatch.setenv("APP_COMMIT", "abc1234def")
    monkeypatch.setenv("BUILD_TIME", "2026-10-03T20:00:00+08:00")
    monkeypatch.setenv("SERVICE_COMPONENT", "worker")
    assert app_commit() == "abc1234def"
    assert build_time() == "2026-10-03T20:00:00+08:00"

    with _client() as (client, _factory):
        assert client.get("/api/version").json()["component"] == "worker"


def test_the_reported_schema_head_is_the_real_migration_head():
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert len(heads) == 1, f"expected exactly one alembic head, got {sorted(heads)}"

    class _Result:
        def scalar_one_or_none(self):
            return heads[0]

    class _Db:
        def execute(self, _statement):
            return _Result()

    assert schema_head(_Db()) == heads[0]


def test_a_missing_schema_table_does_not_break_the_probe():
    class _Db:
        def execute(self, _statement):
            raise RuntimeError("no such table: alembic_version")

    assert schema_head(_Db()) is None


def test_mixed_component_versions_are_detected():
    api = {"component": "api", "app_commit": "abc1234", "build_time": "t1", "schema_head": "202610030001"}
    worker = {"component": "worker", "app_commit": "abc1234", "build_time": "t1", "schema_head": "202610030001"}
    old_frontend = {"component": "frontend", "app_commit": "old9999", "build_time": "t0", "schema_head": "202610030001"}

    assert versions_match(api, worker) is True
    assert versions_match(api, old_frontend) is False
    assert versions_match(api) is True

    stale_schema = {"component": "worker", "app_commit": "abc1234", "build_time": "t1", "schema_head": "202610020051"}
    assert versions_match(api, stale_schema) is False


def test_unknown_identity_is_explicit_rather_than_empty(monkeypatch):
    monkeypatch.delenv("APP_COMMIT", raising=False)
    monkeypatch.delenv("BUILD_TIME", raising=False)
    monkeypatch.setattr("app.services.version_info._packaged_build_info", lambda: {})
    assert app_commit() == UNKNOWN
    assert build_time() == UNKNOWN

    # An unknown identity can never prove that two components agree.
    unknown_report = {"component": "api", "app_commit": UNKNOWN, "build_time": UNKNOWN,
                      "schema_head": "202610030001"}
    real_report = dict(unknown_report, app_commit="abc1234", build_time="t1")
    assert versions_match(unknown_report, real_report) is False
    assert versions_match(unknown_report, dict(unknown_report, component="worker")) is False
