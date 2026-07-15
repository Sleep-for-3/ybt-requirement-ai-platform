from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "YBT Requirement AI Platform"
    api_prefix: str = "/api"
    app_secret_key: str = ""
    database_url: str = "sqlite:///./ybt.db"
    storage_dir: str = "/app/storage"
    cors_origins: str = "http://localhost:3000"
    environment: str = "development"
    auth_mode: str = "optional"
    jwt_secret_key: str = ""
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    login_max_failures: int = 5
    login_lock_seconds: int = 300
    request_rate_limit_per_minute: int = 600
    max_upload_bytes: int = 20 * 1024 * 1024
    lineage_zip_max_total_bytes: int = 100 * 1024 * 1024
    lineage_zip_max_file_count: int = 2000
    lineage_script_max_bytes: int = 10 * 1024 * 1024
    lineage_repository_max_bytes: int = 500 * 1024 * 1024
    lineage_repository_max_file_count: int = 10000
    task_queue_provider: str = "inline"
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"
    storage_provider: str = "local"
    s3_endpoint_url: str = ""
    s3_bucket_name: str = ""
    s3_region: str = "us-east-1"
    database_pool_size: int = 10
    database_max_overflow: int = 20

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

    def validate_production_security(self) -> None:
        if self.environment.lower() != "production":
            return
        missing = []
        if self.auth_mode != "required":
            missing.append("AUTH_MODE=required")
        if len(self.jwt_secret_key) < 32:
            missing.append("JWT_SECRET_KEY (at least 32 characters)")
        if not self.app_secret_key:
            missing.append("APP_SECRET_KEY")
        if "*" in self.cors_origin_list:
            missing.append("explicit CORS_ORIGINS")
        if missing:
            raise RuntimeError("Unsafe production configuration: " + ", ".join(missing))


@lru_cache
def get_settings() -> Settings:
    return Settings()
