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

确认 `compare_policy_and_implementation` 的 task_key，然后为 `requirement_candidate_generation` 建定义（含 IO schema 与 SafetyPrompt）并跑通一次真实模型调用（`model_execution.executed=true`）。

## 4. 漂移判定

`continue` — 与目标一致（真实模型化主链），未新增 Agent 概念；无阻断状态。
