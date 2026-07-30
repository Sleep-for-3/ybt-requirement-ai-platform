# 正式语义检索排障

## 页面仍显示 Mock

检查 `EMBEDDING_PROVIDER` 和 `VECTOR_STORE_PROVIDER`。修改 `backend/.env` 后必须重启后端和 Worker。不要修改 Chat 的 `LLM_*` 配置来解决 Embedding 问题。

## Embedding 连接测试失败

- 401/403：独立密钥环境变量不存在或无权限，不会重试。
- 404：Base URL 或模型名错误，确认服务的 `/embeddings` 路径。
- 429/5xx：系统会有限重试，持续失败时检查配额和服务容量。
- 维度不一致：连接测试返回值与 `EMBEDDING_DIMENSION` 不同，修正配置并重新建新索引。
- 本地服务不可达：宿主机与容器中的 `localhost` 含义不同。

## Milvus 不可用

依次检查 `docker compose ps`、Milvus health、etcd 和 `milvus-minio`，再确认 `MILVUS_URI` 是当前进程可达的地址。不要通过改回 Mock 隐藏正式环境故障，不要删除 volume。

## 重建失败但查询仍有结果

这是预期的蓝绿行为：新版本未通过验证，旧 active 仍服务查询。到 `/jobs/{id}` 查看安全错误摘要和失败批次，修复 Provider/Milvus 后重试。

## 上传后显示“待重新索引”

正式模式上传只解析文档和建立关键词索引，避免无版本写入和意外费用。点击项目级“重新构建语义索引”后，新语料才会进入新的 active Collection。

## 数量校验失败

比较状态卡的有效 Chunk 数、版本的 `indexed_count` 和 Milvus count。检查失败批次、被禁用/归档文档和内容 Hash。不要手工把未验证版本改成 active。

## 查询报没有 active 索引

先完成项目级重建。正式模式不会静默使用 Mock；如只需要临时查询，可显式选择 `keyword_only`。
