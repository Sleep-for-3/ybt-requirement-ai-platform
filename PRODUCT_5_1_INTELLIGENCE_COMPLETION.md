# Product 5.1 End-to-End Intelligence Completion

报告日期：2026-08-31
验证基线：本地 `2c25ea8`（`origin/main = b31faea8e3b5f20fea36a736d0290edf1aeebb7d`）
本地工作分支：Product 5.1 runtime bring-up 工作分支

本轮严格保留既有 Product 5.1 Demo 数据集（1,280 products、7 datasources、57 tables、312 columns、17 target fields、14 semantic concepts、13 scenarios），未读取 Golden Mapping 作为 Agent Context，也未伪造 Agent、Evaluation、Quality、Review 或 Deliverable 结果。

## Gate 结论

| Gate | 状态 | 证据与未完成项 |
| --- | --- | --- |
| Real LLM Runtime | **PASS** | production 启动后 active ModelProfile 使用 `openai_compatible / gpt-5.6-sol`，健康检查和 Generator diagnostic 均为非 mock。 |
| Real Embedding | **PASS** | 本地 FastEmbed `BAAI/bge-small-zh-v1.5`，512 维，`/v1/embeddings` 自检通过。 |
| Real Vector Retrieval | **PASS** | `VECTOR_STORE_PROVIDER=milvus`，Milvus reachable，semantic index active。 |
| 17-field Agent Generation | **PASS** | 17/17 字段有真实 Runtime 结构化结果；最终 artifact 对已有成功草稿做幂等复用并明确标记。 |
| Golden Evaluation | **PASS (后验)** | 仅在 Agent 阶段完成后读取 Golden Truth；指标和逐字段结果见 `PRODUCT_5_1_REAL_BENCHMARK.md`。 |
| Target Lineage | **PASS（重点字段）** | Target resolver 支持物理字段元数据；E010007/E010010/E010015/E010018 可查询 Target→Mart→Source。69 个非核心 unresolved 节点按类别保留。 |
| Requirement Impact | **PASS** | 重新运行 v1→v2 后 impact 40 已传播到 17 Target、17 Requirement、3 ReviewTask。 |
| Human Governance | **PARTIAL** | 关键 6 个 Semantic Concept 已完成 evidence-backed confirm；其余 bindings 仍有 `ai_suggested`，需继续治理。 |
| Quality Execution | **BLOCKED** | 代码库只有 `DataQualityExpectation`/binding 配置 API，没有正式 Execution Service、Result 实例或 `tested_rows/failed_rows/failure_rate` 结果表；10 条 expectation 不能当质量分。 |
| Formal Deliverable | **BLOCKED** | Renderer/Template API 已存在，但 Demo 没有满足 readiness 的正式模板版本、最终审核结果或正式生成包；不得生成伪正式交付物。 |
| Metadata Drift deduplication | **PASS (logic)** / **PARTIAL (history)** | 相同 schema/table/column 第二次 full sync 新增 drift=0；历史事件保留不重写。 |
| Project Dashboard contract | **PASS（核心路径）** | 未登录门禁、超时、部分数据容错和 401/403/404/500/network 产品化提示已验证；Smoke 管理员核心浏览器 UAT 通过。 |

## 已实施修改

- `backend/app/services/lineage/resolver.py`：Target Field resolution 支持 `internal_definition` 中的物理列元数据，同时保留 `field_code`、字段名称和报告字段名称作为稳定候选；不改变 permission code 或数据库语义。
- `backend/tests/test_sql_lineage.py`：新增 Target physical column resolution 红色回归测试。
- `backend/tests/test_metadata_catalog.py`：新增 repeated full-sync drift=0 回归断言。
- `frontend/app/projects/[projectId]/dashboard/page.tsx`：避免未登录页面静默空白；Dashboard 与 Analytics 分离加载，错误按真实类别展示，不再把所有失败归因于项目权限。
- `backend/app/core/settings.py`、`backend/app/services/llm/providers.py`、`scripts/项目启停.ps1`：统一环境文件解析、生产 FastEmbed 512 维注入和 SQLite/production runtime 隔离。
- `backend/app/main.py`、`backend/tests/test_health.py`、`frontend/app/admin/system-health/page.tsx`：统一错误契约和平台健康页错误分类。
- `frontend/app/lineage/impacts/[impactId]/page.tsx`：将现有 Impact Engine 结果呈现为可行动的业务故事。

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

云 provider 的 API key 只能通过环境变量注入；本报告不记录任何 secret。启动后必须先访问 `/api/ai-runtime/status`，核对 provider、model identity、非 mock 标记、512 维、Milvus 可达性和 Generator effective runtime，再运行 17-field Generator。生产启停脚本负责注入本地 FastEmbed 变量；SQLite 模式显式使用 mock，避免配置串线。

## 验证记录

- Target lineage 定向测试：2 passed。
- Metadata drift 定向测试：1 passed。
- 前端 TypeScript：通过。
- 本地浏览器未登录复现：原页面会停在加载态；修复后显示“请先登录后查看项目驾驶舱”，不再伪装成权限失败。
- 后端测试在隔离 mock 环境下通过；最终全量数字以本轮提交前门禁记录为准。Windows 交互式启停菜单用例按平台行为单独执行。
- 前端测试：104 passed；TypeScript、lint 和 production build 以本轮最终门禁为准。

## 仍未关闭的 release gates

1. 对 Golden 低命中来源与转换进行人工治理和候选资产校准，不修改 Golden Truth。
2. 扩大 Semantic/Mapping 人工确认覆盖，并重建可信 Context。
3. 完成多角色 authenticated browser UAT、四桌面视口和异常依赖场景。
4. 实现/接入正式 Quality Execution 与结果审计。
5. 配置正式 Deliverable Template，满足 readiness、review 和 renderer 校验后再生成包。
6. 在 staging PostgreSQL 做 migration、并发/锁、备份恢复、driver matrix、安全和性能验证。

因此，Product 5.1 的真实 Agent intelligence gate 已完成，但仍不是 Production Ready；诚实状态为 **Internal Product / Runtime and Agent Complete, Governance and Release Gates Open**。
