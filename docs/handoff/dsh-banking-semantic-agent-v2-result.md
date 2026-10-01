# Banking Semantic Agent V2 — 开发与验收记录

分支：`dsh/banking-semantic-agent-v2`（基于 `dsh/agent-orchestrator-v1 @ fb04b81`）
状态：**进行中**（Phase 1–2 完成；Phase 3 主体完成，Adaptive Observe→Replan 待续；Phase 9 指标已完成）

本文件按阶段持续更新：完成阶段 / 架构 / 新增模型 / 新增 API / Tool Registry / Scenario /
Evaluation / Test Results / Live Acceptance / Git Commit / 已知限制 / 下一阶段。

---

## 1. 阶段进度

| 阶段 | 内容 | 状态 | Commit |
|---|---|---|---|
| 2.1 | 修复多依赖执行语义（ALL required） | ✅ 完成 | `3c1c6e5` |
| 2.2 | 严格 Plan Validation（+一次自我修复+确定性回退） | ✅ 完成 | `d5326a6` |
| 3a | Subject Resolution V2 + Scenario Router + 4 Scenario 计划 + 人工澄清网关 | ✅ 完成 | `5631092` |
| 3b | Adaptive Observe→Replan（结构化状态 + 计划补丁） | ⏳ 进行中 | |
| 4 | Decision / Case Memory + search_decision_cases | ⏳ | |
| 5 | SQL Change Event Agent（semantic_hash + 去重 + 自动 Task） | ⏳ | |
| 6 | SQL Semantic Diff V2（semantic_fact + interpretation） | ⏳ | |
| 7 | Role-based Human Gate（review_policy: single/all/any） | ⏳ | |
| 8 | 真实模型 Skill 链路与降级可见性 | ⏳ | |
| 9 | Agent Evaluation V2 指标（21 项，无分母返回 null） | ✅ 完成 | `7a0c76e` |
| 10 | Agent Workspace V2 + 前端验收 | ⏳ | |
| 11 | 并发/重启/幂等/事务边界/Context Budget | ⏳ | |

## 2. 架构（V2 增量，不推倒 V1）

```
业务目标
  ↓ Scenario Router（规则 A + LLM B，输出 scenario_key/confidence/rationale/alternatives/clarification）
  ↓ Subject Resolution V2（resolved / ambiguous / not_found，禁止静默兜底）
  ↓ Adaptive Planner（LLM 优先，严格校验，一次自我修复，失败→governed deterministic fallback）
  ↓ Execution（ALL required 依赖语义；open gate 暂停整链）
  ↓ Observe（结构化状态：completed_steps/evidence_summary/gaps/unresolved_questions/budget）
  ↓ Replan（保留/新增/删除未执行/改参/标 gap/请人工；已完成与已确认决策不可动）
  ↓ Final Artifact + Evidence + Gap + Human Decision
```

V1 的 6 张表、Tool Registry、Runtime、HITL、Observability、Workspace 全部保留并增量扩展。

## 3. 已完成阶段详情

### Phase 2.1 — 依赖语义修复（`3c1c6e5`）

V1 的 `any(dependency completed)` 会让步骤在必需前驱失败/跳过/等待人工时照常执行。新增
`app/services/agent/dependencies.py` 定义完整矩阵：

| 依赖 | 状态 | 处置 |
|---|---|---|
| required | completed | satisfied |
| required | failed / blocked | `block` → 步骤 blocked（`dependency_failed`），绝不当成功 |
| required | skipped | `skip` → 步骤 skipped + `dependency_gap`，任务标记 `incomplete` |
| required | waiting_human | `pause` → 整链暂停，下游保持 pending |
| required | pending/running/absent | `wait` |
| optional | completed | satisfied |
| optional | 其他 | 仍可执行，但记录 `optional_dependency_missing` 缺口 |

配套：`AgentStep.optional_depends_on_json`（迁移 `202610020046`）；阻塞/失败时对下游做
**显式结算**（blocked/skipped + 依赖评估落库），不再让下游静默 pending；工具成功的 gap 写入
改为**并集**，不再覆盖依赖缺口。

测试：`tests/test_agent_dependencies.py`（11 例矩阵）+ `tests/test_agent_dependency_runtime.py`
（6 例：blocked 依赖、skipped 依赖、optional 缺口、gate 暂停、跨 plan version 解析、replan 重绑定）。

### Phase 2.2 — 严格 Plan 校验（`d5326a6`）

V1 只校验 tool_key 是否存在。新增 `validate_plan_draft_detailed()`，在**落库前**检查：
注册表成员、工具 input_schema（必填/未知/类型）、step_key 唯一、依赖只能指向更早步骤、
无循环依赖、步骤数上限、`requires_target_field` 的工具必须有 target field、工具权限/风险契约
自身合法、**actor 权限契约**（LLM 不得提出调用者无权执行的步骤）、以及禁止输入清单
（shell/命令、raw SQL 执行、HTTP URL、动态注册工具、篡改 risk/permissions/human gate/evidence 契约）。

- `validate_plan_draft()` 保留 `list[str]` 签名（委托给详细校验器），所有调用方自动获得完整契约。
- `plan_with_llm()`：校验失败 → **把错误回灌给 Planner 自我修复一次** → 仍失败则返回 None。
- `create_task()`：模型计划被拒 → `planner_source="fallback"`（**绝不显示为 llm**）、
  `degraded_reason`、原始校验错误与尝试次数全部落库。
- `AgentPlan.validation_errors_json` + `planner_attempts`（迁移 `202610020047`），并在任务快照中暴露。
- `deterministic_plan()` 不再规划“自身必填输入无法满足”的步骤（无主体时丢弃该步骤及其下游），
  把问题提前到规划阶段。

测试：`tests/test_agent_planner_validation.py`（13 例，含“修复一次成功”“两次非法后回退”
“fallback 来源与错误落库”）。

### Phase 3a — 业务理解与场景识别（`5631092`）

**Subject Resolution V2**（`app/services/agent/subject.py`）：彻底删除 V1 “找不到就用项目第一个字段”
的静默兜底，改为三种显式结果 `resolved / ambiguous / not_found`；候选按目标字段编码/名称、
目标表名称/编码、脚本 logical_target 打可解释分值，并给出匹配来源与理由。无法唯一确定时，
在计划前插入**真实人工澄清网关**（step `clarify_subject`），人工通过 `edited_payload.target_field_id`
或 `target_field_code` 选择后校验归属、落库为 `human_clarified` 并触发 replan，继续跑完整链路。

**Scenario Router**（`app/services/agent/scenarios.py`）：4 个银行业务场景
（regulatory_field_analysis / requirement_generation / sql_change_impact / mapping_resolution）。
Stage A 规则打分（关键词 + 变更结构特征），输出 `scenario_key / confidence / rationale /
alternatives / requires_clarification`；Stage B 校验模型分类结果（未注册场景一律拒绝）。
置信度不足时不强行套用默认场景，而是标记需人工澄清。

**4 个场景计划**：`sql_change_impact`（语义差异→SQL 事实→血缘→影响→元数据→监管条款→比对→证据→缺口）
与 `mapping_resolution`（元数据→召回→重排→血缘→SQL 实现→候选建议→人工确认→证据→缺口）已实现；
`requirement_generation` 复用受治理字段分析链路（单一事实源）。

**附带修复**：运行结束时对“永远不可能执行”的下游步骤做显式结算，任务不会再停留在
`running` 且挂着 pending 步骤；快照新增每步 `input`（澄清 UI 需要）。

测试：`tests/test_agent_subject_resolution.py`（10 例）+ `tests/test_agent_acceptance.py`
新增 2 例（歧义主体→人工网关；无监管依据项目仍不能产出需求文档）。

### Phase 9（提前完成）— Agent Evaluation V2（`7a0c76e`）

`observability.py` 新增 21 项 V2 指标（planner 有效率/回退率、平均计划长度、无效/缺失工具调用率、
replan 成功率、证据精度、条款引用准确率、历史案例使用/采纳率、人工编辑/驳回率、SQL 语义召回/误报率、
影响传播准确率、任务完成率/未完成率、交付物采纳率等）。每项指标都有独立分母；
**无分母或缺少标注基准时返回 null 并给出 `metric_notes` 原因**，并提供 `METRIC_LABELS` 中文名。

## 4. 测试与回归（最新）

```powershell
$env:TASK_QUEUE_PROVIDER='inline'; $env:AUTH_MODE='optional'
.venv\Scripts\python.exe -m pytest tests/test_agent_state_machine.py tests/test_agent_tool_registry.py `
  tests/test_agent_runtime.py tests/test_agent_ai_skill_tools.py tests/test_agent_acceptance.py `
  tests/test_agent_sql_semantic_diff.py tests/test_agent_dependencies.py tests/test_agent_dependency_runtime.py `
  tests/test_agent_planner_validation.py tests/test_agent_subject_resolution.py tests/test_agent_evaluation_v2.py `
  tests/test_migration_schema_freeze.py `
  tests/test_governance.py tests/test_product_integrity.py -q    # → 147 passed
```

## 5. 已知限制（V2 进行中）

1. `generate_business_draft` 内部自行 commit（V1 遗留技术债，Phase 11 处理）。
2. Scenario Router / Subject Resolution / Adaptive Planner 尚未实现（Phase 3）。
3. 历史案例记忆尚未实现；`compare_policy_and_implementation` 仍只输出 pending。
4. 人工网关仍固定路由 `project_manager`（Phase 7 改造为 review_policy）。

## 6. 下一阶段

Phase 3：Scenario Router（规则+LLM 两阶段、低置信度 → clarification gate）、Subject Resolution V2
（resolved/ambiguous/not_found，禁止静默选第一个字段）、Adaptive Planner（默认 LLM、结构化 Observe
状态、Observe→Replan）、4 个 banking scenario 计划模板。
