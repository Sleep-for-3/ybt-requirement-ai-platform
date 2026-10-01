"""The field-rerank catalog floor stays conservative unless a project is explicitly authorized."""
from types import SimpleNamespace

import pytest

from app.core.settings import get_settings
from app.services.ai_skills import field_rerank


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    yield
    cache_clear = getattr(get_settings, "cache_clear", None)
    if cache_clear:
        cache_clear()


def _project(project_id=1, level="internal"):
    return SimpleNamespace(id=project_id, confidentiality_level=level)


def test_default_floor_denies_external_models(monkeypatch):
    monkeypatch.delenv("AI_EXTERNAL_MODEL_ALLOWED_PROJECT_IDS", raising=False)
    cache_clear = getattr(get_settings, "cache_clear", None)
    if cache_clear:
        cache_clear()
    monkeypatch.setattr(get_settings(), "ai_external_model_allowed_project_ids", "", raising=False)
    assert field_rerank.confidentiality_floor(_project()) == "confidential"


def test_authorized_project_follows_its_declared_level(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_external_model_allowed_project_ids", "1, 5", raising=False)
    assert field_rerank.confidentiality_floor(_project(1)) == "internal"
    assert field_rerank.confidentiality_floor(_project(5, "public")) == "public"


def test_unauthorized_project_keeps_the_floor(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_external_model_allowed_project_ids", "1", raising=False)
    assert field_rerank.confidentiality_floor(_project(9)) == "confidential"
    assert field_rerank.confidentiality_floor(_project(1, "restricted")) == "restricted"