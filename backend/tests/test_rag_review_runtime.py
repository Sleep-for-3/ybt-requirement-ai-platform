"""Fresh runtime tooling must preserve existing processes, queues and secrets."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


@pytest.fixture
def runtime_tool(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "rag_review_environment_under_test", scripts / "rag_review_environment.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FreeSocket:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def settimeout(self, _timeout):
        pass

    def connect_ex(self, _address):
        return 111


def test_source_identity_includes_shared_hooks_but_excludes_private_runtime(
    tmp_path, monkeypatch, runtime_tool
):
    names = ['backend/app/main.py', 'frontend/hooks/useJobPolling.ts',
             'frontend/.env.local', '.local-run/environment.json']
    for name in names:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('synthetic source', encoding='utf-8')
    monkeypatch.setattr(runtime_tool, 'BACKEND', tmp_path / 'backend')
    monkeypatch.setattr(runtime_tool.subprocess, 'check_output',
        lambda command, **kwargs: ('\0'.join(names) if 'ls-files' in command else 'a' * 40).encode())
    first = runtime_tool.source_identity()
    assert set(first['code_files']) == set(names[:2])
    (tmp_path / names[1]).write_text('changed hook', encoding='utf-8')
    assert runtime_tool.source_identity()['code_hash'] != first['code_hash']
    before_private = runtime_tool.source_identity()['code_hash']
    (tmp_path / names[2]).write_text('different synthetic credential', encoding='utf-8')
    assert runtime_tool.source_identity()['code_hash'] == before_private


@pytest.mark.parametrize('frontend_port', [None, 18098])
@pytest.mark.parametrize('redis_port', [16389, 16390])
def test_new_runtime_separates_ports_queues_and_records_dirty_source(
    tmp_path, monkeypatch, runtime_tool, capsys, frontend_port, redis_port
):
    root = tmp_path / "new"
    previous = tmp_path / "old"
    environment = {
        "DATABASE_URL": "postgresql+psycopg://test:test@127.0.0.1:15439/rag_accept",
        "LLM_API_KEY_ENV_NAME": "RAG_TEST_KEY",
    }
    original = {
        "environment.json": environment,
        "deepseek-secret.json": {"key": "fake-private-key"},
        "state.json": {"username": "test-user", "password": "fake-password"},
    }
    monkeypatch.setattr(runtime_tool, "read_json", lambda path: dict(original[path.name]))
    monkeypatch.setattr(runtime_tool.socket, "socket", _FreeSocket)
    databases, calls, waits = [], [], []
    monkeypatch.setattr(runtime_tool, "ensure_empty_redis_databases",
                        lambda database, *, port: databases.append((database, port)))
    identity = {"git_head": "b" * 40, "code_hash": "a" * 64, "code_files": {"backend/app/main.py": "c" * 64}}
    monkeypatch.setattr(runtime_tool, "source_identity", lambda: identity)
    monkeypatch.setattr(
        runtime_tool, "spawn",
        lambda root, name, command, env, *args: calls.append((name, command, env)),
    )
    monkeypatch.setattr(runtime_tool, "wait_port", waits.append)
    budget_ledger = tmp_path / 'BUDGET.json'
    budget_state = tmp_path / 'provider-budget.sqlite3'
    from app.services.llm.provider_budget import ProviderBudget

    monkeypatch.setattr(ProviderBudget, 'refresh', lambda _self: None)

    runtime_tool.start(previous, root, port=18106, redis_database=6, redis_port=redis_port,
                       frontend_port=frontend_port, budget_ledger=budget_ledger, budget_state=budget_state)

    saved = json.loads((root / "environment.json").read_text(encoding="utf-8"))
    assert saved["CELERY_BROKER_URL"].endswith("/6")
    assert saved["CELERY_RESULT_BACKEND"].endswith("/7")
    assert saved["APP_COMMIT"] == "b" * 40 + "+worktree." + "a" * 12
    assert databases == [(6, redis_port)]
    assert saved['REDIS_URL'] == f'redis://127.0.0.1:{redis_port}/6'
    assert saved['CELERY_RESULT_BACKEND'] == f'redis://127.0.0.1:{redis_port}/7'
    assert saved['RAG_MODEL_BUDGET_REQUIRED'] == 'true'
    assert saved['RAG_MODEL_BUDGET_PATH'] == str(budget_ledger.resolve())
    assert saved['RAG_MODEL_BUDGET_STATE'] == str(budget_state.resolve())
    assert all(call[2]['RAG_MODEL_BUDGET_REQUIRED'] == 'true' for call in calls[:2])
    assert waits == ([18106] if frontend_port is None else [18106, frontend_port])
    assert calls[1][1][-1] == "18106"
    assert calls[0][2]["SERVICE_COMPONENT"] == "worker"
    assert calls[1][2]["SERVICE_COMPONENT"] == "api"
    assert all(call[2]["RAG_TEST_KEY"] == "fake-private-key" for call in calls[:2])
    if frontend_port:
        assert calls[2][2]['NEXT_PUBLIC_API_BASE_URL'] == 'http://127.0.0.1:18106/api'
        assert calls[2][2]['NEXT_DIST_DIR'] == '.next-verify-rag-18098'
        assert 'RAG_TEST_KEY' not in calls[2][2]
        assert saved['CORS_ORIGINS'] == 'http://127.0.0.1:18098'
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    assert state["backend_url"] == "http://127.0.0.1:18106"
    assert json.loads((root / "source-identity.json").read_text(encoding="utf-8"))["code_hash"] == "a" * 64
    output = capsys.readouterr().out
    assert "fake-private-key" not in output
    assert "fake-password" not in output
    assert "fake-private-key" not in (root / "environment.json").read_text(encoding="utf-8")
    assert "fake-private-key" not in " ".join(str(call[1]) for call in calls)


@pytest.mark.parametrize("port,database", [(80, 6), (65536, 6), (18106, -1), (18106, 15)])
def test_runtime_rejects_invalid_port_or_redis_database(tmp_path, runtime_tool, port, database):
    root = tmp_path / "new"
    with pytest.raises(ValueError, match="Port must be"):
        runtime_tool.start(tmp_path / "old", root, port=port, redis_database=database)
    assert not root.exists()


def test_runtime_refuses_partial_existing_workspace(tmp_path, runtime_tool):
    root = tmp_path / "partial"
    root.mkdir()
    existing = root / "worker.log"
    existing.write_text("preserve", encoding="utf-8")
    with pytest.raises(ValueError, match="Preserve an existing"):
        runtime_tool.start(tmp_path / "old", root)
    assert existing.read_text(encoding="utf-8") == "preserve"


def test_evaluation_runtime_requires_shared_budget_before_start(
    tmp_path, monkeypatch, runtime_tool
):
    monkeypatch.setattr(runtime_tool.socket, 'socket', _FreeSocket)
    monkeypatch.setattr(runtime_tool, 'read_json', lambda _path: {
        'DATABASE_URL': 'postgresql+psycopg://test:test@127.0.0.1:15439/rag_accept',
        'LLM_API_KEY_ENV_NAME': 'RAG_TEST_KEY',
    })
    monkeypatch.setattr(runtime_tool, 'ensure_empty_redis_databases',
                        lambda **_kwargs: pytest.fail('must reject before touching Redis'))

    with pytest.raises(ValueError, match='requires a shared budget ledger'):
        runtime_tool.start(tmp_path / 'old', tmp_path / 'new', port=18106)
    assert not (tmp_path / 'new').exists()


def test_runtime_refuses_occupied_port_before_reading_secrets(
    tmp_path, monkeypatch, runtime_tool
):
    class _OccupiedSocket(_FreeSocket):
        def connect_ex(self, _address):
            return 0

    monkeypatch.setattr(runtime_tool.socket, "socket", _OccupiedSocket)
    monkeypatch.setattr(runtime_tool, "read_json", lambda _path: pytest.fail("must not read secrets"))
    with pytest.raises(ValueError, match="already owned"):
        runtime_tool.start(tmp_path / "old", tmp_path / "new", port=18106)


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://test:test@remote:15439/rag_accept",
    "postgresql+psycopg://test:test@127.0.0.1:5433/rag_accept",
    "postgresql+psycopg://test:test@127.0.0.1:15439/old_business",
    "postgresql+psycopg://test:test@127.0.0.1:15439/rag_accept?host=remote",
])
def test_runtime_refuses_other_databases_before_starting(
    tmp_path, monkeypatch, runtime_tool, url
):
    monkeypatch.setattr(runtime_tool.socket, "socket", _FreeSocket)
    monkeypatch.setattr(runtime_tool, "read_json", lambda _path: {"DATABASE_URL": url})
    with pytest.raises(ValueError, match="dedicated acceptance database"):
        runtime_tool.start(tmp_path / "old", tmp_path / "new", port=18106)
    assert not (tmp_path / "new").exists()


def test_runtime_refuses_nonempty_redis_without_flushing(monkeypatch, runtime_tool):
    import redis

    closed = []

    class _RedisWithData:
        def __init__(self, **kwargs):
            self.database = kwargs["db"]

        def dbsize(self):
            return 1

        def close(self):
            closed.append(self.database)

    monkeypatch.setattr(redis, "Redis", _RedisWithData)
    with pytest.raises(ValueError, match="not empty"):
        runtime_tool.ensure_empty_redis_databases(6)
    assert closed == [6]
