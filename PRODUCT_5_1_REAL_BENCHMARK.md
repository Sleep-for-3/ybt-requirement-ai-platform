# Product 5.1 Real Runtime Benchmark

**最终判断：REAL_AGENT_BENCHMARK_PARTIAL**

> 本报告来自真实 Runtime 执行。Agent 阶段未读取 Golden Truth；本节 Golden Evaluation 只在 17 个字段尝试完成后离线读取并比较。指标为可审计的字段级启发式统计，不把缺失输出当作正确。

## Runtime

- LLM：`openai_compatible` / `gpt-5.6-luna`，profile id `2`，`is_mock=False`，状态 `configured`。
- Embedding：`local_vllm` / `BAAI/bge-small-zh-v1.5`，dimension `512`，`is_mock=False`。
- Vector store：`milvus`，`is_mock=False`；Runtime issues：`none`。
- Semantic index：formal Milvus index ready，collection `ybt_semantic_p5_v5_ec2e880fd3f8_d512`，32 vectors，512 dimensions，COSINE。
- API compatibility：OpenAI-compatible `/v1/models`、chat completion HTTP 200；JSON Mode smoke HTTP 200。生产生成因站点要求消息包含英文 `json`，改用现有 Profile 的 `json_mode=false` + Structured Response validator。

## E010010 Smoke Result

- 目标：产品期限；真实链路：RegulatoryContext → Retrieval → Source-to-Mart → Mart-to-YBT → 场景业务/技术需求草稿。
- 结果：四类生成均有真实模型调用并通过当前 schema；ModelCallLog provider/model 为 `openai_compatible / gpt-5.6-luna`；Context fact count 11，目标血缘为 2 nodes / 1 edge（重复同步后 API 返回 4/2，均 resolved）。
- Gate：通过真实调用、非 mock、Context 非空、候选来自 Catalog；但语义绑定/批准映射仍是待确认，因此 confidence 被正确限制为 low，不能视为正式批准口径。

## 17 Field Results

| 字段 | Agent 状态 | Context facts | Evidence | Semantic facts | Lineage (nodes/edges/unresolved) |
|---|---:|---:|---:|---:|---:|
| E010001 | success | 44 | 30 | 0 | 4/2/0 |
| E010002 | partial | 44 | 30 | 0 | 4/2/0 |
| E010003 | success | 46 | 32 | 0 | 4/2/0 |
| E010004 | partial | 44 | 30 | 0 | 4/2/0 |
| E010005 | success | 46 | 32 | 0 | 4/2/0 |
| E010007 | success | 44 | 30 | 0 | 4/2/0 |
| E010008 | partial | 44 | 30 | 0 | 8/6/0 |
| E010009 | success | 46 | 32 | 0 | 4/2/0 |
| E010010 | success | 45 | 31 | 0 | 4/2/0 |
| E010011 | success | 46 | 32 | 0 | 4/2/0 |
| E010012 | partial | 46 | 32 | 0 | 4/2/0 |
| E010013 | success | 44 | 30 | 0 | 4/2/0 |
| E010014 | success | 44 | 30 | 0 | 4/2/0 |
| E010015 | partial | 46 | 30 | 0 | 7/6/0 |
| E010018 | partial | 49 | 32 | 0 | 8/6/0 |
| E010016 | partial | 48 | 30 | 0 | 7/6/0 |
| E010017 | success | 46 | 32 | 0 | 4/2/0 |

Success `10` / Partial `7` / Total `17`。Partial 的主要原因是第三方 provider 长响应连接中断（RemoteProtocolError）或 invalid_model_response；未出现 401/402/403/404/429。

## Golden Evaluation

- Target → Mart Accuracy：4/10 (40%)
- Mart → Source Accuracy：3/10 (30%)
- Transformation Accuracy：1/10 (10%)
- Evidence Citation Accuracy：10/10 (100%)
- Semantic Match Accuracy：5/10 (50%)
- Hallucinated Asset Count：未对 partial 字段作乐观归零；complete 字段 heuristic 计数为 0，需后续人工复核。
- Missing Required Source Count：15（complete 字段 heuristic 总计）。
- Open Question Precision：complete 字段按输出有待确认问题进行记录；本轮不把模型开放问题当作已解决事实。

逐字段 evaluation（`true/false` 仅基于 Agent 输出文本与 Golden mapping 的离线匹配；没有把 Golden 内容写入 Prompt）：

| 字段 | T→M | M→S | Transformation | Evidence | Semantic | Missing sources |
|---|---:|---:|---:|---:|---:|---:|
| E010001 | False | False | False | True | False | 2 |
| E010002 | False | False | False | True | False | 2 |
| E010003 | False | False | False | True | False | 1 |
| E010004 | False | True | False | True | False | 1 |
| E010005 | True | True | False | True | True | 0 |
| E010007 | False | False | False | True | False | 3 |
| E010008 | False | False | False | True | False | 2 |
| E010009 | False | True | False | True | True | 1 |
| E010010 | False | False | False | True | False | 3 |
| E010011 | False | False | False | True | False | 1 |
| E010012 | False | False | False | True | False | 2 |
| E010013 | True | False | False | True | True | 2 |
| E010014 | True | False | False | True | True | 2 |
| E010015 | True | True | True | True | True | 0 |
| E010018 | True | False | True | True | True | 2 |
| E010016 | True | False | False | True | True | 1 |
| E010017 | True | True | True | True | True | 0 |

## Token Usage

- ModelCallLog requests：97；usage available 的请求累计 prompt `306848`、completion `38534`、total `345382`、cached `9472`。失败/连接中断请求 usage unavailable，未猜测成本。

## Target Lineage

- `E010007 产品类别`、`E010010 产品期限`、`E010015 产品状态代码`、`E010018 代客产品所属机构名称` 均可通过真实 API 查询 Target → Mart；其中 E010015/E010018 包含 v2 code mapping 边，所有返回节点 `unresolved_flag=false`。
- 全项目 unresolved 节点仍为 69，未强制绑定。分类：parser_or_constant=5, external_or_unimported_catalog_asset=60, unresolved_catalog_resolution=4。

## Metadata Drift

- 第二次无结构变化 full sync：7/7 jobs completed，7 个 MetadataSyncTask drift events 均为 0；schema/table/column 计数保持稳定。

## SQL Impact

- v1 → v2 script version 2 parse completed；change set / impact id 40，severity critical。affected target fields `17`，mart fields `18`，requirements `17`，review tasks `3`。Impact 已传播到 Target / Requirement / ReviewTask，不是停在 Mart。

## Product Findings

1. 真实 Generator 确实经过 `RegulatoryContextBuilder`、Context Adapter、`execute_runtime_chat` 与 active Model Profile 2，没有发现 Runtime status=real 但 Generator 使用 MockLLM 的漂移。
2. 当前没有独立命名为 Requirement Generator 的新 Framework；需求产出由既有 scenario business/technical generators 承担，这是现有产品抽象，未创建第二套实现。
3. 第三方服务对大上下文请求存在约 60 秒连接中断，导致 7 个字段 partial；下一阶段应在 provider SLA/上下文压缩/任务异步化方向修复，而不是伪造结果或无限重试。
4. 语义概念和 binding 当前仍为 `ai_suggested`，Context 因缺少 confirmed semantic version/binding 而将 confidence 限制为 low，符合治理规则。

## Next Fixes

- 先解决第三方 endpoint 的长请求稳定性，并增加 provider-specific bounded timeout/telemetry；重跑 7 个 partial 字段。
- 进行 14 个 Semantic Concepts / 关键 Bindings 的 Human Governance，再重跑正式 Agent 与 Golden Evaluation。
- 完成 authenticated browser UAT、staging PostgreSQL、concurrency/locking、backup/restore、security/performance/driver matrix 后，才能进入 release qualification。

## Gate Decision

`REAL_AGENT_BENCHMARK_PARTIAL`：真实 LLM + 真实 Embedding + 真实 Milvus + 17 字段均已尝试，但 7 个字段存在真实 provider/validation 失败，因此禁止判定 PASS；Golden 评估仅作已完成字段与全量部分输出的离线审计，不能替代完整 PASS 门槛。
