# Agent Orchestrator v1 — 交付与验收报告

分支：`dsh/agent-orchestrator-v1`（基于 `dsh/part2-acceptance-closure-20261001`）
状态：Phase 1–6 + 8 + 9 已完成；Phase 6 已在本地部署上通过端到端验收（含 5 个人工确认节点）；Phase 7（前端 Agent Workspace）与收尾验收进行中。

目标：把「多个独立 AI Skill + 人工逐点调用」升级为「业务目标 → 自动规划 → 受控工具 → 证据 → 中间结果 → 人工确认 → 继续执行 → 交付物」，
同时保留银行场景红线：AI 不绕权限、不直接写生产、不自动确认合规、不把模型当事实源、关键结论必须有证据、高风险动作必须人工确认。

---

## 1. 架构图

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ 前端 Agent Workspace (/agent)  —— 企业 AI 工作台，不是聊天框                 │
│ 目标输入 │ 计划区 │ Step Timeline │ Tool Call 展开 │ Evidence │ Gap │         │
│ 人工确认面板 │ Artifact 面板 │ 执行日志 │ Retry/Resume/Replan/Cancel         │
└───────────────┬──────────────────────────────────────────────────────────────┘
                │ REST（/api/agent/*，逐端点鉴权）
┌───────────────▼──────────────────────────────────────────────────────────────┐
│ app/api/agent.py                                                             │
├──────────────────────────────────────────────────────────────────────────────┤
│ Agent Runtime (app/services/agent/runtime.py)                                │
│  • create_task → Planner → materialize_plan(版本化, 不可变)                  │
│  • run_agent_task  ← BackgroundJob handler（inline 或 Celery 同一入口）      │
│  • _execute_step：逐个工具调用 → AgentToolCall 审计 → retry → replan          │
│  • _open_human_gate：waiting_human + 真实 ReviewTask（既有审核台账）          │
│  • decide / resume / cancel / retry / replan / task_snapshot                 │
├───────────────────────────┬──────────────────────────────────────────────────┤
│ Planner (约束式)          │ Tool Registry (受控)                             │
│  • 只能选注册表内 tool_key │  • 15 个工具，规格含权限/风险/超时/重试/只读/    │
│  • 依赖只能指向更早步骤    │    人工确认/证据契约/审计字段                     │
│  • LLM 仅"提议"，输出必须  │  • 规格不合格直接拒绝注册                         │
│    过注册表校验，否则回退  │  • 工具自身再校验项目权限（服务层无权限）         │
│    确定性计划并记录原因    │                                                  │
├───────────────────────────┴──────────────────────────────────────────────────┤
│ 复用既有能力（不重写）：                                                     │
│  Skill Runtime/契约(SkillEvidence/SkillGap/SkillPolicyComparison) │           │
│  HybridRetriever/planned_search │ Field Recall/Rerank/Prepare │ Mapping │      │
│  Requirement Generation │ LineagePathResolver/SemanticImpact │ SQL 解析         │
│  BackgroundJob/任务队列 │ ReviewTask/ReviewDecision/Workflow │ AuditLog         │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 2. 新增数据模型（`app/models/agent.py`，迁移 `202610010045`）

| 表 | 作用 | 关键字段 |
|---|---|---|
| `agent_tasks` | 一条业务目标 | objective/objective_key/scenario_key、status、current_step_key、plan_version、background_job_id、review_instance_id、counts（completed/pending/failed/waiting_human/skipped）、retry_count、replanning_count、max_retries、evidence_count、artifact_count、model_metadata_json、evidence_refs_json、artifact_refs_json、result_summary_json、error_code/message、created_by、started_at/finished_at |
| `agent_plans` | 不可变计划版本 | task_id、version_no、status(active/superseded)、planner_source(deterministic/llm/replan)、steps_json、plan_hash、degraded_reason、superseded_by |
| `agent_steps` | 一步 = 一个工具绑定 | step_key、order_index、tool_key、reason、status、required、depends_on_json、input_json/input_hash、output_summary_json、evidence_refs_json、gap_codes_json、attempt_count/max_attempts、evidence_count、requires_human_confirmation、human_gate_key、review_task_id、idempotency_key(unique)、artifact_count、error_code/message |
| `agent_tool_calls` | 追加式可观测记录 | tool_key/tool_version、attempt、status、input_summary_json、output_summary_json、evidence_count、context_hash、model_name/prompt_version/provider_type、duration_ms、token_usage_json、retry_count、failure_reason、degraded_path、required_permissions_json、risk_level、read_only、human_confirmed、adopted、execution_metadata_json |
| `agent_human_decisions` | 人工决策的 Agent 侧绑定 | decision(approve/reject/edit_and_approve/request_reanalysis)、comment、edited_payload_json、context_hash、applied_plan_version、**review_task_id / review_decision_id**（指向既有审核台账，不另造决策源）、decided_by/decided_at |
| `agent_artifacts` | 交付物候选 | artifact_type、title、status(draft/confirmed/rejected/superseded)、ref_type/ref_id、summary_json、evidence_refs_json、content_hash、confirmed_by/confirmed_at |

迁移为**手写显式 DDL**（迁移文件禁止 import 活模型，`tests/test_migration_schema_freeze.py` 门禁），downgrade 可重放。

## 3. 新增 API

| 方法 | 路径 | 权限 |
|---|---|---|
| GET | `/api/agent/tools?project_id=` | 登录；给 project_id 时按该角色可执行范围过滤 |
| POST | `/api/projects/{id}/agent/tasks` | `task.manage` |
| GET | `/api/projects/{id}/agent/tasks` | `project.view` |
| GET | `/api/agent/tasks/{id}` | `project.view`（按任务所属项目解析） |
| POST | `/api/agent/tasks/{id}/cancel` \| `/retry` \| `/replan` \| `/resume` | `task.manage` |
| POST | `/api/agent/tasks/{id}/steps/{step_id}/decision` | 该 gate 声明的权限（默认 `final.review`）+ 审核流程角色校验 |
| GET | `/api/projects/{id}/agent/metrics` | `project.view` |

Agent 路由**不使用**共享 `guard_project_resource`：项目从任务解析，并且**每一步都按 job actor 重新校验该工具声明的权限**（服务层无权限逻辑，工具自己再查一次）。

## 4. Tool Registry 清单（16）

| tool_key | 风险 | 只读 | 需人工确认 | 权限 |
|---|---|---|---|---|
| search_regulatory_knowledge | medium | ✔ | | knowledge.search |
| search_metadata | low | ✔ | | catalog.search |
| recall_field_candidates | medium | ✔ | | technical.edit |
| rerank_field_candidates | medium | ✔ | | technical.edit |
| prepare_field_candidate | medium | | | technical.edit |
| get_lineage | low | ✔ | | lineage.view |
| analyze_lineage_impact | medium | ✔ | | impact.view |
| inspect_sql_rule | low | ✔ | | lineage.view |
| compare_policy_and_implementation | high | ✔ | ✔ | lineage.view |
| generate_mapping_draft | high | | ✔ | business.edit |
| generate_requirement_candidate | high | | ✔ | deliverable.generate |
| generate_requirement_document | high | | ✔ | deliverable.generate |
| create_gap_report | low | | | project.view |
| summarize_evidence | low | | | project.view |
| request_human_confirmation | high | ✔ | ✔ | project.view |
| compare_sql_versions | high | ✔ | ✔ | lineage.view |

Registry 拒绝无法治理的规格：无权限、写操作无审计字段、人工确认却低风险、缺证据契约、handler 不可调用、tool_key 不合规。

## 5. Agent 状态机

- 步骤：`pending → running|blocked|failed|skipped`；`running → completed|failed|waiting_human|blocked|skipped`；`waiting_human → completed|blocked|pending|running|failed|skipped`；`failed/blocked → pending|running|skipped`；`completed/skipped` 终止。
- 任务：`created → planning|running|failed|cancelled`；`running → waiting_human|blocked|completed|failed|cancelled`；`waiting_human → running|blocked|completed|failed|cancelled`；`failed/blocked → running|cancelled`；`completed/cancelled` 终止。
- 人工决策映射：`approve/edit_and_approve → completed`、`reject → blocked`、`request_reanalysis → pending`（并可触发重规划）。
- **开放人工节点 = 整任务暂停**：冗余运行不会跳过网关下游步骤，也不会吞掉失败。

## 6. Planner 示例

确定性主链路（`regulatory_field_analysis`，15 步）：

```json
{ "objective": "分析二级市场福费廷报送需求", "scenario_key": "regulatory_field_analysis",
  "subject": {"target_field_id": 42, "target_field_code": "FT_BAL", "resolution": "objective_match"},
  "steps": [
    {"step_key":"search_policy","tool_key":"search_regulatory_knowledge","depends_on":[],"required":true},
    {"step_key":"search_metadata","tool_key":"search_metadata","depends_on":[]},
    {"step_key":"recall_candidates","tool_key":"recall_field_candidates","depends_on":["search_metadata"]},
    {"step_key":"rerank_candidates","tool_key":"rerank_field_candidates","depends_on":["recall_candidates"]},
    {"step_key":"inspect_sql","tool_key":"inspect_sql_rule","depends_on":["search_metadata"]},
    {"step_key":"query_lineage","tool_key":"get_lineage","depends_on":["search_metadata"]},
    {"step_key":"analyze_impact","tool_key":"analyze_lineage_impact","depends_on":["query_lineage"]},
    {"step_key":"compare_policy","tool_key":"compare_policy_and_implementation","depends_on":["search_policy","inspect_sql"]},
    {"step_key":"prepare_mapping","tool_key":"prepare_field_candidate","depends_on":["rerank_candidates"],"required":false},
    {"step_key":"generate_mapping_draft","tool_key":"generate_mapping_draft","depends_on":["prepare_mapping"],"required":false},
    {"step_key":"generate_requirement_candidate","tool_key":"generate_requirement_candidate","depends_on":["compare_policy","analyze_impact"]},
    {"step_key":"confirm_requirement_candidate","tool_key":"request_human_confirmation","depends_on":["generate_requirement_candidate"]},
    {"step_key":"generate_requirement_document","tool_key":"generate_requirement_document","depends_on":["confirm_requirement_candidate"]},
    {"step_key":"summarize_evidence","tool_key":"summarize_evidence","depends_on":["generate_requirement_document"]},
    {"step_key":"create_gap_report","tool_key":"create_gap_report","depends_on":["summarize_evidence"]}] }
```

LLM 规划路径：只允许输出 `tool_key/depends_on/input`；输出必须通过注册表校验，否则回退确定性计划并把 `degraded_reason` 写进 `agent_plans`。Planner 无法生成 shell/SQL/HTTP 或表外工具。

## 7. 一次完整执行记录（本地部署，HTTP 全程）

命令（见 `.local-run/agent-live-acceptance.json` 原始记录）：

```
python agent-live-acceptance.py      # 合成数据 + 登录 + REST 全链路 + 逐个 gate 人工确认
```

| 项 | 结果 |
|---|---|
| Registry 可见工具 | 15 |
| 创建任务 | POST 202，异步由 Celery worker 执行 `agent_task_run` |
| 首次暂停 | `waiting_human` @ `compare_policy` |
| 人工确认 | 5 个 gate 全部 200：compare_policy → generate_mapping_draft → generate_requirement_candidate → confirm_requirement_candidate → generate_requirement_document |
| 最终状态 | **completed**，completed=15 / failed=0 / skipped=0 |
| 证据 | 12 条（policy_clause 1 + 事实/血缘/SQL 等） |
| 交付物 | mapping_draft(confirmed)、requirement_candidate(confirmed)、requirement_document(confirmed)、evidence_summary(draft)、gap_report(draft) |
| 缺口 | metadata_not_found、skill_binding_missing×3（未绑定技能时明确降级，不伪造） |
| 指标 | task_success_rate=1.0、avg_steps=15、tool_success_rate=1.0、evidence_coverage=0.667、final_artifact_acceptance_rate=1.0、unsupported_claim_rate=null（无分母不造假 0） |

## 8. 失败重试 / 人工拒绝 / 重规划记录

- **失败重试 + 重规划**：`tests/test_agent_runtime.py::test_retryable_failure_retries_then_replans_and_marks_incomplete`
  工具连续抛可重试错误 → 按 `retry_policy.max_attempts=2` 重试 2 次 → 仍失败 → `replan()`（只改当前计划的后续/可选步骤，不碰已完成步骤与人工决策）→ 步骤降级为可选并记录 `step_replanned` / `optional_step_failed` → 任务以 **blocked + incomplete=true** 结束，绝不伪装成完成。
- **人工拒绝**：`test_rejection_blocks_the_task_and_records_the_decision`
  拒绝 → 步骤 blocked、`error_code=human_rejected`、缺口入账、`AgentHumanDecision(decision=reject)` 引用 `ReviewDecision`；重复提交同一决策幂等（不重复记账）。
- **人工拒绝后重规划**：`POST /api/agent/tasks/{id}/replan` → `runtime.replan_task()`（重置失败/阻断步骤为 pending 后重排后续步骤）；`request_reanalysis` 决策同样把步骤退回 pending 并记录 `human_reanalysis_requested`。
- **取消**：`test_cancel_skips_pending_steps` → 未执行步骤按 `task_cancelled` 跳过，任务 cancelled。

## 8.5 Phase 9：SQL 语义差异（同步增强，不阻塞主链路）

`app/services/lineage/sql_semantic_diff.py` 建立在既有 `compare_sql_versions` 之上（它已经是 AST/语义级：解析两版 SQL 的血缘边并比对 WHERE/JOIN/聚合/CASE/来源字段，不是文本 diff），再做一层**非权威投影**：把变化类别翻成业务语言、标出可能影响口径的类别，并要求人工确认。

Agent 工具 `compare_sql_versions`（第 16 个工具，risk=high、read_only、requires_human_confirmation）：

- 可显式传 `old_sql`/`new_sql`，也可给 `script_file_id`（或按主体字段自动发现脚本）对比“上一版本 vs 当前版本”；
- 输出一条 `sql_semantic_diff` 证据 + 每条语义变化一条 `interpretation` 声明（只引用该 SQL 证据，`policy_clause_ids` 恒为空 → SQL 永远不能当监管依据）；
- 无基线→skipped + 缺口 `sql_baseline_missing`；无语义变化→缺口 `no_semantic_change`。

示例（测试断言）：`where deal_status is not null` → `where deal_status in ('ACTIVE','MATURED')` 产出
“过滤范围（WHERE/条件）发生变化：… ；可能改变该监管字段的统计口径或取值范围（interpretation，需 Evidence 与人工确认）”。
**刻意不加入确定性主链路**：它本身需要人工确认，放进默认计划会额外增加网关；由 LLM 规划器或按场景计划按需启用。

## 9. 测试报告

| 套件 | 数量 | 覆盖 |
|---|---|---|
| `tests/test_agent_state_machine.py` | 6 | 状态词表、合法/非法跃迁、派生状态优先级、决策映射、计数 |
| `tests/test_agent_tool_registry.py` | 9 | 规格治理、重复注册、未知工具失败关闭、输入校验、按权限过滤、计划校验、场景识别 |
| `tests/test_agent_runtime.py` | 12 | 执行+审计、证据/交付物绑定、幂等不重跑、重试+重规划、超时、权限拒绝、task.manage 校验、人网关+批准续跑、拒绝幂等、取消、指标、create_task 计划落地 |
| `tests/test_agent_ai_skill_tools.py` | 8 | 6 个 Skill 工具注册/降级/输入校验/人工确认声明 |
| `tests/test_agent_acceptance.py` | 2 | 合成监管数据全链路（真实工具、真实人工网关）+ 无监管依据项目**不得**产出需求文档 |
| `tests/test_agent_sql_semantic_diff.py` | 5 | SQL 语义差异→interpretation 声明、无语义变化、无基线缺口、工具治理声明、声明仅引用证据 |
| `tests/test_migration_schema_freeze.py` | 3 | 迁移链、fresh→downgrade→upgrade 与 ORM 契约一致 |

运行（本机建议显式覆盖测试环境）：

```powershell
$env:TASK_QUEUE_PROVIDER='inline'; $env:AUTH_MODE='optional'
.venv\Scripts\python.exe -m pytest tests/test_agent_state_machine.py tests/test_agent_tool_registry.py `
  tests/test_agent_runtime.py tests/test_agent_ai_skill_tools.py tests/test_agent_acceptance.py -q
  tests/test_agent_sql_semantic_diff.py -q
# → 42 passed
```

## 10. 回归结果

```powershell
$env:TASK_QUEUE_PROVIDER='inline'; $env:AUTH_MODE='optional'
.venv\Scripts\python.exe -m pytest tests/test_governance.py tests/test_product_integrity.py tests/test_coverage_metrics.py `
  tests/test_ai_skill_control.py tests/test_ai_skill_runtime.py tests/test_requirement_paths.py `
  tests/test_performance_integrity.py -q          # → 137 passed（含 agent 套件）
.venv\Scripts\python.exe -m pytest tests/test_ai_skill_field_candidates.py tests/test_ai_skill_field_rerank.py `
  tests/test_ai_skill_mapping.py tests/test_ai_skill_requirement.py tests/test_ai_skill_lineage_adapter.py -q  # → 119 passed（含 agent）
```

**WARN（环境，非回归）**：`backend/.env` 里 `TASK_QUEUE_PROVIDER=celery`，而 `test_governance.py::test_inline_batch_job_is_queryable_and_idempotent` 断言 inline 语义；加 `$env:TASK_QUEUE_PROVIDER='inline'` 即通过。

## 11. 已知限制

1. `generate_business_draft` 内部自行 commit，编排器无法完全拥有该步骤的事务边界（记录在案，未回退任何既有逻辑）。
2. Skill 绑定缺失时，重排/需求/文档工具走**确定性降级路径**并记录 `skill_binding_missing` 缺口；要得到模型结论必须先发布并绑定对应 Skill。
3. 没有治理条款（normative source）的项目**无法**产出需求文档 —— 这是设计约束，不是缺陷。
4. 人工网关路由角色固定为 `project_manager`（该角色同时持有 `task.manage` 与全部 review 权限）；如需按业务/技术角色分派，需按 gate 类型拆分 workflow key。
5. 单文档中的策略比对只输出 `pending`（“需人工确认”），Agent 从不断言 matched/conflict；要断言冲突必须走已发布的比对技能或人工。
6. 本机 DSH 沙箱内 `next build`/Playwright 受管道限制，前端构建在沙箱外执行。

## 12. 下一阶段建议

1. 把 `compare_policy_and_implementation` 接到已发布的比对 Skill（返回 matched/conflict + 证据），并补一条“冲突 → 人工拒绝 → 重规划”的现场记录。
2. Agent 评估集：把 `docs/evaluation/` 的口径扩到 agent 级（成功率、重试、重规划、人工拒绝率、证据覆盖、Unsupported Claim、Hallucination Guard、交付物采纳率），用固定合成语料跑基线。
3. 多 Agent 暂不引入：先把单 Agent 主链路的 SQL 语义 diff、冲突检测、交付物采纳闭环做扎实。
4. 权限细化：按 gate 类型拆分 workflow key，使技术评审人也能确认映射类网关。
5. 前端补浏览器验收（Playwright）与截图基线。
