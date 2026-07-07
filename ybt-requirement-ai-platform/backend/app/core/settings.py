from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "YBT Requirement AI Platform"
    api_prefix: str = "/api"
    database_url: str = "postgresql+psycopg://ybt:ybt_password@postgres:5432/ybt_requirement_ai"
    storage_dir: str = "/app/storage"
    cors_origins: list[str] = ["http://localhost:3000"]

    llm_provider: str = "mock"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"

    vector_store_provider: str = "mock"

    coze_enabled: bool = False
    coze_base_url: str = "http://coze-studio:8888"
    coze_api_key: str = ""
    coze_workflow_id: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
