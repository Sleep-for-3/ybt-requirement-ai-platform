# Product 5.1 Runtime、Benchmark 与 UAT 收口报告

日期：2026-08-31
本地基线：`2c25ea8`（包含 `6a3d81a`、`4471959`）
远端参考：`origin/main = b31faea8e3b5f20fea36a736d0290edf1aeebb7d`
发布动作：未 push

## 结论

- Runtime：真实且就绪。
- Real Agent：`REAL_AGENT_BENCHMARK_PASS`。
- 产品成熟度：`Internal Product`。

Real Agent PASS 只表示真实运行、结构化输出和后验评估已完成；它不等于语义绑定全部人工确认、质量检测通过或正式监管交付已放行。

## Runtime 配置收口

| 组件 | 最终来源 | 实际状态 |
|---|---|---|
| LLM | active `ModelProfile`（无 profile 时回退 Settings） | `openai_compatible`，`gpt-5.6-sol`，ready |
| Embedding | production 启停脚本注入的本地 FastEmbed endpoint | `local_vllm`，`BAAI/bge-small-zh-v1.5`，512 维，ready |
| Vector | Settings/启停脚本 | Milvus，reachable |
| Semantic index | 正式索引表 + Milvus collection | ready，active index 2 |
| Generator | `get_prompt_runtime` → `get_runtime_llm_service` | `OpenAICompatibleLLMService` / 同一 active profile |

启动脚本现在把 SQLite 模式显式隔离为 mock，并识别遗留的本地 FastEmbed 配置；生产模式在需要时启动并自检 512 维 FastEmbed。此前 `embedding_dimension_missing` 的原因是测试/SQLite 或旧进程环境继承了生产 Milvus 配置，却没有把维度带入；该路径已修复，测试也不再继承开发者的 ignored `.env`。

Runtime 诊断只返回 provider、model、Base URL host、维度、向量可达性、索引状态和 Generator service 类型，不返回密钥或 Authorization header。`configuration_drift=false`。

## API 兼容性与错误契约

- 第三方 OpenAI-compatible `/v1/models`、普通 chat smoke 和 JSON mode smoke 均 HTTP 200。
- 站点对 JSON mode 的消息格式有额外要求，正式 profile 使用现有 `json_mode=false` 与 Structured Response validator 兼容；未新增 provider framework。
- 后端 `user_message` 按 HTTP 状态稳定返回中文：401 登录失效、403 无权操作、404 资源不可见、409 状态冲突、422 输入不完整、500 服务器处理失败、503 依赖暂不可用。
- Admin Health 前端按 401/403/500/503/network 分层，不再把网络或依赖故障说成权限问题；业务用户看不到 Python stack，支持人员可使用 trace id。

## 17 字段真实 Agent Benchmark

Agent 阶段没有读取 `demo/product_5_1/expected/golden_mapping.json`。E010010（产品期限）先通过 smoke gate，随后 17 个字段均有结构化结果（17/17）。最终 artifact 对已存在的真实草稿采用幂等复用；早期 `sol_retry`/`sol_final` 记录了真实模型调用，复用不冒充新的模型请求。

### Golden Evaluation（生成完成后离线读取）

| 指标 | 结果 |
|---|---:|
| Target → Mart | 17/17（100%） |
| Mart → Source | 15/17（88%） |
| Transformation | 10/17（59%） |
| Evidence Citation | 17/17（100%） |
| Semantic Match | 17/17（100%） |
| Hallucinated Asset Count | 0（complete 字段启发式；需人工复核） |
| Missing Required Source Count | 7 |
| Open Question Precision | complete 字段已记录；不把开放问题当作已解决 |

逐字段结果和上下文事实见 [`PRODUCT_5_1_REAL_BENCHMARK.md`](./PRODUCT_5_1_REAL_BENCHMARK.md)。低命中映射、来源和转换仍需人工治理，未修改 Golden Truth。

### 成本与可追溯性

ModelCallLog 累计：100 requests；prompt 383,265；completion 42,390；total 425,655；cached 43,439。没有 usage 的请求标记 unavailable，未猜测费用，也没有无限重试。

## 关键数据链路

### Target Lineage

重新 ingestion 后，产品类别（E010007）、产品期限（E010010）、产品状态代码（E010015）、代客产品所属机构名称（E010018）均可查询 `Target → Mart → Source`；返回节点已解析。全项目 69 个 unresolved 节点保留并分类：parser/constant 5、外部或未导入 Catalog 资产 60、Catalog resolution 4；没有为清零而创建假绑定。

### Metadata Drift

结构不变时重复同步完成，第二次新增 drift 为 0；7/7 jobs completed，schema/table/column 计数稳定。

### SQL Impact

v1 → v2 变更集 impact `40`（critical）已传播：18 个 Mart fields、17 个 Target fields、17 个 Requirements、3 个 ReviewTasks。现有 Impact Engine 的路径为 `SQL Change → Source → Mart → Target → Semantic → Requirement → ReviewTask`。

## Semantic Governance 与 Human Review

以下关键概念已真实完成 evidence-backed human confirm，并形成有效版本：Product、ProductCategory、ProductTerm、ProductStatus、AgencyInstitution、ReportingInstitution。其余 bindings 仍可能是 `ai_suggested`，不能批量标记 confirmed；Generator 对缺少 confirmed binding 的场景保留 open question。

真实 workflow `36` 已完成 `AI Draft → Human Edit → Business Review → Technical Review → Final Review → Final`，5 个阶段任务、5 个决定和 approved package 均有审计记录。后续 AI 不会覆盖 Human Final；对已批准 technical lineage 的非法修改返回 409。

## 认证浏览器 UAT

Smoke 平台管理员认证后，以下生产 bundle 路径已实测通过：

- 系统管理：`/admin`、`/admin/institutions`、`/admin/users`、`/admin/permissions`、`/admin/health`；无 404，breadcrumb 和二级导航一致，权限首屏为中文，技术标识渐进展示。
- 监管驾驶舱：`/cockpit` 可进入并显示 5 个授权项目；未把服务错误误报为项目权限问题。
- 工作与口径：`/work`、`/workspace`、`/tasks/85`；监管定义、AI 草稿、Evidence、解释面板、保存/人工最终内容和任务上下文可见。
- 影响分析：`/lineage/impacts/40`；业务故事、影响路径、监管影响、待处理事项和技术详情折叠可见。

尚未宣称通过的范围：普通项目用户/机构管理员的完整权限矩阵、故障注入的 partial/system-error 浏览器场景、四种桌面视口和全站键盘可访问性；这些仍是 release qualification 工作。

## Impact Story

Impact 页面已复用现有 ChangeSet、Lineage、Semantic、Requirement 和 ReviewTask 数据，默认回答“发生了什么、为什么重要、影响范围、影响路径、谁要处理/下一步是什么”；SQL diff、原始摘要和内部 ID 只在“技术详情”展开，没有新增第二套 Impact Engine 或让 AI 编写无行动价值的长篇说明。

## 已修复 P0/P1 与剩余问题

已修复：

1. `/admin` canonical 路由、统一 AdminShell 和 capability contract（历史 P0）。
2. Cockpit 401/403/404/500/network/partial 分层及单项目容错（历史 P0/P1）。
3. 真实 Runtime 启停与 512 维 embedding readiness 漂移。
4. 401/403 等错误的英文透传和 Admin Health catch-all 权限提示。
5. Work/Requirement/Impact 核心路径的中文产品语言、AI Explanation、Unsaved Protection 和业务化 Impact Story。

仍存在：

- Quality Execution 尚未形成可审计执行结果；正式 Deliverable 尚未满足 release readiness。
- 69 个 unresolved lineage 节点中有外部资产和 parser limitation，需按分类治理。
- 部分 semantic bindings 仍为 `ai_suggested`；Golden 低命中来源/转换需人工确认。
- Work 后端摘要尚未完整提供风险、负责人和等待时长；全站 Error/Empty/Loading、Recent/Favorite、键盘/视口 UAT 仍不完整。
- staging PostgreSQL、并发/锁、备份恢复、安全、性能和驱动矩阵尚未完成。

## 测试门禁

| 检查项 | 结果 |
|---|---|
| Backend targeted tests | 通过（相关 runtime/governance/health/model-profile 用例） |
| Backend full pytest | `496 passed, 6 warnings` |
| Frontend tests | `104 passed` |
| TypeScript | `npx tsc --noEmit` 通过 |
| Lint | `next lint` 通过；仅既有 React Hook dependency warnings |
| Production build | `next build` 通过 |
| Python compile | `python -m compileall -q app` 通过 |
| Diff check | `git diff --check` 通过 |

浏览器 UAT 与 release qualification 的未覆盖范围仍按上文标记为 pending/blocked；本报告不把未执行的多角色、故障注入、四视口或完整可访问性检查写成通过。

## 最终判断

`REAL_AGENT_BENCHMARK_PASS`；产品成熟度 `Internal Product`。下一步优先级是语义/映射人工治理、Quality Execution、正式 Deliverable 和完整认证 UAT，而不是继续增加图表或页面。
