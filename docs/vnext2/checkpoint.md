# VNext 2 检查点（docs/vnext2/checkpoint.md）

更新时间：2026-10-23 05:45（Asia/Shanghai）

## 当前状态

- 当前分支：`dsh/vnext-business-accuracy-20261021`
- 起始 HEAD：`6b75384e4bacd94dfae70c58900f09282c7fcde5`
- 已提交：`08f8e9b`（P0-A）、`b5e5ae8`（P0-B）、`525190d`（P0-C 后端闭环与真实模型缺陷修复）
- 当前工作包：**P0-C 浏览器真实闭环（已跑通，待提交） + P1-B（top_limit/cte 归因、复合业务键、SQL→需求关联均已修，剩余 GBase/Hive 语法矩阵与文档）**
- 下一个工作包：P1-B 收尾（语法矩阵 + `docs/vnext2/p1b-sql-semantics.md`）→ P1-A（Agent 五类决策）

## 本轮尚未提交的改动（按工作包）

### A. P0-C 浏览器闭环（REAL_COMPONENT）

1. `scripts/vnext2_p0c_browser_e2e.mjs`（新增，约 520 行）：真实 Chromium 全链路脚本，6 个角色独立上下文（`p0c-biz`/`p0c-tech`/`p0c-pm`/`p0c-breview`/`p0c-treview`/`p0c-freview`），全部动作由页面点击触发 API；含 `waitGenerationOutcome` 轮询、`generateAndQueue`（失败→「重试失败项」→预算耗尽则重新点击「生成候选」开新一轮）、`resolveAnalysisGaps`（每轮 reload 后重新取面板再点）、`refreshLineageSnapshot`、`waitContentVersion`、失败即截图 + 4xx 响应体记录。
2. `scripts/vnext2_p0c_browser_seed.py`（新增）：幂等造数（project 7 / requirement 5 / 一表通目标表 / 借据+合同+产品+期限四张来源表 / 集市映射 / 知识文档与 RULE_V1 / 6 个账号，密码 `Vnext2#P0C2026`）。
3. `scripts/vnext2_p0c_reset.sql`（新增）：重跑前重置演示需求（清 generation items/inputs、revisions>1、content_version=1）。
4. `frontend/components/requirement-workspace/RequirementGapResolver.tsx`（新增）：缺口关闭入口，区分「人工问题」「字段派生缺口（不可用说明关闭）」「已关闭（显示解决依据）」。
5. `frontend/components/requirement-workspace/RequirementWorkspace.tsx`：新增 `isGapClosed` 与 `RequirementGapList`，摘要区分「发现 N 项待确认」/「当前没有待确认缺口（已关闭 N 项）」；已关闭卡片置灰并标注「已关闭」。
6. `frontend/components/requirement-workspace/RequirementGenerationPanel.tsx`：物理字段引用复选框仅对 `section==="lineage"` 渲染；`retry()` 失败时按 `ApiError.detail` 提示「若重试次数已用完…重新点击“生成候选”创建新一轮」。
7. `frontend/app/projects/page.tsx`：`/admin/institutions` 仅在 `can_view_admin` 时请求（原实现所有角色必得 403）。
8. `backend/app/services/requirement_candidates.py`：`SPECIAL_FIELDS` 调整为 `{"business": ("evidence",), "lineage": ("physical_references","evidence")}`（原实现 business 候选不能保留证据，前端勾选必 422）。
9. `backend/app/services/requirement_revisions.py`：`resolve_gap` 对已关闭缺口由“静默返回”改为 409「该缺口已关闭，无需重复处理…」（原实现会让界面版本永远不前进）。
10. `backend/app/api/requirements.py`：`refresh-lineage` 审计调用签名修复；新增 `POST .../gaps/{gap_id}/resolve`；`retry_requirement_generation` 在无 failed/blocked 项时 409 明确提示，若 job 已 completed 但有 blocked 项则先置 failed 再交给队列。
11. `backend/tests/test_requirement_candidate_adoption.py` / `test_requirement_generation_input.py` / `test_vnext2_p0c_real_delivery.py`：对应回归。
12. 证据：`docs/audit/VNEXT2_P0C_BROWSER-20261022.json`（66 步、1019 次 API 调用、`ok:true`）、`docs/audit/vnext2-p0c-browser/*.png`。

### B. P1-B SQL 语义

1. `backend/app/services/lineage/sql_parser.py`：`StatementSemantics` 增 `row_limit`/`order_by`/`cte_signatures`；`_cte_signature` 排除 CTE 名称（等价重命名静默）。
2. `backend/app/services/lineage/version_diff.py`：`top_limit_changed`（limit 变化或 limit 存在时的 order 变化）、`cte_changed`。
3. `backend/app/services/lineage/sql_semantic_diff.py`：`SEMANTIC_LABELS`/`CALIBER_AFFECTING`/`SEMANTIC_FAMILIES` 增两类；`change_item` 对 `unattributed` 变化不再声称影响口径（避免等价重写虚增 caliber 计数）；`filter_changed` 语句级谓词现已归因（不再落 fallback）。
4. `backend/app/services/lineage/join_plan.py`：`declared_key_columns`/`key_coverage`/`partial_unique_keys`，复合唯一键未覆盖时基数保持 unknown 并生成 `missing_join_cardinality` 待确认问题，不自动拼接缺失键。
5. `backend/app/services/lineage/semantic_impact.py` + `backend/app/api/lineage.py`：修复把 `target_field_ids` 当 `requirement_ids` 的真实缺陷，改为按 `Requirement.project_id + scope_json.field_ids` 求真实需求；影响详情返回需求摘要。
6. `backend/app/services/requirement_snapshot.py`：字段计划（field plan）中复合键缺口并入快照缺口列表。
7. 测试：`tests/test_vnext2_sql_rowlimit_cte.py`（12）、`tests/test_vnext2_composite_business_key.py`（3）、`tests/test_vnext2_sql_impact_requirement_link.py`（4，2 正例 2 反例）；`tests/test_sql_semantic_diff_v2.py`/`test_sql_semantic_statement_coverage.py`/`test_sql_lineage.py` 契约同步。

## 测试结果

| 命令 | 结果 |
| --- | --- |
| `node scripts/vnext2_p0c_browser_e2e.mjs`（真实前端 3010 + 后端 8011 + Celery + 真实网关模型 + 真实 PG） | **exit 0，66 步 PASS，1019 次 API 调用** |
| `pytest tests/test_vnext2_p0c_real_delivery.py -q`（真实模型 `deepseek-v4.1-flash`） | 4 passed / 159.94s |
| 全量相关 bundle（P0-C + P1-B + P0-A + P0-B 共 10 文件，`AUTH_MODE=optional` `TASK_QUEUE_PROVIDER=inline`） | **99 passed / 133.16s** |
| SQL/血缘相邻回归（27 文件） | 276 passed（filter 归因修复后 130 passed；后续 110 passed 子集） |
| `npx tsc --noEmit -p tsconfig.json` | 通过（无输出） |

## 环境事实（重要）

- 开发验收网关：`http://47.101.159.7:29988/v1`，模型 `deepseek-v4.1-flash`（推理型；`max_tokens` 不足时 `content` 为空 → 必须 `LLM_MAX_OUTPUT_TOKENS=8192`）。`deepseek-v4-flash` 已下线。
- 真实组件在 WSL docker：PG 5432 / Redis 6379 / Milvus 19530；WSL 空闲自动停机，先 `wsl -e sh -lc "sleep 7200"` 保活再等端口。
- 后端：`cd ai-platform\backend; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8011`（需 `CORS_ORIGINS=http://127.0.0.1:3010`）。改后端代码必须重启（未开 `--reload`）。
- 前端：`npx next dev -p 3010`（**不能** `npm run dev -- --port 3010`，会把端口当目录）。
- 测试默认环境变量：`AUTH_MODE=optional`（`.env` 默认 required）、`TASK_QUEUE_PROVIDER=inline`（不需要 Redis）。
- 夹具重置：`scripts/vnext2_p0c_reset.sql`（project 7 / requirement 5）。

## 当前阻断项

- 无硬阻断。已知缺口（详见 `docs/vnext2/plan.md` 末尾）：
  1. 冻结后新增人工问题只阻断、不自动生成 `RequirementRecheck`。
  2. `POST /questions/{id}/reject` 不写解决依据，故驳回后仍阻断（与“驳回≠口径确认”一致，前端文案需写清）。
  3. `pinned_versions` 未接入产品生成路径。
  4. `order_by` 单独变化仍是显式 limitation（不伪造归因）。
  5. 历史全量基线 1910 passed 未复现，最终回归需重新给出结论。

## 下一步准确动作

1. 提交当前改动（P0-C 浏览器 + P1-B）。
2. P1-B 收尾：GBase/Hive 语法矩阵证据 + `docs/vnext2/p1b-sql-semantics.md`。
3. 进入 P1-A（Agent 五类业务决策）。
