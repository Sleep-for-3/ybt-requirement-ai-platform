# 正式语义检索与持久化向量索引 v1：现状审计

审计基线：`00f0bb840a65915ad0336bcb19e198d87187b9dc`。本文件只描述当前本地代码中的真实实现。

## Embedding 调用链

`get_embedding_service()` 根据 `EMBEDDING_PROVIDER` 创建 `MockEmbeddingService` 或 OpenAI-compatible 适配器。配置使用独立的 `EMBEDDING_BASE_URL`、`EMBEDDING_MODEL` 和 `EMBEDDING_API_KEY_ENV_NAME`，没有依赖聊天模型配置。OpenAI-compatible 适配器已经支持批量请求、超时以及对 408、429 和 5xx 的有限重试；401、403、404 不重试。

`embed_with_observability()` 在调用前执行数据分级检查，外部 Provider 会先使用现有脱敏函数处理文本，并以正文哈希、文本数量、字符数、模型、耗时和 Token 摘要写入 `ModelCallLog`。受限数据会被现有外发策略拒绝并记录安全审计。

当前缺口：

- 公开接口名称仍是 `embed_texts`，没有统一的文档批次结果元数据；
- 没有完整校验非有限数值、批内维度一致性和查询/索引维度一致性；
- batch size、超时和重试次数没有暴露为运行配置；
- 正式配置失败时虽然会报错，但没有索引版本承接失败状态。

## Vector Store 调用链

`get_vector_store()` 在 `mock` 和 `MilvusVectorStore` 之间选择。两种适配器共同实现 `upsert`、`search`、`delete`。Mock 只保存在 API 进程内存；Milvus 使用 `pymilvus.MilvusClient`。

Docker Compose 已有同一套 Milvus profile：

- `etcd`：`etcd_data`
- `milvus-minio`：`milvus_minio_data`
- `milvus`：`milvus_data`
- Milvus 版本 `2.5.4`，端口 `19530`

当前 Milvus 适配器只使用固定 Collection `ybt_knowledge_units`，首次写入时按首条向量维度自动建表。缺少健康检查、显式 schema、版本化 Collection、数量与完整性校验、索引参数配置以及旧版本保留策略。不同模型或维度可能错误进入同一 Collection。

## 知识摄取流程

上传内容先保存到现有 Storage，再创建或递增 `KnowledgeDocumentVersion`。解析器生成 `KnowledgeUnit`；每个 Unit 已具备稳定数据库主键、文档版本、内容哈希、出处位置、数据分级和项目/机构作用域。摄取按 `KNOWLEDGE_INGESTION_BATCH_SIZE` 分批写入关键词索引、实体关系、EmbeddingRecord 和 Vector Store。

文档更新后旧 Unit 会禁用，旧向量会被立即删除。这个行为适用于原测试型单索引，但不满足正式蓝绿索引切换：新索引验证前不应影响当前 active 索引。

## 重新索引流程

现有 `knowledge_reindex` 是“单文档原地覆盖”：

1. 读取该文档当前启用的 KnowledgeUnit；
2. 执行外发策略检查；
3. 一次性生成向量；
4. 重建关键词索引；
5. upsert 到当前 Vector Store；
6. 将文档标记为 indexed。

它已经通过 `BackgroundJob`、任务队列、语义幂等、任务中心和 `/jobs/{id}` 执行，但没有项目级语料快照、EmbeddingIndexVersion、分批进度、验证或 active 原子切换。

## 检索流程

`HybridRetriever.search()` 当前总是同时执行：

1. PostgreSQL 持久关键词倒排检索；
2. 查询文本 Embedding；
3. Vector Store 按项目、全局或机构作用域搜索；
4. 数据库再次校验 Unit 可见性；
5. 按固定 `0.55 keyword + 0.35 vector + 0.1 rules` 合并。

检索结果保留 keyword/vector/rerank 分数和匹配原因，并通过真实 KnowledgeUnit 生成 citation。当前没有 `keyword_only`、`vector_only` 模式，没有 active 索引过滤，向量分数也没有对不同返回范围做规范化。

## Citation 调用链

Milvus 只保存 KnowledgeUnit ID 和治理元数据，不保存正文。检索后重新从业务数据库读取已启用 Unit，`citation_validator` 再检查 Unit 真实存在、启用且对项目可见。Citation 来自 Unit 的文件、Sheet、页码、标题或单元格范围。这条链可以直接复用，正式向量索引不得只凭 Milvus ID 构造 citation。

## RAG 评测流程

现有 `RagEvaluationCase` 保存 Golden Query、期望 Unit、来源系统/表/字段和答案关键词；`RagEvaluationRun` 保存 retrieval config 和汇总指标；`run_evaluation()` 已计算 Recall@5、Recall@10、MRR、Citation Coverage、Groundedness、关键词覆盖和平均延迟，并由 `rag_evaluation` BackgroundJob 执行。

当前缺口是没有记录索引版本、Embedding/Collection、检索模式、P50/P95、Answer Correctness、失败查询和索引吞吐，也无法在同一 Golden Dataset 上明确运行 keyword/vector/formal hybrid 对比。

## 可直接复用的能力

- 独立 Embedding Factory 与 OpenAI-compatible 适配器；
- 外发分级、脱敏、审计和 ModelCall 可观测性；
- KnowledgeDocumentVersion、KnowledgeUnit、内容哈希和真实出处；
- PostgreSQL 关键词索引；
- Mock/Milvus VectorStore seam；
- HybridRetriever 与 citation validator；
- RAG Evaluation 数据模型与 BackgroundJob；
- 任务幂等、进度、Toast、任务中心和 `/jobs/{id}`；
- Docker Compose 中现有持久化 Milvus profile。

## 必须补齐的能力

- `EmbeddingIndexVersion` 及对称 migration；
- Provider/model/维度/索引配置指纹和版本化 Collection；
- Milvus 健康、显式建表、幂等 upsert、count、validate 与版本隔离；
- 项目级蓝绿重建、完整性校验和 active 原子切换；
- active 版本驱动的 keyword/vector/hybrid 三种模式；
- 规范化合并分数、索引与评测元数据；
- 语义检索状态、版本列表、付费提醒和重新索引入口。

## 本阶段不修改

DeepSeek Chat Profile、业务/技术口径生成、知识解析与 Chunk 切分、SQL 血缘、UAT 规则、正式交付、审批状态机、权限架构、Agent、MCP、任务中心和任务详情路由。
