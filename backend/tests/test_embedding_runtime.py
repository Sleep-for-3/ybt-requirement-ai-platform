from app.core.settings import Settings
from app.services.embeddings import factory
from app.services.embeddings.mock import MockEmbeddingService


def test_chat_and_embedding_runtime_configuration_are_independent(monkeypatch):
    settings = Settings(
        _env_file=None,
        llm_provider="openai_compatible",
        llm_base_url="https://chat.example/v1",
        llm_model="deepseek-chat",
        llm_api_key_env_name="CHAT_ONLY_KEY",
        embedding_provider="local_openai_compatible",
        embedding_base_url="http://127.0.0.1:8001/v1",
        embedding_model="bge-m3",
        embedding_api_key_env_name="EMBEDDING_ONLY_KEY",
        embedding_dimension=1024,
    )
    monkeypatch.setattr(factory, "get_settings", lambda: settings)
    factory.get_embedding_service.cache_clear()

    service = factory.get_embedding_service()

    assert service.model == "bge-m3"
    assert service.base_url == "http://127.0.0.1:8001/v1"
    assert service.api_key_env_name == "EMBEDDING_ONLY_KEY"
    assert service.model != settings.llm_model
    assert service.local_only is True


def test_factory_uses_mock_only_when_explicitly_configured(monkeypatch):
    settings = Settings(_env_file=None, embedding_provider="mock")
    monkeypatch.setattr(factory, "get_settings", lambda: settings)
    factory.get_embedding_service.cache_clear()
    assert isinstance(factory.get_embedding_service(), MockEmbeddingService)

    settings = Settings(
        _env_file=None,
        embedding_provider="openai_compatible",
        embedding_base_url="https://embedding.example/v1",
        embedding_model="real-embedding",
        embedding_api_key_env_name="MISSING_TEST_KEY",
    )
    monkeypatch.setattr(factory, "get_settings", lambda: settings)
    factory.get_embedding_service.cache_clear()
    assert not isinstance(factory.get_embedding_service(), MockEmbeddingService)
