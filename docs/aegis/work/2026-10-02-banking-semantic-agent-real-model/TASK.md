# TaskIntent — 单 Agent 主链路真实模型化（银行监管字段分析闭环）

- 分支：`dsh/banking-semantic-agent-v2`（HEAD `5194e9b`，23+ 提交已推送）
- 目标：把现有单 Agent 主链路做成**真实模型驱动、真实业务可验收**的闭环；不新增 Agent 概念、不做 Multi-Agent、不重复已完成能力（Orchestrator / SQL semantic diff / Workspace / retry·replan·human gate 已完成）。
- 真实模型：`LLM_PROVIDER=openai_compatible`，`LLM_BASE_URL=http://47.101.159.7:29988/v1`，`LLM_MODEL=deepseek-v4-flash`（`backend/.env`）。
  已实测：`chat_json` 1.41s / `chat_structured` 12.24s（schema 校验通过）。
- 非目标：不新增空壳 Skill；不为覆盖率造 Skill；不做 Multi-Agent。

## 1. 审计：主链路中可能出现 skill_binding_missing / deterministic fallback / degraded 的位置

代码证据：`backend/app/services/agent/tools/ai_skill_tools.py` 第 313、809、924、1041、1081 行写 `skill_binding_missing`；
184 行 `resolve_skill(db, principal, FIELD_RERANK_TASK, _project_skill_scope(ctx)) is not None`。

| 主链步骤 / 工具 | 需要的 Skill task_key | 定义 | 已发布 | 已绑定(验收项目 11) | 当前行为 |
|---|---|---|---|---|---|
| `rerank_field_candidates`（模型重排） | `field_semantic_matching` | ✅ 定义 1 | ✅ v9（另有 v2/3/4/5/8） | ❌（原仅项目 2、5；本次已补建 `project:5:11`） | 有绑定后仍走 `deterministic_recall`（候选仅 1 条；需 ≥2 候选复验） |
| `generate_mapping_draft`（Mapping 草稿） | `source_to_mart_mapping` / `mart_to_ybt_mapping` / `scenario_business_mapping` / `scenario_technical_lineage` | ❌ 无定义 | ❌ | ❌ | 确定性草稿 + `skill_binding_missing` |
| `generate_requirement_candidate` | `requirement_candidate_generation` | ❌ 无定义 | ❌ | ❌ | 确定性草稿（`ai_skill_tools.py:924`） |
| `generate_requirement_document` | `requirement_document_assistance` | ❌ 无定义 | ❌ | ❌ | 确定性草稿（`ai_skill_tools.py:1041/1081`） |
| `compare_policy_and_implementation`（制度与实现对照） | **无模型 Skill**（工具未引用任何 task_key，走确定性比较/待定分支） | ❌ | ❌ | ❌ | 确定性比较，且当前多为 pending（缺口）—— 属于需真实模型化的业务能力 |

设计为确定性、**不属于缺口**的步骤：`recall_field_candidates`（`recall_fields`）、`search_regulatory_knowledge`（RAG 检索 + embedding）、
`search_metadata`/`inspect_sql_rule`/`get_lineage`/`analyze_impact`/`prepare_field_candidate`/`summarize_evidence`/`create_gap_report`。

## 2. 计划（按用户给定顺序）

1. ✅ 审计（上表）；待补：`compare_policy_and_implementation` 的 task_key 与绑定状态。
2. 为 4 类主链 Skill 完成：定义 → Prompt/IO schema（平台既有 `SfetyPrompt`/`ContractModel` 模式）→ 测试用例 → 评测 → 独立审批 → 发布 → 项目绑定：
   - `requirement_candidate_generation`、`requirement_document_assistance`、`source_to_mart_mapping`、`mart_to_ybt_mapping`
   - 复验 `field_semantic_matching` 在 ≥2 候选下确实产生模型型结果。
3. 真实模型重跑完整 `regulatory_field_analysis`（13 项覆盖清单）。
4. 每个模型型步骤记录 `model_execution.executed=true` + model_name/provider/skill_version/run_id/input hash/citations/latency/degraded_reason，禁止伪装。
5. 4 组自主性场景（信息不足自补查 / 冲突→人工 reanalysis→重规划 / Skill 失败→retry→fallback+incomplete / SQL 语义变化→impact→recheck）。
6. 15 步计划审查（必须固定 / Observation 决定 / Planner 可插 / optional）。
7. 不做 Multi-Agent。
8. Agent 级业务质量评测集（10 项指标）。
9. 治理约束复核（不自动执行 SQL、不自动写正式 Mapping/Requirement、高风险人工确认、不越权、无证据不下监管结论、敏感数据不外发）。
10. 最终报告（自主步骤 / 固定流程 / 真实模型步骤 / replan / human gate / 可用 artifact / 非 Agent 部分）。

## 3. 下一步（最小动作）

## 3. 本轮真实进度（已落库到本机环境）

- 定义 **2** `requirement_candidate_generation`（task_key 同）创建者 `smoke_admin`（平台管理员；定义一律平台级，需 platform admin）。
- 版本 **10**（no 1，scope=project 11，`model_profile_id=4`，`output_schema_key=requirement_candidate_v1`）。
- 测试用例 **5**；评测模式必须是 `mock_model|real_model|deterministic|replay|human_review`（本次 `real_model`）；
  `run_tests` 从 ModelProfile 推导 `actual_mode`，与请求不符报 422。
- 评测产生 2 条 `ValueError` → `releases.submit` 被 **`release_gate_failed`** 拦住（治理门禁生效）。
- 直调 `runtime.execute_resolved` 定位真正原因：`compile_input` → `validate_requirement_output` 抛
  `ValueError: one fixed requirement context is required`。契约：envelope 必须恰好 1 条 `kind="requirement_context"`
  的 fact（value 为 dict；`project_id` 等于 scope.project_id；`fields` 恰好 1 项且含 `target.id`），且 `policy_evidence` 非空。
- `resolve_skill` 要求已发布版本 + 绑定（draft 会 `skill_unavailable`）；但 `run_tests` 直接对 draft 版本执行。

## 4. 下一步（最小动作）

用平台 builder 为验收项目真实字段生成 `requirement_context` fact，重建测试用例 → 重跑 `real_model` 评测 →
`releases.submit` → **另一用户** `releases.publish`（强制独立审批）→ 绑定 → 验 `model_execution.executed=true`。
然后同法处理 `requirement_document_assistance`、`source_to_mart_mapping`、`mart_to_ybt_mapping`，并给制度对照加模型入口。

## 5. 漂移判定
`continue` — 与目标一致；无阻断。

## 6. 验收样数据现状（project 11）与播种计划

实测：`institution=5`、`confidentiality=internal`、目标表 `4 YBT_FT 福费廷报送表`、目标字段 `22 FT_BAL 福费廷余额`；
**项目内无 Requirement、无 RequirementGenerationInput**；全局 SourceField 有 186 条，但项目目录绑定极薄（重排召回只有 1 个候选）。

播种计划（按依赖顺序，全部走平台服务而非裸插入，保留 revision/hash 不变量）：

1. 为项目 11 建 **Requirement + Revison**（含字段 22），使 `RequirementGenerationInput` 可准备。
2. 调 `requirement_generation.prepare_input(db, project_id, requirement_id, PrepareGenerationInput(
   expected_content_version, field_ids=[22], sections=["business"], idempotency_key), principal)`（需 `business.edit`）→ 得 row+item。
3. 用 `requirement_context.build_requirement_envelope(project, row, item)` 生成**合法 envelope**（含 1 条
   `kind="requirement_context"` fact + policy_evidence）→ 作为 Skill 测试用例输入 → 重跑 `real_model` 评测。
4. 目录侧补 ≥2 个候选来源字段（CatalogTable/CatalogField 绑定到项目），使 `rerank_field_candidates` 真正走模型。
5. 依次完成 submit → 独立用户 publish → 绑定 → agent 工具验 `executed=true`。

待确认的模型类名：项目目录字段模型不是 `CatalogField`（导入名不存在），下一步需先查 `app/models` 中目录字段/目录表的真实类名。

## 7. Round 3 实际进展（已写入本机数据库）

验收样数据已就位：**Requirement 1**（scope: target_table_id=4, scenario_id=17, field_ids=[22]）→
**Revision 1**（content_version=1, hash 28c7bbd62bae）→ **RequirementGenerationInput 1**（hash 3110bc83a1f2）→
**RequirementGenerationItem 1**（field 22, section business, pending）。
关键发现：`initialize_content` 需要 `scope_json["scenario_id"]`（项目已有场景 17 `SECONDARY_MARKET_FORFAITING`）；
`prepare_input` 返回 `(row, deduplicated)` 且**不创建 items**；items 由 `app/api/requirements.py:328` 创建、随后
`enqueue(job_type="requirement_generation", handler=requirement_generation_handler)`；worker 对每个 item 调
`generate_candidate`（那里才会走 Skill）。

`requirement_context.build_requirement_envelope(project, row, item)` 已能产出**合法 envelope**：
`facts=[(requirement_context, requirement-input:1)]`，`policy_evidence=0`，`gaps=[missing_basis]`。

`real_model` 评测 RUN 29 结果（这是第一次真实模型链路评测）：

- metrics：`total 4, executed 1, skipped 3, passed 0, elapsed_ms 18845, mode real_model, real_model_successes 0`
- 断言：`schema/scope/budget/unknown_reference_rejected/native_unknown_reference_rejected` 全 ✓；
  **`model_output_valid: False`**、`minimum_claims: False`（模型输出未被计为真实模型产物，claims 为空）
- 其余 3 个用例 `case_defect: True`（早期错误 envelope 的用例，被正确归为用例缺陷而非模型失败）
- `submit` 再次被 `release_gate_failed` 拦住（门禁正确）

## 8. 下一步（两件具体事）

1. 为项目挂接**固定监管知识条款**（policy_evidence），消除 `missing_basis`；
2. 查 `ModelCallLog` 看这次 18.8s 调用的**真实 provider 响应**，判定 `execution_kind` 为何不是 `real_model`
   （是模型调用失败、响应不合 schema，还是 prompt 输出为空）→ 修 Prompt/schema 后重跑评测 →
   `submit` → 独立用户 `publish` → 绑定 → `enqueue` 生成作业验真实模型候选。

## 9. Round 4 —— 真实模型链路打通（关键里程碑）

**根因（真凭实据）**：`ModelProfile 4` 的 `config_json.max_output_tokens=2048` + `max_context_tokens=8192`
导致模型输出被截断：三次调用 completion_tokens = 4065 / 2392 / 2770 全超 2048 → `invalid_model_response`
（`http_status=200`，即模型回了但 JSON 不完整）。
修复：`max_output_tokens=4096`、`max_context_tokens=32768`、`timeout_seconds=120` → 预算 limit 从 5632 升到 **28160**。

**发布门禁完整跑通（治理链路全部生效）**：

- 要求**两个通过态运行**（内容 hash / 依赖 hash / 用例快照均须一致）：
  - `RUN 33`：`deterministic`，`passed 4 / skipped 3`
  - `RUN 32`：`real_model`，`passed 4`，**`real_model_successes: 4`**
- `releases.submit` → `pending_approval`（第一次真正通过门禁）
- `releases.publish` → **由另一用户完成审批**（`approved_by=26 dsh_handoff_admin_20260930`；
  创建者是 1 `smoke_admin`，满足 `independent_approval_required` 约束）；`expected_binding_lock` 用于并发保护
- 绑定 `project:5:11` 现指向已发布版本 11（`requirement_candidate_generation` v2）

**真实模型产物证据**（`ModelCallLog`，持久化）：

- 日志 473/474/475：`status=success`、`execution_kind=real_model`、`model_name=deepseek-v4-flash`、
  `skill_version=v2`、latency 15.2s / 15.6s / **7.6s**、completion_tokens 3591 / 3553 / 1552
- 模型产出的 claims 引用真实证据 id（`requirement-input:1`），无编造 policy 引用（`policy_clause_ids: []`），
  证据不足时写入 gaps（`missing_basis` / `missing_business_definition` / `missing_physical_source`）
- 用例断言：`schema / scope / budget / unknown_reference_rejected / native_unknown_reference_rejected /
  model_output_valid / minimum_claims / required_gaps` 全 ✓

**另：平台早就存在真实模型成功的 Skill 调用**：`scenario_business_mapping`（记 mapping 任务族）在 2026-10-02 00:49/01:03
两次 `status=success`、`execution_kind=real_model`、latency 2.49s、带 citations —— 说明映射线已具备真实模型能力，
不需重建（下一轮直接验证其在 Agent 主链中的 `executed=true` 即可）。

## 10. 下一步

1. 同法处理 `requirement_document_assistance`（prompt/schema/用例/评测/独立审批/发布/绑定）；
2. 复验 `scenario_business_mapping` 等映射类 Skill 在 Agent 工具链中的真实模型执行；
3. 跑完整 `regulatory_field_analysis` 并逐步校验 `model_execution.executed=true`（记录
   model_name/provider/skill_version/run_id/input hash/citations/latency/degraded_reason）；
4. 补 4 组自主性场景与 Agent 级业务质量评测集。

## 11. Round 5-6 —— 主链跑到第一个真实模型步骤（并修掉 3 个阻断缺陷）

真实 15 步主链（project 11，task 7）实测轨迹：

```
search_policy completed → search_metadata completed(gap metadata_not_found)
→ recall completed → rerank completed(executed=False, 只有 1 个候选)
→ inspect_sql → query_lineage → analyze_impact → compare_policy ⛔ 人工 Gate
→ （人工批准）prepare_mapping → generate_mapping_draft ✅ executed=True deepseek-v4-flash
→ generate_requirement_candidate ⛔ Gate（此前 executed=False/ deterministic_draft）
```

**里程碑**：`generate_mapping_draft` 产生 Agent 链中**第一个 `model_execution.executed=true`**（model=deepseek-v4-flash，无 degraded）。

**本轮前两个提交修掉的阻断缺陷**：

1. `61094df`：运行失败（如 pydantic ValidationError）只捕获 HTTPException → 任务永久 `running`、
   步骤永久 `pending`、**租约不释放**（后续全部 `skipped=run_lease_held`）。现在任何异常都记录
   `error_code/agent_run_failed`、写 `halt_reason`、结算下游步骤、刷新状态并释放租约。
2. `d722e37`（三处）：
   - 观察器在被拒补丁（`s2 already exists in the plan`）上抛异常且**不计重规划预算** → 每完成一步就再问一次模型；
     现在拒绝/不可解析的补丁记录 `plan_patch_invalid` 并计入 `MAX_REPLANS_PER_TASK`；
   - Planner 安全提示词新增约束：`depends_on` 只能引用自己声明过的 step_key（就是模型编造
     `search_metadata_by_code` 的根源）；
   - `generate_requirement_candidate` 在计划未带 `skill_key` 时直接降级，**即使 Skill 已发布绑定**；
     现在回退到 `requirement_candidate_generation` 任务键，由绑定决定是否模型型。

回归：agent 全量 **189 passed**。

## 12. 下一步（已验证可继续的具体动作）

1. 直接重跑 task 7 的剩余步骤（先批准 mapping gate），验证 `generate_requirement_candidate` 是否变为
   `executed=true`（skill v2 已发布+绑定，且工具已改为按任务键解析）；
2. 向 project 11 补 ≥2 个目录候选，让 `rerank_candidates` 真正走模型（而不是 1 候选短路）；
3. 建 `requirement_document_assistance` skill（同法）；
4. 4 组自主性场景 + Agent 级业务质量评测集。

## 13. Round 7 —— 全链 15/15 跑完（6 个 Gate 全部人工批准）

新建 task 8 完整跑完（不再停滞）：15 个唯一步骤全部 `completed`，`plan_version=2 / replans=1`，`model_executed=1`。

**真实模型调用证据（`ModelCallLog`，project 11）**：

- `scenario_business_mapping`：2 次 `success`、`kind=real_model`、1.75s、token 912/957 → 映射草稿步骤
  `generate_mapping_draft` **`model_execution.executed=true`，model=deepseek-v4-flash，degraded=None**
- **`agent_observation`（Observe→Replan）真实模型执行：3 次成功**（3.6s / 8.1s / 16.6s，token 2984/4234/6090）
  → 自适应重规划是**真的模型驱动**（task 8 的 `replans=1` 由此产生）；另有 1 次失败（19.1s / 8461 token）

**本轮新发现的两个缺陷（待修）**：

1. `generate_requirement_candidate`：gap 从 `skill_binding_missing` 变为 **`skill_execution_unavailable`** →
   任务键回退修复生效（**绑定已找到**），但技能执行失败：最后 6 条调用日志里**没有**该技能调用记录，
   说明失败发生在模型调用之前的阶段（compile_input / 上下文预算 / 绑定版本解析），需查具体异常。
2. **任务完成后状态停在 `running`**：15 个步骤均 `completed`，但 task 8 仍为 `running`，
   后续 4 轮运行均返回 `paused=False` 且无步骤可跑 → `_refresh_task_status` 未在所有步骤完成时把任务置为 completed。

**另一确认**：`generate_requirement_document` 仍为 `skill_binding_missing`（该 Skill 本就未创建，符合预期）。

## 14. 下一步

1. 修缺陷 2（全部步骤完成 → 任务 completed）——最小、最先；
2. 修缺陷 1（查 `skill_execution_unavailable` 真实异常）；
3. 建 `requirement_document_assistance` skill；
4. 补 ≥2 个目录候选让 rerank 走模型；
5. 4 组自主性场景 + Agent 级业务质量评测集。
