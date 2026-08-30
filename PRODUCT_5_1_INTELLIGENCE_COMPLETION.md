# Product 5.1 End-to-End Intelligence Completion

报告日期：2026-08-30
验证基线：`origin/main = b31faea8e3b5f20fea36a736d0290edf1aeebb7d`
本地工作分支：`codex/frontend-rebuild-requirement-workspace`

本轮严格保留既有 Product 5.1 Demo 数据集（1,280 products、7 datasources、57 tables、312 columns、17 target fields、14 semantic concepts、13 scenarios），未读取 Golden Mapping 作为 Agent Context，也未伪造 Agent、Evaluation、Quality、Review 或 Deliverable 结果。

## Gate 结论

| Gate | 状态 | 证据与未完成项 |
| --- | --- | --- |
| Real LLM Runtime | **BLOCKED** | 本机只有 backend `8000` 与 frontend `3000` 监听；没有 `11434` Ollama/vLLM 或其它模型服务。当前 `LLM_PROVIDER=mock`、model=`mock-llm`。需启动受支持的 OpenAI-compatible/vLLM/Ollama endpoint，并配置 model name；不得把 mock 结果计为真实运行。 |
| Real Embedding | **BLOCKED** | 当前 `EMBEDDING_PROVIDER=mock`、model=`mock-embedding`，没有 embedding endpoint。需配置真实 embedding provider、model 与 dimension。 |
| Real Vector Retrieval | **BLOCKED** | `VECTOR_STORE_PROVIDER=mock`，Milvus `19530` 未监听，semantic index/向量检索 disabled。需先启动 Milvus 并完成索引验证。 |
| 17-field Agent Generation | **BLOCKED** | `scripts/demo/run_product_5_1_verification.py` 在 mock runtime 下明确不调用 Generator，17 字段没有 AI Draft。 |
| Golden Evaluation | **BLOCKED** | 因没有真实 Agent 输出，Target→Mart、Mart→Source、Transformation、Evidence、Semantic、Hallucination、Missing Source、Open Question 等指标均保持 N/A；Golden Truth 仍只用于后验比较。 |
| Target Lineage | **PARTIAL** | 修复 `resolver.py`：Target 节点现在支持从稳定编码/名称及 bootstrap 写入的物理字段元数据解析。新增回归测试；对现有 Demo 数据库只读演算显示 34/34 个 Target column nodes 可解析，但未直接改写历史 Demo DB。需重新 ingestion/resolution 后再做浏览器/API UAT。 |
| Requirement Impact | **PARTIAL** | 既有 `persist_change_impact` 已能沿 Target→Scenario Mapping→Semantic→Requirement 传播；测试覆盖 requirement id。历史 v1→v2 Impact 仍是旧快照（Target=0、Requirement=0），必须在 Target resolution 生效后重新运行 v1→v2，不能手工改指标。 |
| Human Governance | **BLOCKED** | 当前没有真实 AI Draft，因此没有高置信度、人工修改、Open Question 三类真实审核样本，也没有 Business→Technical→Final 的最终内容闭环。 |
| Quality Execution | **BLOCKED** | 代码库只有 `DataQualityExpectation`/binding 配置 API，没有正式 Execution Service、Result 实例或 `tested_rows/failed_rows/failure_rate` 结果表；10 条 expectation 不能当质量分。 |
| Formal Deliverable | **BLOCKED** | Renderer/Template API 已存在，但 Demo 没有满足 readiness 的正式模板版本、最终审核结果或正式生成包；不得生成伪正式交付物。 |
| Metadata Drift deduplication | **PASS (logic)** / **PARTIAL (history)** | 增加 deterministic repeated-sync 回归测试：相同 schema/table/column 第二次 full sync 新增 drift=0；真实变化仍产生事件。历史 Demo DB 中已有的 369 条 drift 未被删除或重写。 |
| Project Dashboard contract | **PARTIAL** | 修复前端在未登录时无限等待/空白的问题，增加登录门禁、请求超时、`allSettled` 部分数据容错和 401/403/404/500/network 产品化提示。当前会话未登录，因此未宣称 authenticated browser UAT 已通过。 |

## 已实施修改

- `backend/app/services/lineage/resolver.py`：Target Field resolution 支持 `internal_definition` 中的物理列元数据，同时保留 `field_code`、字段名称和报告字段名称作为稳定候选；不改变 permission code 或数据库语义。
- `backend/tests/test_sql_lineage.py`：新增 Target physical column resolution 红色回归测试。
- `backend/tests/test_metadata_catalog.py`：新增 repeated full-sync drift=0 回归断言。
- `frontend/app/projects/[projectId]/dashboard/page.tsx`：避免未登录页面静默空白；Dashboard 与 Analytics 分离加载，错误按真实类别展示，不再把所有失败归因于项目权限。

## 真实 Runtime 启动要求

项目已有正式 provider 工厂，不应新建第二套 LLM framework。启动前应在 backend 环境中配置：

```text
LLM_PROVIDER=openai_compatible 或 local_vllm/ollama_compatible
LLM_BASE_URL=http://<model-service>/v1
LLM_MODEL=<实际模型名>
EMBEDDING_PROVIDER=openai_compatible/local_vllm/fastembed
EMBEDDING_BASE_URL=http://<embedding-service>/v1
EMBEDDING_MODEL=<实际 embedding 模型名>
EMBEDDING_DIMENSION=<模型真实维度>
VECTOR_STORE_PROVIDER=milvus
MILVUS_URI=http://<milvus-host>:19530
```

云 provider 的 API key 只能通过 `OPENAI_API_KEY`/`EMBEDDING_API_KEY` 等环境变量注入；本报告不记录任何 secret。启动后必须先访问 `/api/ai-runtime/status`，核对 provider、model identity、非 mock 标记与连接测试，再运行 17-field Generator。

## 验证记录

- Target lineage 定向测试：2 passed。
- Metadata drift 定向测试：1 passed。
- 前端 TypeScript：通过。
- 本地浏览器未登录复现：原页面会停在加载态；修复后显示“请先登录后查看项目驾驶舱”，不再伪装成权限失败。
- 本轮后端全量复跑（排除会打开交互式启停菜单的 Windows launcher test）：491 passed、1 deselected、5 warnings。被排除用例是交互式控制台行为测试，不是业务失败。
- 既有前端基线：99 passed、2 个浏览器测试因 CDP `Page.navigate` 8 秒超时失败，属于浏览器环境超时，不是 Product 5.1 断言失败；本轮新增 Dashboard 合同测试后，前端测试总数为 103 passed。

## 仍未关闭的 release gates

1. 启动并验证真实 LLM、Embedding、Milvus；随后对全部 17 fields 运行真实 Generator。
2. 读取 Golden Mapping 进行字段级后验 Evaluation，并输出逐字段 artifact。
3. 重新 ingestion/resolution 后重跑 v1→v2 Impact，验证 Target 与 Requirement propagation。
4. 通过真实 Governance API 确认关键 semantic，完成三类 Human Review 样本并证明 Human Final 不被 AI 覆盖。
5. 实现/接入正式 Quality Execution 与结果审计。
6. 配置正式 Deliverable Template，满足 readiness、review 和 renderer 校验后再生成包。
7. 使用已认证会话完成 authenticated browser UAT；再在 staging PostgreSQL 做 migration、并发/锁、备份恢复、driver matrix、安全和性能验证。

因此，本轮不能把 Product 5.1 标记为“End-to-End Intelligence Complete”或 Production Ready；诚实状态为 **Internal Product / Intelligence Completion Blocked**。
