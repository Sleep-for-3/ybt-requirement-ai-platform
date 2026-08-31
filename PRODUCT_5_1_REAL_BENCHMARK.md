# Product 5.1 Real Runtime Benchmark

**最终判断：REAL_AGENT_BENCHMARK_PASS**

> 本报告来自真实 Runtime 执行。Agent 阶段未读取 Golden Truth；本节 Golden Evaluation 只在 17 个字段尝试完成后离线读取并比较。指标为可审计的字段级启发式统计，不把缺失输出当作正确。

## Runtime

- LLM：`openai_compatible` / `gpt-5.6-sol`，profile id `2`，`is_mock=False`，配置与连接状态 `ready`。
- Embedding：`local_vllm` / `BAAI/bge-small-zh-v1.5`，dimension `512`，`is_mock=False`。
- Vector store：`milvus`，`is_mock=False`；Runtime issues：`none`。
- Semantic index：`formal`，collection `ybt_semantic_p5_v5_ec2e880fd3f8_d512`，vectors `32`，dimension `512`，Milvus `healthy`。
- Generator effective runtime：`OpenAICompatibleLLMService` / `gpt-5.6-sol`；configuration drift `False`，与 Runtime status 使用同一 active profile。
- API compatibility：OpenAI-compatible `/v1/models`、chat completion HTTP 200；JSON Mode smoke HTTP 200。生产生成因站点要求消息包含英文 `json`，改用现有 Profile 的 `json_mode=false` + Structured Response validator。

## E010010 Smoke Result

- 目标：产品期限；真实链路：RegulatoryContext → Retrieval → Source-to-Mart → Mart-to-YBT → 场景业务/技术需求草稿。
- 结果：四类生成的持久化草稿均来自真实 Runtime 并通过当前 schema；ModelCallLog provider/model 为 `openai_compatible / gpt-5.6-sol`。
- Gate：通过真实调用、非 mock、Context 非空、候选来自 Catalog；但语义绑定/批准映射仍是待确认，因此 confidence 被正确限制为 low，不能视为正式批准口径。

## 17 Field Results

| 字段 | Agent 状态 | Context facts | Evidence | Semantic facts | Lineage (nodes/edges/unresolved) |
|---|---:|---:|---:|---:|---:|
| E010001 | success | 44 | 30 | 0 | 4/2/0 |
| E010002 | success | 44 | 30 | 0 | 4/2/0 |
| E010003 | success | 46 | 32 | 0 | 4/2/0 |
| E010004 | success | 44 | 30 | 0 | 4/2/0 |
| E010005 | success | 46 | 32 | 0 | 4/2/0 |
| E010007 | success | 44 | 30 | 0 | 4/2/0 |
| E010008 | success | 44 | 30 | 0 | 8/6/0 |
| E010009 | success | 46 | 32 | 0 | 4/2/0 |
| E010010 | success | 45 | 31 | 0 | 4/2/0 |
| E010011 | success | 46 | 32 | 0 | 4/2/0 |
| E010012 | success | 46 | 32 | 0 | 4/2/0 |
| E010013 | success | 44 | 30 | 0 | 4/2/0 |
| E010014 | success | 44 | 30 | 0 | 4/2/0 |
| E010015 | success | 47 | 30 | 0 | 7/6/0 |
| E010018 | success | 49 | 32 | 0 | 8/6/0 |
| E010016 | success | 49 | 30 | 0 | 7/6/0 |
| E010017 | success | 46 | 32 | 0 | 4/2/0 |

Success `17` / Partial `0` / Total `17`。本次补跑使用 Sol Profile；最终幂等 artifact 对已有真实成功草稿标记为 `reused_existing_success`，不把复用计作新的模型请求，也没有将失败字段或缺失任务乐观记为成功。

真实调用 provenance：早期运行和 Sol 补跑的 ModelCallLog/中间 artifact 保留真实模型请求；最终 17-field 汇总允许复用已持久化草稿以避免重复消耗额度。复用状态不改变 Agent 阶段禁止读取 Golden Truth 的约束，也不等同于人工批准。

## Golden Evaluation

- Target → Mart Accuracy：17/17 (100%)
- Mart → Source Accuracy：15/17 (88%)
- Transformation Accuracy：10/17 (59%)
- Evidence Citation Accuracy：17/17 (100%)
- Semantic Match Accuracy：17/17 (100%)
- Hallucinated Asset Count：未对 partial 字段作乐观归零；complete 字段 heuristic 计数为 0，需后续人工复核。
- Missing Required Source Count：7（complete 字段 heuristic 总计）。
- Open Question Precision：complete 字段按输出有待确认问题进行记录；本轮不把模型开放问题当作已解决事实。

逐字段 evaluation（`true/false` 仅基于 Agent 输出文本与 Golden mapping 的离线匹配；没有把 Golden 内容写入 Prompt）：

| 字段 | T→M | M→S | Transformation | Evidence | Semantic | Missing sources |
|---|---:|---:|---:|---:|---:|---:|
| E010001 | True | True | True | True | True | 0 |
| E010002 | True | True | False | True | True | 1 |
| E010003 | True | True | False | True | True | 0 |
| E010004 | True | True | False | True | True | 0 |
| E010005 | True | True | False | True | True | 0 |
| E010007 | True | True | False | True | True | 2 |
| E010008 | True | True | True | True | True | 0 |
| E010009 | True | True | True | True | True | 0 |
| E010010 | True | True | True | True | True | 0 |
| E010011 | True | True | True | True | True | 0 |
| E010012 | True | True | True | True | True | 0 |
| E010013 | True | True | False | True | True | 0 |
| E010014 | True | False | True | True | True | 2 |
| E010015 | True | True | True | True | True | 0 |
| E010018 | True | False | True | True | True | 2 |
| E010016 | True | True | False | True | True | 0 |
| E010017 | True | True | True | True | True | 0 |

## Token Usage

- ModelCallLog requests：100；usage available 的请求累计 prompt `383265`、completion `42390`、total `425655`、cached `43439`。失败/连接中断请求 usage unavailable，未猜测成本。

## Target Lineage

- `E010007 产品类别`、`E010010 产品期限`、`E010015 产品状态代码`、`E010018 代客产品所属机构名称` 均可通过真实 API 查询 Target → Mart；其中 E010015/E010018 包含 v2 code mapping 边，所有返回节点 `unresolved_flag=false`。
- 全项目 unresolved 节点仍为 69，未强制绑定。分类：parser_or_constant=5, external_or_unimported_catalog_asset=60, unresolved_catalog_resolution=4。

## Metadata Drift

- 第二次无结构变化 full sync：7/7 jobs completed，7 个 MetadataSyncTask drift events 均为 0；schema/table/column 计数保持稳定。

## SQL Impact

- v1 → v2 parse completed；impact id `40`，severity `critical`。affected target fields `17`，mart fields `18`，requirements `17`，review tasks `3`。Impact 已传播到 Target / Requirement / ReviewTask，不是停在 Mart。

## Product Findings

1. 真实 Generator 确实经过 `RegulatoryContextBuilder`、Context Adapter、`execute_runtime_chat` 与 active Model Profile 2，没有发现 Runtime status=real 但 Generator 使用 MockLLM 的漂移。
2. 当前没有独立命名为 Requirement Generator 的新 Framework；需求产出由既有 scenario business/technical generators 承担，这是现有产品抽象，未创建第二套实现。
3. 本次 Sol 补跑后 17 个字段均完成结构化生成；Agent success 不代表映射已经人工批准。
4. 语义概念和 binding 当前仍有 `ai_suggested`；缺少 confirmed semantic version/binding 时仍保留待确认问题。

## Next Fixes

- 对 Golden 评估低命中的映射、来源与转换做人工治理和候选资产校准；不修改 Golden Truth。
- 进行 14 个 Semantic Concepts / 关键 Bindings 的 Human Governance，再重跑正式 Agent 与 Golden Evaluation。
- Smoke 管理员核心浏览器 UAT 已完成；仍需补齐多角色 authenticated UAT、staging PostgreSQL、concurrency/locking、backup/restore、security/performance/driver matrix 后，才能进入 release qualification。

## Gate Decision

`REAL_AGENT_BENCHMARK_PASS`：真实 LLM + 真实 Embedding + 真实 Milvus + 17 字段结构化生成均完成；Golden Evaluation 仍是离线审计，不能替代人工批准或生产发布门禁。
