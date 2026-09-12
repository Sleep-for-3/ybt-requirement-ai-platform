# Docker 编排部署

生产拓扑是 **Linux + Docker Compose**，唯一入口文件是仓库根目录的 `docker-compose.yml`。

## 1. 准备环境文件

```bash
cp .env.production.example .env     # .env 已被 gitignore，切勿提交
vi .env                             # 替换全部 change-me 占位值
```

`docker-compose.yml` 不会引用 `.env.production.example`；它只读取私有 `.env`。必需项使用 `${VAR:?...}` 形式，缺失时 compose 会直接拒绝启动，而不是静默使用空密钥：

`POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_DB`、`APP_SECRET_KEY`、`JWT_SECRET_KEY`、`PRODUCTION_DATABASE_URL`。

## 2. 启动

```bash
docker compose -p ybt up -d --build
docker compose -p ybt ps
```

服务顺序由编排保证，无需手工执行迁移：

1. `postgres` / `redis` 通过自身 healthcheck；
2. 一次性 `migrate` 服务执行 `alembic upgrade head`（`restart: "no"`，失败即停）；
3. `backend` / `worker` / `beat` 通过 `depends_on: migrate: condition: service_completed_successfully` 等待迁移成功后才启动；
4. `frontend` 等待 `backend` healthy。

不要再用 `docker compose exec backend alembic upgrade head` 手工迁移——那会绕过编排门禁。

## 3. 可选 profile

```bash
docker compose -p ybt --profile milvus up -d            # etcd + minio + milvus
docker compose -p ybt --profile object-storage up -d    # 独立 MinIO
```

启用这两个 profile 前必须在 `.env` 中设置 `MILVUS_MINIO_ROOT_USER` / `MILVUS_MINIO_ROOT_PASSWORD`（milvus）以及 `S3_ACCESS_KEY` / `S3_SECRET_KEY`（object-storage）。未设置时 compose 会打印 "variable is not set" 警告。

## 4. 本地开发

开发不要修改 `docker-compose.yml`，改用叠加文件把依赖端口映射到回环地址：

```bash
docker compose -f docker-compose.yml -f docker-compose.dev-ports.yml up -d
```

该叠加文件才会暴露 PostgreSQL 5432、Redis 6379、Milvus 19530 到 `127.0.0.1`。

## 5. 端口与绑定

- `backend` 与 `frontend` 默认只绑定 `127.0.0.1`，可用 `BACKEND_BIND_ADDRESS` / `FRONTEND_BIND_ADDRESS` 覆盖；
- `postgres`、`redis`、`milvus` **不发布任何宿主机端口**，只能通过内部网络访问；
- 对外暴露由入口代理完成，TLS 与可信代理头由代理统一配置（同时设置 `TRUST_PROXY_HEADERS=true`）。

## 6. 探针

- API：`python -m app.container_probe api` → `/health/live`；
- Worker / Beat：`python -m app.container_probe worker|beat` → 检查 `/proc` 中的 celery 进程；
- 前端：容器内 `fetch('http://127.0.0.1:3000/')`。

不要用需要管理员权限的 `/health/details` 作为容器探针。

## 7. 校验编排

```bash
cp .env.production.example .env      # 若尚无 .env
docker compose -p ybt config -q
docker compose -p ybt --profile milvus config -q
docker compose -p ybt --profile object-storage config -q
```

契约由 `backend/tests/test_deployment_contract.py` 固化：迁移门禁、四个长期服务的 healthcheck、依赖端口不外泄、API/Worker/Beat/Migrate 共用同一份 environment、`.env.production.example` 覆盖 compose 全部变量且不含真实密钥。

## 8. 运行时约定

知识上传由 API 保存原文件并向 Redis 投递 `knowledge_ingestion` 任务，随后立即返回 `202 Accepted`；Celery Worker 负责解析和索引，`KNOWLEDGE_INGESTION_BATCH_SIZE` 控制每次数据库写入规模（默认 200）。API 与 Worker 必须使用同一套 `DATABASE_URL`、存储配置、Redis/Celery 地址和索引 Provider 配置。

脚本仓库轮询依赖独立 `beat` 服务，缺失时受控仓库不会自动同步。
