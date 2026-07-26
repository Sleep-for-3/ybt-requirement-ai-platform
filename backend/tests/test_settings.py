from app.core.settings import Settings


def test_settings_accepts_comma_separated_cors_origins(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")

    settings = Settings(_env_file=None)

    assert settings.cors_origin_list == ["http://localhost:3000", "http://127.0.0.1:3000"]
