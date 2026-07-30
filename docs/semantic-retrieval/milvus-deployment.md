# Milvus 部署与持久化

项目复用根目录 `docker-compose.yml` 中已有的 etcd、`milvus-minio` 和 Milvus 2.5.4，不建立第二套 Compose，也不更换已验证镜像版本。

## 启动

```powershell
docker compose --profile milvus config --services
docker compose --profile milvus up -d
docker compose ps
docker volume ls
```

本机直接运行后端时使用：

```dotenv
MILVUS_URI=http://localhost:19530
```

后端和 Worker 都在 Compose 网络内运行时使用：

```dotenv
MILVUS_URI=http://milvus:19530
```

## 持久化

- `milvus_data`：Milvus 数据。
- `etcd_data`：Collection 元数据。
- `milvus_minio_data`：对象数据。

禁止执行 `docker compose down -v`、`docker volume rm` 或 system prune。普通容器重启不会删除这些 named volume。

## Collection

默认格式：

`ybt_semantic_p{project_id}_v{index_version_id}_{fingerprint前12位}_d{dimension}`

每个 Collection 使用固定维度、COSINE、配置化的索引类型，并保存项目、文档、文档版本、Chunk、内容 Hash、citation、分级、模型指纹和索引版本等无正文元数据。知识正文仍保存在业务数据库。

## 持久化验收

使用完全合成数据创建索引，记录安全的 Collection 名和 count，然后：

```powershell
docker compose restart milvus
docker compose ps
```

等待健康后重新读取 count 并执行一次 `vector_only` 查询。前后数量和查询结果必须一致。当前执行环境没有 Docker CLI 时，此项只能在安装 Docker Desktop 的人工验收机完成。
