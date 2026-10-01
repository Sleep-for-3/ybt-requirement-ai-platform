# Banking Semantic Agent V2 — 最终验收与交付报告

分支：`dsh/banking-semantic-agent-v2`（基于 `dsh/agent-orchestrator-v1 @ fb04b81`）
远端：`https://github.com/Sleep-for-3/ybt-requirement-ai-platform`
本机部署：后端 8000（ready，迁移 head `202610020051`）、前端 3000（V2 构建 `3BrVHZdoiHu-Nz_69DKXd`）、Celery worker+beat、便携 PG/Redis/Milvus Lite。

目标达成方式：**在 V1 上增量扩展，未推倒重来、未引入 Multi-Agent、未新增框架**。所有能力仍在
`Agent Runtime + Tool Registry + ReviewTask/审计台账` 之内。

---

## 1. 阶段与提交

| 阶段 | 内容 | Commit |
|---|---|---|
| 2.1 | 依赖语义（ALL required + optional/blocked/skipped/waiting_human 矩阵） | `3c1c6e5` |
| 2.2 | 严格 Plan Validation + 一次自我修复 + 确定性回退 | `d5326a6` |
| 3a | Subject Resolution V2 + Scenario Router + 4 场景计划 + 人工澄清网关 | `5631092` |
| 3b | 结构化 Observe 状态 + 计划补丁 + 运行时观察点（默认 LLM 规划） | `713f590` `2d572ad` |
| 4 | Decision/Case Memory + 人工反馈闭环 + `search_decision_cases` 工具 | `7316675` `2c51777` `4c66b3d` |
| 5 | SQL Change Event Agent（semantic_hash 去重 + 导入自动触发 + API） | `9778b69` |
| 6 | SQL Semantic Diff V2（fact/interpretation + 39 族覆盖表） | `b489ddb` |
| 7 | Role-based Human Gate（single/any/all + 权限跟随角色 + 双人批准） | `b805b83` `2ebb264` |
| 8 | 每步 `model_execution`（模型未执行 vs 成功，显式区分） | `5bf2851` |
| 9 | Agent Evaluation V2（21 项指标，无分母返回 null） | `7a0c76e` |
| 10 | Agent Workspace V2（6 个新面板，前端构建通过并浏览器验收） | `e24e072` |
| 11 | 单执行者租约（并发）+ 中断步骤恢复（崩溃幂等） | `e139fc9` `1027514` |
| 快照/文档 | 场景路由与 adaptive 暴露、开发记录维护 | `7b7b3b7` `396e179` 等 |

## 2. 架构（V2 增量）

```
业务目标
  ↓ Scenario Router（Stage A 规则打分 → confidence/rationale/alternatives；Stage B 只接受注册表内场景）
  ↓ Subject Resolution V2（resolved / ambiguous / not_found；候选带分值+匹配来源；禁止静默兜底）
  ↓ Adaptive Planner（LLM 优先 → 严格校验 → 一次自我修复 → 失败回退受治理确定性计划并记录原因）
  ↓ Execution（ALL required 依赖；open gate 暂停整链；单执行者租约；中断恢复）
  ↓ Observe（结构化有界状态 + digest 字符上限）
  ↓ Replan（计划补丁：新增/改未执行/删可选/标缺口/请人工；已完成与已确认决策不可动）
  ↓ Human Gate（review_policy single/any/all，按角色路由，权限跟随角色）
  ↓ Artifact + Evidence + Gap + 审计
```

## 3. 新增数据模型（8 张表）

| 表 | 说明 | 迁移 |
|---|---|---|
| `agent_tasks` / `agent_plans` / `agent_steps` / `agent_tool_calls` / `agent_human_decisions` / `agent_artifacts` | V1 六表；V2 增 `agent_steps.optional_depends_on_json`、`agent_plans.validation_errors_json/planner_attempts`、`agent_tasks.adaptive/run_lease_until` | `202610010045` `202610020046` `202610020047` `202610020049` `202610020051` |
| `decision_cases` | 人工确认的企业经验（领域/主体/决策/理由/证据/监管引用/关联 mapping·requirement·script/审批人/confidence_source/生效区间/状态） | `202610020048` |
| `sql_change_events` | SQL 语义变更事件与幂等锚点（project+script+old/new version+semantic_hash 唯一） | `202610020050` |

**关键治理约束**：证据必须引用事实/条款；SQL 事实永不能作监管依据（`policy_clause_ids` 恒空）；
历史人工决策一律 `source_type=historical_decision` 且 `case_is_regulatory_basis()` 恒 False；
交付物在人工确认前只能 draft。

## 4. 新增 API

| 方法 | 路径 | 权限 |
|---|---|---|
| GET | `/api/agent/tools` | 登录（可按项目过滤） |
| POST/GET | `/api/projects/{id}/agent/tasks` | `task.manage` / `project.view` |
| GET | `/api/agent/tasks/{id}` | `project.view` |
| POST | `/api/agent/tasks/{id}/cancel|retry|replan|resume` | `task.manage` |
| POST | `/api/agent/tasks/{id}/steps/{step_id}/decision` | 网关路由角色的权限 |
| GET | `/api/projects/{id}/agent/metrics` | `project.view` |
| POST | `/api/projects/{id}/agent/sql-change-events` | `task.manage` |

## 5. Tool Registry（17 个受治理工具）

V1 的 15 个 + `compare_sql_versions`（SQL 语义差异，high/只读/需人工确认）+ `search_decision_cases`
（历史决策检索，low/只读，`fact_kinds=[historical_decision]`，`policy_kinds=[]`）。
每个工具规格含权限、风险、超时、重试、只读、是否需人工确认、证据契约与审计字段；**规格不合格拒绝注册**。

## 6. 状态机与依赖语义

- 步骤 7 态、任务 8 态，非法跃迁抛 `AgentStateError`。
- 依赖矩阵：required ×（completed→满足 / failed·blocked→阻断 / skipped→跳过+`dependency_gap` /
  waiting_human→整链暂停 / pending·absent→等待）；optional 缺失→仍执行但记 `optional_dependency_missing`。
- 运行结束时对"永不可能执行"的下游步骤做**显式结算**（blocked/skipped + 依赖评估落库）。

## 7. Planner

- 4 个确定性场景计划：`regulatory_field_analysis`（15 步，`requirement_generation` 复用）、
  `sql_change_impact`（9 步）、`mapping_resolution`（10 步，含可选历史案例检索）。
- 约束式 LLM 规划：只能选注册表内 tool_key、依赖只能前置、输出必须通过 20 项校验，
  失败**回灌错误修复一次**，再失败→`planner_source=fallback` + 原始错误落库（绝不显示为 AI 成功）。
- Observe→Replan：每成功一步最多观察 3 次（受重规划预算约束），模型提出 5 类计划补丁，
  只能动未执行步骤；补丁非法/模型不可用→记录原因并继续当前计划。

## 8. 验收 Demo 证据

| Demo | 期望 | 证据 |
|---|---|---|
| 1｜分析二级市场福费廷报送需求 | 场景→主体→计划→监管→元数据→召回→重排→SQL→血缘→比对→映射→人工→需求→文档→证据→缺口 | `tests/test_agent_acceptance.py::test_regulatory_field_analysis_reaches_gates_with_governed_evidence`（真实工具链，15 步、5 个人工网关、5 个交付物、12 条证据）；Phase 6 本机 HTTP 现场记录（`.local-run/agent-live-acceptance.json`）与浏览器现场（V1 期已验证，V2 构建再度验收面板） |
| 2｜SQL 变更影响（不跑需求全链） | 识别 `sql_change_impact` → 语义差异→SQL→血缘→影响→元数据→条款→比对→证据→缺口 | `tests/test_agent_sql_change_events.py`（哈希忽略格式、变更建单、去重）+ `tests/test_agent_sql_semantic_diff.py`、`test_sql_semantic_diff_v2.py`（52 passed） |
| 3｜字段映射定位 | 元数据→召回→历史案例（可选）→重排→血缘→SQL→建议→人工确认 | 计划构造与校验断言见 `test_agent_decision_case_tool.py::test_the_mapping_scenario_uses_cases_as_optional_context`；工具级行为见 `test_agent_ai_skill_tools.py`、`test_agent_decision_case_tool.py` |
| 4｜SQL 语义变化自动触发 + 重复导入不重复建单 | `status IS NOT NULL` → `IN ('ACTIVE','MATURED')` 自动检测建单；重复导入去重 | `test_agent_sql_change_events.py::test_a_semantic_change_creates_one_task_and_dedups_on_repeat`、`test_a_format_only_change_detects_nothing` |
| 5｜主体歧义（账户/贷款/授信余额） | **不允许默认第一条**，`ambiguous` + 人工澄清网关，人工选后继续 | `test_agent_subject_resolution.py`（10 例）+ `test_agent_acceptance.py::test_an_unresolvable_subject_asks_a_human_instead_of_guessing` |

## 9. 测试与回归

```
$env:TASK_QUEUE_PROVIDER='inline'; $env:AUTH_MODE='optional'
.venv\Scripts\python.exe -m pytest <agent 全量 19 套件> tests/test_governance.py -q   # → 168 passed
```
| 套件 | 例数 | 主题 |
|---|---|---|
| state_machine / tool_registry / runtime | 6 / 9 / 12 | 状态机、注册表治理、执行+审计+幂等+超时+权限 |
| dependencies / dependency_runtime | 11 / 6 | 依赖矩阵与运行时行为 |
| planner_validation | 13 | 20 项校验 + 修复一次 + 回退 |
| subject_resolution | 10 | resolved/ambiguous/not_found 与候选 |
| observation / adaptive_replan | 6 / 8 | 有界状态与计划补丁 |
| case_memory / case_loop / decision_case_tool | 14 / 3 / 4 | 经验记忆硬规则与闭环 |
| sql_change_events / sql_semantic_diff(×2) | 6 / 5+ | 事件去重与 fact/interpretation |
| gate_routing | 6 | 单/any/all 路由与双人批准 |
| concurrency / crash_recovery | 6 / 5 | 单执行者租约与崩溃点幂等 |
| model_execution | 5 | 模型未执行 vs 成功 |
| evaluation_v2 | 6 | 21 项指标与 null 语义 |
| acceptance ×3 | 3 | 主链路、无依据不得出文档、歧义主体须问人 |
| migration_schema_freeze | 3 | 迁移链与 ORM 契约一致 |
前端：`agent-workspace-v2` 30 + `agent-workspace`/`navigation-contract` 21 = **51 passed**；
`tsc --noEmit`、`eslint` exit 0；`next build` exit 0；浏览器验收 `/agent` 面板齐全、0 错误。

## 10. 与基线的对照

**保留未动**：Skill Runtime/发布/绑定/Evaluation、RAG（HybridRetriever）、Metadata、Mapping、
Lineage、Requirement、权限服务、ReviewTask/ReviewDecision/Workflow、AuditLog、BackgroundJob/任务队列、
Migration Freeze 门禁、前端既有页面与导航契约。**AI 全程无自动合规结论、无自动生产写、无自注册工具、
无绕过人工网关、无改动已确认人工决策、无绕过审计。**

## 11. 已知限制与技术债

1. **真实内网模型链路未在本机验证**：`model_execution` 契约与降级可见性已完整实现并测试；
   真实 provider 的端到端链路需在银行内网环境复验（模型未配置时一律显示"模型未执行"）。
2. `generate_business_draft` 内部自行 commit（V1 遗留），编排器无法完全拥有该步骤事务边界。
3. Evidence Budget / Tool Output Budget 目前只落实到 observation digest 的字符上限，未做显式配额。
4. SQL 语义差异对 39 族中 **29 族可检**，10 族（GROUP BY 粒度、DISTINCT、UNION/UNION ALL、HAVING、
   ORDER BY、TOP/LIMIT、LEFT/INNER/FULL JOIN、CTE）由比较器能力所限**显式列为 unsupported**，
   不伪造检测结果；29 族为比较器类别粒度（如 `>`↔`>=` 归为谓词级 `filter_changed`）。
5. 4 个指标（scenario/evidence_recall/sql_semantic_recall·false_positive/impact_propagation）
   在缺少标注基准集时返回 null（附 `metric_notes` 原因），不美化。
6. `subject_resolution_accuracy` 为运行口径代理，不是标注准确率。
7. 人工网关按角色路由时会跳过项目未配置的角色（记 `unstaffed_fallback`），避免网关死锁。

## 12. 下一阶段建议

1. 在银行内网完成真实模型链路复验（field rerank / policy comparison / mapping / requirement /
   document 五个技能），并固化基线指标。
2. 补齐 10 个 SQL 语义族的比较器能力（GROUP BY keys、JOIN 类型、DISTINCT/UNION、HAVING、ORDER BY、
   TOP/LIMIT、CTE），并为其建立标注用例集，把 sql_semantic_recall/false_positive 从 null 变为真实值。
3. 事务边界改造（把 `generate_business_draft` 的 commit 上移到运行时）。
4. Context/Evidence Budget 显式配额与超限降级策略。
5. 建立 Agent 标注基准集（scenario/subject/impact 三张标签表），驱动 4 个 null 指标转正。
6. 若单 Agent 在某类复杂任务上被证明不足，再按文档化设计评估 Multi-Agent（本阶段明确不做）。
