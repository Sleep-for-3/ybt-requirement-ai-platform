# Docker Compose 部署

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
