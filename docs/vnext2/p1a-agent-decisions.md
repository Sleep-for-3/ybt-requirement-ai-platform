# P1-A Agent 五类业务决策：真实运行时证据

- 日期：2026-10-23
- 分支：`dsh/vnext-business-accuracy-20261021`
- 证据级别：`MOCK`（隔离 SQLite + 真实运行时/真实内置工具/真实门控），业务准确率 `UNVERIFIED`
- 测试：`backend/tests/test_vnext2_agent_decisions.py`（5 例）；相邻回归 `pytest tests -k "agent"` → **224 passed**

## 1. 目的与边界

任务书第六章要求：Agent 必须在五类业务情形下作出正确取舍，而不是“能跑完就算成功”。本轮不新建调度框架，全部复用既有
`backend/app/services/agent/{planner,runtime,state_machine,dependencies,gate_policy,tools/}` 与既有
`AgentTask / AgentPlan / AgentStep / ToolCall / BackgroundJob` 记录、审计与租约体系。

判定基准不是“Agent 使用率”，而是：

- 该停的地方是否停住（阻断 / 等待人工 / 拒绝自动确认）；
- 不该继续的步骤是否真的没有执行；
- 人工否决是否被尊重，恢复是否留下可审计痕迹；
- 是否存在静默重复劳动（同一工具被反复调用）。

## 2. 五类决策的实际执行证据

| 案例 | 场景构造 | 期望 | 实际证据（断言） | 结果 |
| --- | --- | --- | --- | --- |
| 一、信息充分 | 真实计划：`search_metadata` → `recall_field_candidates` → `summarize_evidence` | 组工具、执行分析、形成候选，并在人工采用前停止 | 任务 `completed`；三步均 `completed`；召回 `carry.candidate_ids` 非空且 `ranking_mode ∈ {deterministic_recall, model_rerank}`；`ScenarioBusinessMapping / SourceToMartMapping / MartToYbtMapping` 计数为 0；所有 artifact `status != confirmed` | PASS |
| 二、缺少输入 | 直接调用真实工具 `generate_requirement_candidate`，但项目内无 `Requirement`/生成输入 | 明确阻断并给出下一步，不产出空草稿 | 步骤 `blocked`；gaps 含 `requirement_input_missing`；`carry.next_action = {code: create_requirement_input, follow_up_api: …/generation-inputs}`；任务 `blocked`；`task_snapshot()["artifacts"]` 为空 | PASS |
| 三、Skill 未绑定 | 无 `AISkillScopeBinding` 时调用 `rerank_field_candidates` | 显式回退 + 绑定待办，绝不静默绑定最新版本 | 步骤 `completed`；`ranking_mode == deterministic_recall`；`model_metadata.degraded_reason == skill_binding_missing`；摘要不得出现 `model_rerank`；`AISkillScopeBinding` 计数前后不变 | PASS |
| 四、需要人工确认 | 高风险门控工具返回 `policy_comparisons.status = conflict` | 进入 `waiting_human`，保留证据，获人工决定后恢复 | 步骤/任务 `waiting_human`；`carry.analysis.basis` 与 `evidence_count ≥ 1` 保留；`approve` 后 `resume` → 步骤 `completed`、同一证据仍在、任务 `completed`、工具调用次数仍为 1 | PASS |
| 五、人工否决 | 对门控步骤提交 `reject` | 停止后续步骤；只能有界重规划，不得重新采用被否决结论 | 步骤 `blocked`、`error_code = human_rejected`、任务 `blocked`；`retry_task` 返回 409 `human_rejected_requires_replan` 且步骤仍 `blocked`、工具调用次数仍为 1；`replan_task` → 计划版本 1→2、原步骤 `skipped` 且 `error_code = replanned` | PASS |

## 3. 本轮修复的真实缺陷

### 3.1 人工否决可以被“重试”重新跑出来

- 位置：`backend/app/services/agent/runtime.py` 的 `retry_task`。
- 旧行为：只要任务不是 `completed/cancelled` 等终态，就把所有 `failed/blocked` 步骤重置为 `pending` 并用同一计划重跑。
  人工否决把步骤置为 `blocked + human_rejected` 之后，任何人点一次“重试失败步骤”，Agent 就会用同样的输入、同样的工具再产出一次
  被明确否决过的结论，并可能带着它继续完成整条任务。
- 业务风险：银行审批中“人工驳回”是有效业务决定，任务书 1.4 要求“业务拒绝与人工驳回必须保持有效”。静默重跑把否决降级成
  “执行故障”，与“不得重新偷偷采用被否决的结论”直接冲突，且审计上看起来只是一次普通重试。
- 修复：`retry_task` 在重置前先查 `status = blocked AND error_code = human_rejected` 的步骤，存在则直接 409：

  ```json
  {
    "error_code": "human_rejected_requires_replan",
    "message": "被人工否决的步骤不能直接重试：请先发起有边界的需求重分析（replan），再由新的计划重新收集证据。",
    "rejected_step_keys": ["compare"]
  }
  ```

  有边界的 `replan_task` 仍可用：计划版本递增，被否决步骤标记 `skipped/replanned` 保留在审计链里，由新计划重新取证。
- 回归：`test_human_rejection_cannot_be_retried_into_a_silent_re_adoption`；修复前该用例在“重试后步骤仍 blocked”处失败
  （实际被重置为 `pending` 并再次调用工具），修复后通过。前端 `frontend/app/agent/page.tsx` 的“重试失败步骤 / 重新规划”两个动作
  与错误提示都复用同一 `describeError` 通道，409 中的中文说明会直接展示给用户。

## 4. 机制级指标（样本量 5，仅代表机制正确性）

| 指标 | 数值 | 说明 |
| --- | --- | --- |
| 正确阻断次数 | 3 | 缺输入、需人工确认、人工否决各 1 |
| 错误继续执行次数 | 0 | 五例均未出现“该停未停” |
| 被否决结论重新生成次数 | 0（修复后） | 修复前为 1，即缺陷本体 |
| 重复工具调用次数 | 0 | 人工通过后恢复不重跑工具（`calls["n"] == 1`） |
| 自动 confirmed / 正式映射写入 | 0 | 信息充分案例也未写入确认状态 |
| 单任务模型调用数 | 0 | 本批使用确定性内置工具与门控工具，未调用外部模型 |

**不得误读**：以上数字证明的是门控与恢复机制按设计工作，不代表“真实监管业务准确率”。五例均为隔离合成数据，
没有银行专家标注真值。

## 5. 未完成与下一步

1. 案例一~五目前未串联真实外部模型规划（`planner.plan_with_llm`）；本轮验证的是“计划已成立后，运行时的取舍是否正确”。
   真实模型规划路径此前已有 `backend/tests/test_agent_autonomy_scenarios.py` 等用例覆盖，但缺少与五类决策的组合证据。
2. 任务书 6.3 要求的业务收益指标（成功子目标数、人工返工次数、完成一个需求的实际操作成本）尚无独立标注基线，
   `backend/app/services/agent/observability.py::agent_metrics` 已能给出 `model_execution_rate`、`deterministic_fallback_rate`、
   `human_reanalysis_rate` 三个比率，可在有真实任务量后统计。
3. 任务书 6.4 的并发类场景（Worker 中断、审批后重复派发、迟到结果围栏）由既有 Celery 专项证据覆盖
   （`docs/audit/VNEXT_CELERY_RECOVERY-20261022.json`），本轮未重复执行。

## 6. 复现命令

```powershell
cd ai-platform\backend
$env:AUTH_MODE="optional"; $env:TASK_QUEUE_PROVIDER="inline"
.\.venv\Scripts\python.exe -m pytest tests/test_vnext2_agent_decisions.py -q
.\.venv\Scripts\python.exe -m pytest tests -q -k "agent"
```
