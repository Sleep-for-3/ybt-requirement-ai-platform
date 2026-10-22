# VNext 2 检查点（docs/vnext2/checkpoint.md）

更新时间：2026-10-23 01:10（Asia/Shanghai）

## 当前状态

- 当前分支：`dsh/vnext-business-accuracy-20261021`
- 起始 HEAD：`6b75384e4bacd94dfae70c58900f09282c7fcde5`
- 已提交：`08f8e9b`（P0-A）、`b5e5ae8`（P0-B）、`525190d`（P0-C 后端闭环）、`7d37cc7`（P0-C 浏览器闭环 + P1-B 第一批）、`182d479`（P1-B 第二批：方言矩阵/等价重写/filter 归因/文档）
- 当前工作包：**P1-A（Agent 五类业务决策）——代码与文档已完成，待提交**
- 下一个工作包：P1-C（黄金集评测体系）

## 本轮尚未提交的改动（P1-A）

1. `backend/app/services/agent/runtime.py`：`retry_task` 增加人工否决守卫——存在 `status=blocked and error_code=human_rejected` 的步骤时返回 409 `human_rejected_requires_replan`，禁止用同一计划重跑被否决结论；有边界的 `replan_task` 仍是合法恢复路径。
2. `backend/tests/test_vnext2_agent_decisions.py`（新增，373 行）：五类决策各一例——信息充分（真实工具链 + 人工采用边界）、缺少输入（`requirement_input_missing` + `next_action`）、Skill 未绑定（`skill_binding_missing` 回退且不自动绑定）、需人工确认（`waiting_human` 保留证据、批准后恢复不重调工具）、人工否决（重试 409、重规划版本递增）。
3. `docs/vnext2/p1a-agent-decisions.md`（新增）：五案例证据表、缺陷前后对比、机制级指标、未完成项。
4. `docs/vnext2/plan.md`：P1-A 由 `TODO` 改为 `DONE`。

## 测试结果

| 命令 | 结果 |
| --- | --- |
| `pytest tests/test_vnext2_agent_decisions.py -q` | **5 passed / 7.64s** |
| `pytest tests -q -k "agent"` | **224 passed, 1751 deselected / 72.34s** |
| `pytest tests -q -k "sql or lineage or semantic or impact"`（P1-B 收尾，已提交） | 365 passed / 261.55s |

## 环境事实（重要）

- 开发验收网关：`http://47.101.159.7:29988/v1`，模型 `deepseek-v4.1-flash`（推理型；`max_tokens` 不足时 `content` 为空 → 必须 `LLM_MAX_OUTPUT_TOKENS=8192`）。`deepseek-v4-flash` 已下线。
- 真实组件在 WSL docker：PG 5432 / Redis 6379 / Milvus 19530；WSL 空闲自动停机，先 `wsl -e sh -lc "sleep 7200"` 保活再等端口。
- 后端：`cd ai-platform\backend; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8011`（需 `CORS_ORIGINS=http://127.0.0.1:3010`）。改后端代码必须重启（未开 `--reload`）。
- 前端：`npx next dev -p 3010`（**不能** `npm run dev -- --port 3010`）。
- 测试默认环境变量：`AUTH_MODE=optional`（`.env` 默认 required）、`TASK_QUEUE_PROVIDER=inline`（不需要 Redis）。
- 夹具重置：`scripts/vnext2_p0c_reset.sql`（project 7 / requirement 5，须 `ON_ERROR_STOP=1`）。

## 当前阻断项

- 无硬阻断。已知缺口（详见 `docs/vnext2/plan.md` 末尾）：
  1. 冻结后新增人工问题只阻断、不自动生成 `RequirementRecheck`。
  2. `POST /questions/{id}/reject` 不写解决依据，故驳回后仍阻断（与“驳回≠口径确认”一致，前端文案需写清）。
  3. `pinned_versions` 未接入产品生成路径。
  4. `order_by` 单独变化仍是显式 limitation（不伪造归因）。
  5. 历史全量基线 1910 passed 未复现，最终回归需重新给出结论。
  6. 五类 Agent 决策目前是机制级证据（`MOCK`），业务收益指标缺独立标注基线。

## 下一步准确动作

1. 提交 P1-A。
2. 进入 P1-C：`backend/app/services/evaluation/regulatory_golden.py` + `data/vnext_golden_set_v1.json` + `tests/test_vnext_regulatory_golden.py`；把 `reviewer_id` 非空即“已标注”改为结构化标注元数据（案例作者/预期作者/独立标注人/时间/依据/状态/争议/数据集版本），其余案例族用真实生产入口执行并显式标 `not_run`，指标带样本量与真实性级别。
3. P2-A（组件稳定性 / `auth/actors.py` / 规模性能）→ P2-B（工作台）→ 全量回归 + `docs/vnext2/final-report.md`。
