# 环境变量

生产环境至少配置以下变量，凭据应由 Secret 管理系统注入，不写入镜像、Compose 文件或日志。

| 变量 | 生产要求 |
| --- | --- |
| `ENVIRONMENT` | `production` |
| `AUTH_MODE` | `required` |
| `APP_SECRET_KEY` | 非默认随机值 |
| `JWT_SECRET_KEY` | 至少 32 字符 |
| `DATABASE_URL` | PostgreSQL SQLAlchemy URL |
| `CORS_ORIGINS` | 明确的 HTTPS 前端源，禁止 `*` |
| `DEBUG` | `false` |
| `TRUST_PROXY_HEADERS` | 按实际代理拓扑明确设置 |
| `STORAGE_PROVIDER` | `local` 或 `s3` |
| `STORAGE_DIR` | 本地存储目录，仅 local 使用 |
| `S3_BUCKET_NAME` | S3 模式必填 |
| `S3_ENDPOINT_URL` | MinIO 或兼容服务使用 |
| `TASK_QUEUE_PROVIDER` | 生产建议 `celery` |
| `REDIS_URL` | Celery 模式必填 |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | Worker 使用 |
| `VECTOR_STORE_PROVIDER` | `mock` 或 `milvus` |
| `MILVUS_URI` | Milvus 模式必填 |
| `LLM_PROVIDER` | `mock` 或部署支持的云端提供方 |
| `LLM_API_KEY` | 非 mock 模式通过 Secret 注入 |
| `EMBEDDING_PROVIDER` | `mock` 或兼容提供方 |
| `EMBEDDING_API_KEY_ENV_NAME` | 指向密钥环境变量名 |
| `MAX_UPLOAD_BYTES` | 1 KiB 至 500 MiB |
| `UAT_LOCAL_PACK_DIR` | 本地真实脱敏 UAT 材料目录；不得提交 Git |
| `HEALTH_DETAILS_PUBLIC` | 默认 `false` |

启动时 `Settings.validate_configuration()` 会输出 error/warning/info；任何 error 都会阻止应用启动，消息不含密钥值。
