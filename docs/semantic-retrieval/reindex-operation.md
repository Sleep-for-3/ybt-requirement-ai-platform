# 正式语义索引重建操作

## 前置条件

1. DeepSeek Chat 配置保持不变。
2. 独立 Embedding 连接测试成功，维度已写入 `EMBEDDING_DIMENSION`。
3. `VECTOR_STORE_PROVIDER=milvus`，Milvus 健康。
4. PostgreSQL、Redis、Celery Worker 按正式运行方式可用。

## 操作

进入“知识库 → 知识文档”，查看语义检索状态卡。点击“重新构建语义索引”后，确认框会显示文档数、Chunk 数、Provider 和可能产生的调用费用。确认后进入既有 `/jobs/{id}`。

任务步骤：

1. `preparing_corpus`
2. `creating_index_version`
3. `embedding_chunks`
4. `writing_milvus`
5. `validating_index`
6. `activating_index`
7. `completed`

任务详情显示 Provider、模型、维度、文档数、Chunk 数、已写入数、失败数、批次和 Collection，不显示正文或密钥。

## 幂等

幂等键包含机构、项目、操作类型、模型指纹、语料 Hash、Chunk 策略和索引配置版本。相同 queued/running 请求返回原 job。相同模型和语料已经 active 时，默认只显示当前索引，不重新产生费用；只有明确“强制重建”才生成新代次。

## 失败和恢复

失败版本标记为 `failed`，旧 active 保持可用，半成品 Collection 不会激活也不会自动删除。任务按稳定向量主键 upsert，已完成批次由 `BackgroundJobItem` 形成安全 checkpoint；可以使用任务重试或重新提交。

## 安全回滚

本阶段不提供删除 active 的按钮，也不自动删除最近旧版本。如需回滚，先核对旧版本 Collection 的数量和抽样查询，再由管理员在数据库事务中把当前 active 标记为 superseded、目标 validated/superseded 版本标记为 active。操作前备份数据库并记录审计，禁止直接删除当前 Collection。
