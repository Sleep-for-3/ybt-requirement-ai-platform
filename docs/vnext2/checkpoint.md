# VNext 2 检查点（docs/vnext2/checkpoint.md）

更新时间：2026-10-23 00:55（Asia/Shanghai）

## 当前状态

- 当前分支：`dsh/vnext-business-accuracy-20261021`
- 起始 HEAD：`6b75384e4bacd94dfae70c58900f09282c7fcde5`
- 已提交：`08f8e9b`（P0-A）、`b5e5ae8`（P0-B）、`525190d`（P0-C 后端闭环）、`7d37cc7`（P0-C 浏览器闭环 + P1-B 第一批：top_limit/cte/复合业务键/SQL→需求关联）
- 当前工作包：**P1-B 第二批（方言矩阵 + filter 归因 + 未归因不宣称口径 + 等价重写静默 + 文档）——已全部通过，待提交**
- 下一个工作包：P1-A（Agent 五类业务决策）

## 本轮尚未提交的改动（P1-B 第二批）

1. `backend/app/services/lineage/dialects.py`（新增）：`resolve_dialect` 把上传方言字符串（`gbase`/`hive`/`mysql`…）统一映射到 sqlglot 方言，未知方言降级为默认并记录 warning；解析与比较共用。
2. `backend/app/services/lineage/version_diff.py`
   - `_semantic_ast` 走 `resolve_dialect`（修复 `gbase` 直接传 `sqlglot.parse` 抛 `Unknown dialect` → 变化分析 500）。
   - 新增 `_canonicalize_cte_names`、`_canonicalize_table_aliases`、`_normalize_transformation`：等价重写（CTE/别名重命名、裸列限定符）不再产生未归因噪声。
   - `_condition_changes(..., normalizer=...)`；`StatementSemantics.filters` 参与比较，边层无 `filter_changed` 时补 `filter_changed`。
   - `ChangeItemSpec.attributed`（整段 AST 兜底项 `attributed=False`）。
3. `backend/app/services/lineage/sql_parser.py`：`StatementSemantics` 增 `filters`（非 CTE 语句级 WHERE 谓词，CTE 内部交给 `cte_signatures`）。
4. `backend/tests/vnext2_sql_matrix_cases.py`（新增）：15 个 GBase/Hive 解析用例 + 8 个语义变化用例（2 有效变化正例、2 等价反例、top_limit/cte/order_by/函数等价）。
5. `scripts/vnext2_sql_dialect_matrix.py`（新增）：一键执行矩阵并写 `docs/audit/VNEXT2_SQL_DIALECT_MATRIX-20261023.json`。
6. `docs/vnext2/p1b-sql-semantics.md`（新增）：实现、7 个真实缺陷、矩阵结果、限制。
7. `docs/vnext2/plan.md`：P1-B 标 `DONE`，补第二批缺陷与限制。

## 测试结果

| 命令 | 结果 |
| --- | --- |
| `backend\.venv\Scripts\python.exe scripts\vnext2_sql_dialect_matrix.py` | `parse_status_matched 15/15`、`change_expectations_matched 8/8` |
| `pytest tests -q -k "sql or lineage or semantic or impact"`（`AUTH_MODE=optional`、`TASK_QUEUE_PROVIDER=inline`） | **365 passed, 1605 deselected / 261.55s** |
| `pytest tests/test_vnext2_sql_rowlimit_cte.py tests/test_vnext2_composite_business_key.py tests/test_vnext2_sql_impact_requirement_link.py` | 19 passed（见 `p1b-sql-semantics.md` §7） |

## 环境事实（重要）

- 开发验收网关：`http://47.101.159.7:29988/v1`，模型 `deepseek-v4.1-flash`（推理型；`max_tokens` 不足时 `content` 为空 → 必须 `LLM_MAX_OUTPUT_TOKENS=8192`）。`deepseek-v4-flash` 已下线。
- 真实组件在 WSL docker：PG 5432 / Redis 6379 / Milvus 19530；WSL 空闲自动停机，先 `wsl -e sh -lc "sleep 7200"` 保活再等端口。
- 后端：`cd ai-platform\backend; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8011`（需 `CORS_ORIGINS=http://127.0.0.1:3010`）。改后端代码必须重启（未开 `--reload`）。
- 前端：`npx next dev -p 3010`（**不能** `npm run dev -- --port 3010`，会把端口当目录）。
- 测试默认环境变量：`AUTH_MODE=optional`（`.env` 默认 required）、`TASK_QUEUE_PROVIDER=inline`（不需要 Redis）。
- 夹具重置：`scripts/vnext2_p0c_reset.sql`（project 7 / requirement 5，须 `ON_ERROR_STOP=1`）。

## 当前阻断项

- 无硬阻断。已知缺口（详见 `docs/vnext2/plan.md` 末尾）：
  1. 冻结后新增人工问题只阻断、不自动生成 `RequirementRecheck`。
  2. `POST /questions/{id}/reject` 不写解决依据，故驳回后仍阻断（与“驳回≠口径确认”一致，前端文案需写清）。
  3. `pinned_versions` 未接入产品生成路径。
  4. `order_by` 单独变化仍是显式 limitation（不伪造归因）。
  5. 历史全量基线 1910 passed 未复现，最终回归需重新给出结论。

## 下一步准确动作

1. 提交 P1-B 第二批。
2. 进入 P1-A：复用 `backend/app/services/agent/{planner,runtime,state_machine,gate_policy,tools}`，为五类决策（信息充分 / 缺输入 / Skill 未绑定 / 需人工确认 / 人工否决）各建真实执行用例，先复现“应阻断而未阻断/应停止而继续”的缺陷再改。
3. P1-C 黄金集评测体系（结构化标注元数据 + `not_run` + 指标带样本量）。
