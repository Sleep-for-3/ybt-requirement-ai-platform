from pathlib import Path
import json

import pytest

from scripts.rag_round46_runtime import (
    CONTAINERS,
    VOLUMES,
    browser_api_environment,
    formal_vector_identity,
    _wsl_path,
    prepare,
    preflight_inventory,
)


def test_round46_preflight_rejects_any_owned_resource_collision():
    with pytest.raises(ValueError, match="round46_resources_already_exist"):
        preflight_inventory({
            "containers": {CONTAINERS[0]},
            "volumes": set(),
        })


def test_round46_preflight_accepts_only_clean_namespace():
    preflight_inventory({"containers": set(), "volumes": set()})


def test_wsl_path_requires_absolute_windows_path():
    with pytest.raises(ValueError, match="absolute Windows path"):
        _wsl_path(Path("relative/path"))


def test_wsl_path_maps_workspace_without_shell_evaluation():
    assert _wsl_path(Path("C:/rag workspace/backend")) == "/mnt/c/rag workspace/backend"


def test_formal_runtime_targets_configured_milvus_and_collection_namespace(monkeypatch):
    monkeypatch.setattr("scripts.rag_round46_runtime.PREFIX", "rag-p0-r53")
    monkeypatch.setattr("scripts.rag_round46_runtime.MILVUS_PORT", 19533)
    assert formal_vector_identity() == {
        "uri": "http://127.0.0.1:19533",
        "collection_prefix": "rag_p0_r53_formal",
    }


def test_browser_api_uses_current_identity_isolated_queue_and_shared_budget(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.rag_round46_runtime.REDIS_PORT", 16392)
    environment = browser_api_environment(
        {"LLM_PROVIDER": "mock", "EMBEDDING_PROVIDER": "local_vllm"},
        app_commit="head+worktree.current",
        build_time="2026-11-17T00:00:00+00:00",
        budget_path=tmp_path / "BUDGET.json",
        budget_state=tmp_path / "provider-budget.sqlite3",
        frontend_port=18136,
        broker_db=4,
        result_db=5,
    )

    assert environment["APP_COMMIT"] == "head+worktree.current"
    assert environment["CORS_ORIGINS"] == "http://127.0.0.1:18136"
    assert environment["CELERY_BROKER_URL"] == "redis://127.0.0.1:16392/4"
    assert environment["CELERY_RESULT_BACKEND"] == "redis://127.0.0.1:16392/5"
    assert environment["RAG_MODEL_BUDGET_REQUIRED"] == "true"
    assert environment["LLM_PROVIDER"] == "mock"


def test_browser_api_rejects_shared_or_invalid_redis_databases(tmp_path):
    kwargs = {
        "app_commit": "head+worktree.current",
        "build_time": "2026-11-17T00:00:00+00:00",
        "budget_path": tmp_path / "BUDGET.json",
        "budget_state": tmp_path / "provider-budget.sqlite3",
        "frontend_port": 18136,
        "broker_db": 4,
        "result_db": 4,
    }
    with pytest.raises(ValueError, match="Redis databases"):
        browser_api_environment({}, **kwargs)


def test_prepare_keeps_generated_secrets_out_of_workspace_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.rag_round46_runtime.REPOSITORY", tmp_path)
    monkeypatch.setattr(
        "scripts.rag_round46_runtime.PRIVATE_ROOT",
        tmp_path / ".local-run/rag-long-run/private-round46",
    )
    monkeypatch.setattr("scripts.rag_round46_runtime._port_available", lambda _port: True)
    monkeypatch.setattr("scripts.rag_round46_runtime._milvus_collections", lambda: [])
    monkeypatch.setattr("scripts.rag_round46_runtime._source_identity", lambda: ("head+worktree.hash", "a" * 64))

    workspace = tmp_path / "workspace"
    plan = prepare(workspace, milvus_container_id="a" * 64)
    credentials = json.loads((tmp_path / ".local-run/rag-long-run/private-round46/secrets.json").read_text())
    artifacts = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (workspace / "environment.json", workspace / "runtime-plan.json")
    )

    for key in ("postgres_password", "app_secret_key", "jwt_secret_key"):
        assert credentials[key] not in artifacts
    assert "postgresql+psycopg://" not in artifacts
    assert plan["secret_fields_persisted"] is False
