from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "YBT Requirement AI Platform"
    api_prefix: str = "/api"
    app_secret_key: str = ""
    database_url: str = "postgresql+psycopg://ybt:ybt_password@postgres:5432/ybt_requirement_ai"
    storage_dir: str = "/app/storage"
    cors_origins: str = "http://localhost:3000"

    llm_provider: str = "mock"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    embedding_provider: str = "mock"
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key_env_name: str = "EMBEDDING_API_KEY"
    llm_api_key_env_name: str = "OPENAI_API_KEY"

    vector_store_provider: str = "mock"
    milvus_uri: str = "http://localhost:19530"
    milvus_token: str = ""

    safe_sql_default_limit: int = 100
    safe_sql_max_limit: int = 1000
    safe_sql_timeout_seconds: int = 30

    enable_postgres_datasource: bool = True
    enable_sqlite_datasource: bool = True
    enable_oracle_datasource: bool = False
    enable_mysql_datasource: bool = False
    enable_db2_datasource: bool = False
    enable_hive_datasource: bool = False

    coze_enabled: bool = False
    coze_base_url: str = "http://coze-studio:8888"
    coze_api_key: str = ""
    coze_workflow_id: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
