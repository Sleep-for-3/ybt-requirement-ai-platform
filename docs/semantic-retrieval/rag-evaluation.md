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

## 2026-07-30 本机验收结果

使用 `BAAI/bge-small-zh-v1.5`（FastEmbed CPU，512 维）和 Milvus 对项目 4 的 10 份合成文档、100 个 Chunk、20 个问题完成验收：

| 模式 | Top 1 命中 | Recall@5 | Recall@10 | MRR | P50 / P95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `keyword_only` | 20/20 | 1.00 | 1.00 | 1.00 | 36.4 / 56.3 ms |
| `vector_only` | 11/20 | 0.60 | 0.60 | 0.5625 | 717.7 / 969.0 ms |
| `hybrid` | 20/20 | 1.00 | 1.00 | 1.00 | 570.6 / 686.8 ms |

三种模式的 Citation Coverage 均为 1.00。同一语料重复提交正式重建请求时复用了后台任务 `#62`；该任务约 9.36 秒写入 100 个 Chunk，端到端吞吐约 10.7 Chunk/s。Milvus 单独重启前后均为 100 条向量，重启后 Hybrid 首条仍命中 `01-loan_balance.md`。本轮没有自动执行 DeepSeek 回答正确性评测，避免在未明确授权的情况下产生外部模型费用；检索与持久化部分已经使用真实 Embedding 和真实 Milvus 完成。
