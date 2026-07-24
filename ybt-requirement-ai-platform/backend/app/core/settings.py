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
    debug: bool = False
    trust_proxy_headers: bool = False
    health_details_public: bool = False
    health_check_timeout_seconds: float = 2.0
    disk_free_min_bytes: int = 100 * 1024 * 1024
    auth_mode: str = "optional"
    jwt_secret_key: str = ""
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    login_max_failures: int = 5
    login_lock_seconds: int = 300
    request_rate_limit_per_minute: int = 600
    max_upload_bytes: int = 20 * 1024 * 1024
    uat_local_pack_dir: str = "./uat_local_packs"
    uat_zip_max_total_bytes: int = 200 * 1024 * 1024
    uat_zip_max_file_count: int = 500
    uat_file_max_bytes: int = 20 * 1024 * 1024
    lineage_zip_max_total_bytes: int = 100 * 1024 * 1024
    lineage_zip_max_file_count: int = 2000
    lineage_script_max_bytes: int = 10 * 1024 * 1024
    lineage_repository_max_bytes: int = 500 * 1024 * 1024
    lineage_repository_max_file_count: int = 10000
    lineage_git_allowed_hosts: str = "github.com,gitee.com"
    lineage_git_allowed_local_roots: str = ""
    lineage_git_enabled: bool = True
    task_queue_provider: str = "inline"

    @property
    def lineage_git_allowed_host_list(self) -> list[str]:
        return [item.strip().lower() for item in self.lineage_git_allowed_hosts.split(",") if item.strip()]

    @property
    def lineage_git_allowed_local_root_list(self) -> list[str]:
        return [item.strip() for item in self.lineage_git_allowed_local_roots.split(",") if item.strip()]

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

    def validate_configuration(self) -> list[dict[str, str]]:
        issues: list[dict[str, str]] = []

        def add(severity: str, code: str, message: str) -> None:
            issues.append({"severity": severity, "code": code, "message": message})

        production = self.environment.lower() == "production"
        if not production:
            add("info", "non_production_mode", "Development or test configuration is active; mock providers may be used.")
        if self.auth_mode not in {"optional", "required"}:
            add("error", "auth_mode_invalid", "AUTH_MODE must be optional or required.")
        elif production and self.auth_mode != "required":
            add("error", "auth_mode_not_required", "Production requires AUTH_MODE=required.")
        if not self.database_url.strip():
            add("error", "database_url_missing", "DATABASE_URL is required.")
        if production and self.app_secret_key.strip().lower() in {"", "default", "change-me", "changeme"}:
            add("error", "app_secret_key_unsafe", "Production APP_SECRET_KEY must be a non-default value.")
        if production and len(self.jwt_secret_key) < 32:
            add("error", "jwt_secret_key_unsafe", "Production JWT_SECRET_KEY must contain at least 32 characters.")
        if self.storage_provider not in {"local", "s3"}:
            add("error", "storage_provider_invalid", "STORAGE_PROVIDER must be local or s3.")
        if self.storage_provider == "s3" and not self.s3_bucket_name.strip():
            add("error", "s3_configuration_missing", "S3 storage requires S3_BUCKET_NAME.")
        if self.task_queue_provider not in {"inline", "celery"}:
            add("error", "task_queue_provider_invalid", "TASK_QUEUE_PROVIDER must be inline or celery.")
        if self.task_queue_provider == "celery" and not self.redis_url.strip():
            add("error", "celery_redis_missing", "Celery mode requires Redis configuration.")
        if self.vector_store_provider not in {"mock", "milvus"}:
            add("error", "vector_store_provider_invalid", "VECTOR_STORE_PROVIDER must be mock or milvus.")
        if self.vector_store_provider == "milvus" and not self.milvus_uri.strip():
            add("error", "milvus_uri_missing", "Milvus mode requires MILVUS_URI.")
        if self.llm_provider != "mock" and not self.llm_api_key.strip():
            add("error" if production else "warning", "llm_api_key_missing", "The configured cloud LLM provider requires an API key.")
        if self.embedding_provider != "mock" and not self.embedding_api_key_env_name.strip():
            add("error" if production else "warning", "embedding_key_reference_missing", "The configured embedding provider requires an API-key environment variable name.")
        if "*" in self.cors_origin_list:
            add("error" if production else "warning", "cors_wildcard", "Unrestricted CORS origins are not allowed in production.")
        add("info", "proxy_headers_explicit", "Trusted proxy headers are enabled." if self.trust_proxy_headers else "Trusted proxy headers are disabled.")
        if self.max_upload_bytes < 1024 or self.max_upload_bytes > 500 * 1024 * 1024:
            add("error", "upload_limit_unreasonable", "MAX_UPLOAD_BYTES must be between 1 KiB and 500 MiB.")
        if self.lineage_git_enabled and not self.lineage_git_allowed_host_list and not self.lineage_git_allowed_local_root_list:
            add("error", "git_allowlist_empty", "Git ingestion requires an allowed host or local root; otherwise disable Git ingestion.")
        if production and self.debug:
            add("error", "debug_enabled", "DEBUG must be disabled in production.")
        return issues

    def validate_production_security(self) -> None:
        errors = [item for item in self.validate_configuration() if item["severity"] == "error"]
        if self.environment.lower() == "production" and errors:
            raise RuntimeError("Unsafe production configuration: " + ", ".join(item["code"] for item in errors))


@lru_cache
def get_settings() -> Settings:
    return Settings()
