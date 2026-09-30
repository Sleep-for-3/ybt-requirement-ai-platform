# 04｜Agent 开发：把不确定决策放进确定性护栏

## 一、什么是 Agent

Agent 是一个能围绕目标观察状态、选择工具、执行动作、读取结果并决定下一步的系统。LLM 可以充当决策器，但 Agent 还包括：

- 明确的目标和完成条件。
- 可调用工具及权限。
- 状态存储和步骤上限。
- 错误恢复、审计和人工接管。
- 对最终结果的验证。

只有一次 LLM 调用不是 Agent；“循环调用 LLM 直到它说完成”也不是企业级 Agent。

## 二、Workflow 与 Agent 的区别

| 维度 | Workflow | Agent |
|---|---|---|
| 路径 | 预先定义 | 根据状态动态选择 |
| 可预测性 | 高 | 较低 |
| 适用 | 审批、固定 ETL、发布流程 | 信息不完整、需动态取证 |
| 测试 | 分支和状态机 | 轨迹、工具选择、停止条件 |
| 银行建议 | 默认优先 | 只在需要弹性的局部使用 |

一表通最佳形态是 **Workflow 外壳 + Agent 内核**：

```text
固定工作流：创建任务 → Agent 调研 → 人工确认 → 审核 → UAT → 发布
动态 Agent：在“调研”步骤中决定查知识库、目录还是血缘
```

## 三、Tool Calling

### 工具设计原则

- 单一职责：一个工具完成一个可审计动作。
- 参数最小化：不要让模型传 institution_id 来越权，范围从认证上下文注入。
- 读写分离：查询工具可自动执行；创建问题等写操作需幂等，关键写操作需确认。
- 输出限制：行数、字段、字符、超时和敏感信息过滤。
- 每次执行重新鉴权并记录 trace。

### 字段口径 Agent 工具

```text
search_knowledge(query, target_field_id, scenario_id, knowledge_types, top_k)
get_target_field(field_id)
get_catalog_candidates(field_id, scenario_id)
get_lineage(field_id, scenario_id, max_depth)
get_change_impacts(field_id)
get_existing_mappings(field_id, scenario_id)
create_open_question(field_id, scenario_id, owner_role, question, evidence_ids, idempotency_key)
save_draft(field_id, scenario_id, draft, evidence_ids, expected_version)
```

不要提供：

- `execute_any_sql(sql)`
- `read_any_file(path)`
- `call_any_url(url)`
- `update_final_content(...)`

## 四、Planner

Planner 根据任务和当前证据决定下一步。不要让它输出自由文本计划，应用应接收有限动作：

```json
{
  "next_action": "search_knowledge|get_catalog_candidates|get_lineage|create_question|draft|stop",
  "reason_code": "missing_business_evidence|missing_physical_source|conflict|sufficient|budget_exhausted",
  "tool_args": {},
  "expected_evidence": "string",
  "stop_if": ["string"]
}
```

Planner 的决策必须经过代码检查：工具是否允许、参数是否在范围、剩余步数和预算是否足够。

## 五、Executor

Executor 不做“聪明判断”，只负责：

- 校验 Pydantic 参数。
- 从认证主体注入项目/机构范围。
- 重新做权限检查。
- 执行超时、重试和幂等。
- 截断/脱敏结果。
- 写入 tool trace。

Planner 与 Executor 分离的价值：模型可以犯决策错误，但不能突破执行边界。

## 六、Memory

### 三类记忆

- **Working memory**：当前任务状态、已查证据、剩余预算。
- **Episodic memory**：过去任务轨迹和人工反馈，供评测和复用。
- **Semantic memory**：知识库中的正式口径、监管答疑、目录和血缘。

### 银行场景规则

- 不把完整对话历史无限拼回 Prompt。
- 记忆按机构/项目/用户隔离，并设置保留期限。
- 人工最终口径和 AI 草稿必须分开。
- 只有审核通过的内容才能升级为高权威知识。

## 七、Reflection

Reflection 不应是无止境“再想一遍”。更可靠的做法是确定性检查器 + 一次受限修正：

1. Schema 是否有效？
2. 每个关键 claim 是否有 citation？
3. 物理字段是否存在于目录？
4. 是否使用了失效/不可见证据？
5. 业务口径与技术溯源是否混淆？
6. 有冲突是否创建待确认问题？

失败时最多修正一次；仍失败则转人工并保留原轨迹。

## 八、Multi Agent

多 Agent 适合职责和权限真正不同的并行子问题，例如：

- Business Evidence Agent：监管定义、历史口径和场景边界。
- Technical Lineage Agent：目录、SQL/Shell 血缘和变更影响。
- Evidence Critic：检查 claim-citation 和冲突。
- Draft Composer：在验证结果基础上组织草稿。

但第一版不要急于多 Agent。单 Agent + 明确工具 + 确定性验证器更容易评测。只有当单一上下文过大、工具权限需要隔离、任务可并行且指标证明有收益时再拆。

## 九、字段口径分析 Agent 设计

### 1. 输入

```json
{
  "project_id": 1,
  "target_field_id": 25,
  "scenario_id": 3,
  "requested_by": 1001,
  "task_goal": "生成业务口径与技术溯源草稿"
}
```

`project_id` 最终以认证和资源归属校验为准，不能仅相信请求体。

### 2. 状态

```json
{
  "status": "collecting|needs_confirmation|draft_ready|failed",
  "step_no": 0,
  "evidence": [],
  "conflicts": [],
  "open_questions": [],
  "business_draft": null,
  "technical_draft": null,
  "budget": {"max_steps": 8, "max_tool_calls": 12, "max_tokens": 20000},
  "trace_id": "..."
}
```

### 3. 执行流程

```text
加载字段和场景
→ 查询监管/历史知识
→ 判断业务证据是否足够
→ 查询目录候选与现有映射
→ 查询 SQL/Shell 血缘和最新变更影响
→ 证据去重、权威性与冲突检查
→ 缺口变成待确认问题
→ 生成结构化业务/技术草稿
→ 确定性验证
→ 保存 AI 草稿（不更新 final_content）
→ 返回审核任务
```

### 4. 证据判断

每条证据计算的不是单一“相似度”，而是：

- visibility：当前用户是否可见。
- authority：监管正式文件 > 监管答疑 > 已审核口径 > 人工备注 > AI 草稿。
- recency：是否为当前有效版本。
- applicability：机构、字段、场景是否适用。
- directness：是否直接支持该 claim。
- consistency：是否与其他高权威证据冲突。

高置信结论至少要求一条高权威直接证据，或两条独立、无冲突的中权威证据；物理字段还必须通过目录/血缘验证。

### 5. 创建待确认问题

问题必须可执行：

```json
{
  "question": "贷款场景是否包含已核销但仍有追索权的合同？",
  "owner_role": "business",
  "reason": "监管定义与 2024 历史口径范围冲突",
  "evidence_ids": [321, 654],
  "blocking": true,
  "idempotency_key": "project-field-scenario-question-type"
}
```

避免“请确认口径”这种无上下文问题。

### 6. 输出草稿

- `business_draft`：范围、定义、规则、特殊情况、citation、待确认项。
- `technical_draft`：来源系统/表/字段、处理逻辑、lineage evidence、变更状态。
- `decision_summary`：简短可审计因素，不保存冗长私有推理。
- `confidence`：由代码规则计算，模型只能提供特征。

## 十、异常与停止条件

- 连续两次相同工具调用 → 停止并标记循环。
- 工具错误不可重试类型（403、参数越权）→ 立即失败。
- 临时错误最多指数退避重试两次。
- 步数、Token、费用任一超限 → 保存中间状态，转人工。
- 证据冲突未解决 → `needs_confirmation`，不能生成高置信最终草稿。
- 物理字段无法验证 → 置空字段并创建技术问题。

## 十一、Agent 评测

- Tool selection accuracy：该查目录时是否查目录。
- Argument validity：参数 Schema 和作用域正确率。
- Task success：草稿是否达到审核入口条件。
- Evidence coverage：关键 claim 的证据覆盖。
- Unsafe action rate：目标 0。
- Loop/timeout rate、平均步骤、Token、成本。
- Human edit distance：审核人员修改量。
- Open question usefulness：问题被直接回答/验收的比例。

## 十二、面试回答模板

> 我不会把整个审核流程都交给 Agent。外层仍是确定性的业务 Workflow，Agent 只负责证据调研和草稿生成。Planner 只能从有限动作中选择，Executor 负责参数校验、项目权限、超时和审计；物理字段、citation 和证据充分性由确定性验证器判断。无证据或冲突时创建可分派的待确认问题，AI 草稿永不覆盖人工 final_content。

## 阶段项目作业

1. 写出 8 个工具的 Pydantic 输入/输出 Schema。
2. 用状态机实现单 Agent 原型，先不引入框架。
3. 建 20 个轨迹案例：成功 8、缺证据 4、冲突 4、权限/工具失败 4。
4. 对比“单次 RAG 生成”和“Agent 取证”在准确率、步骤、成本上的差异。
