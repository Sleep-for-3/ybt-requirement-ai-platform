# 正式语义检索架构

## 范围

本阶段沿用 `KnowledgeDocument`、`KnowledgeDocumentVersion`、`KnowledgeUnit`、关键词索引、citation、`BackgroundJob` 和 RAG 评测，只把 Mock 向量链路升级为可版本化的正式链路。没有重新切分文档，也没有修改 DeepSeek Chat 的业务逻辑。

## 两条完全独立的模型链路

- Chat：`LLM_PROVIDER / LLM_BASE_URL / LLM_MODEL / LLM_API_KEY_ENV_NAME`，继续用于结构化答案和最终回答。
- Embedding：`EMBEDDING_PROVIDER / EMBEDDING_BASE_URL / EMBEDDING_MODEL / EMBEDDING_API_KEY_ENV_NAME / EMBEDDING_DIMENSION`，只生成文档和查询向量。

系统不会把 Chat 模型名称拿去调用 `/embeddings`。正式 Embedding 或 Milvus 失败时会明确失败，不会自动改用 Mock。

## 数据流

1. 上传文档后复用现有 parser 生成 `KnowledgeUnit` 并建立关键词索引。
2. 正式 Milvus 模式不会在上传时写入无版本的向量集合，语义状态变为 `pending_reindex`。
3. 项目级重建任务冻结当前有效语料 Hash，创建 `EmbeddingIndexVersion`。
4. Worker 按批调用独立 Embedding Provider，以稳定主键 upsert 到新的 Milvus Collection。
5. 数量、维度、抽样搜索全部通过后，新版本才原子切换为 `active`；旧版本变为 `superseded`。
6. 正式向量查询只读取当前项目的 active Collection，并在业务库再次校验知识单元是否启用和可见。
7. `keyword_only`、`vector_only`、`hybrid` 共用原有 citation 和回答生成链路。

## 一致性边界

- 一个 Collection 只对应一个项目、一个模型指纹和一个固定维度。
- 稳定向量主键由索引版本、文档版本、Chunk ID、内容 Hash 和模型指纹生成。
- 同项目同一时刻只由数据库状态暴露一个 active 版本。
- 新版本失败不会改变旧 active；本阶段不会自动删除旧 Collection。
- 文档删除会立即禁用业务库中的知识单元，检索二次校验会阻止旧向量形成 citation；下一次重建会从新语料中排除它。

## 模型指纹

指纹包含 Provider、无查询参数的服务端点摘要、模型名、向量维度、归一化配置版本和索引配置版本。不包含 API Key、Token、Authorization 或 Base URL 查询参数。
