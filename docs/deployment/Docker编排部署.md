# Docker 编排部署

开发模式：

```bash
docker compose up --build
```

生产依赖 profile：

```bash
docker compose --profile production up -d --build
docker compose --profile production exec backend alembic upgrade head
```

如需 Milvus，再增加 `--profile milvus`。启动前在宿主机或 Secret 文件中设置 PostgreSQL、JWT、应用、S3/MinIO 和 Milvus 凭据；不要使用示例值。

上线顺序建议为 PostgreSQL、Redis/对象存储、迁移、API/Worker、前端。探针使用 `/health/live` 和 `/health/ready`，不要用需要管理员权限的 `/health/details` 作为容器探针。

生产环境不应直接暴露 PostgreSQL、Redis、MinIO 管理端口或 Milvus；只由内部网络访问。TLS 和可信代理头由入口代理统一配置。

知识上传由 API 保存原文件并向 Redis 投递 `knowledge_ingestion` 任务，随后立即返回 `202 Accepted`；Celery Worker 负责解析和索引。`KNOWLEDGE_INGESTION_BATCH_SIZE` 控制每次数据库写入规模，默认 200。API 与 Worker 必须使用同一套 `DATABASE_URL`、存储配置、Redis/Celery 地址和索引 Provider 配置。
