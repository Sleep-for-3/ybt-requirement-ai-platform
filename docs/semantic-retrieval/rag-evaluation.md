# RAG 语义检索评测

评测复用现有 Golden Dataset、`RagEvaluationRun` 和后台任务。页面可选择：

- `keyword_only`：关键词基线，不调用 Embedding。
- `vector_only`：只查询当前 active Milvus 索引。
- `hybrid`：归一化后合并关键词和向量分数，默认模式。

每次 Run 记录数据集版本 Hash、Embedding Provider/模型/维度、索引版本、Collection、模式、Top K、权重、Chat Provider/模型、执行时间和 Token 汇总。

指标包括 Recall@5、Recall@10、MRR、Citation Coverage、Groundedness、确定性 Answer Correctness、检索延迟 P50/P95、回答延迟、索引吞吐和失败查询数。CI 使用 Mock/Fake，不连接公网、不调用真实 DeepSeek 或收费 Embedding。

## 比较方法

在同一批启用案例上依次运行 `keyword_only`、`vector_only` 和 `hybrid`。正式 Hybrid 的 Recall@10 不应低于关键词基线，MRR 如有下降必须结合 Chunk、同义词、模型和权重分析，不得通过硬编码答案或针对测试集过拟合。

## 本地真实验收

使用完全合成的 10 份文档、100 个以上 Chunk 和 20 个问题，覆盖同义词、缩写、表字段名、业务规则与混淆口径。先运行连接测试和项目级重建，再执行三种模式。真实 DeepSeek 只用于人工选择的本地评测，CI 不会触发。

可运行 `python scripts/prepare_semantic_acceptance_dataset.py` 在 `.local-run/semantic-acceptance` 生成 10 份模拟文档、100 个段落和 20 个问题。生成内容不含真实银行材料。
