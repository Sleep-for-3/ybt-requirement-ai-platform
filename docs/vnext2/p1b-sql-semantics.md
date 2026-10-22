# P1-B 复杂 SQL 与监管口径变化 —— 实现、缺陷与验收证据

- 生成时间：2026-10-23
- 分支：`dsh/vnext-business-accuracy-20261021`
- 证据级别：`REAL_COMPONENT`（真实 sqlglot 解析器 + 真实血缘/比较/影响服务，PostgreSQL 侧未参与本项）
- 真值级别：`合成期望`（用例由本轮构造，判断标准写入用例，未经银行专家独立标注）
- 原始记录：`docs/audit/VNEXT2_SQL_DIALECT_MATRIX-20261023.json`

## 1. 本项要解决的问题

任务书第七章要求区分七类结果，而不是“AST 能建出来就算成功”：

1. 解析成功／2. 部分解析／3. 无法解析；
4. 字段血缘完整／5. 部分完整；
6. SQL 语义变化已归因／7. 变化存在但无法归因。

本轮不改动既有 `group_by` / `distinct` / `union_mode` / `having` / `join_type` 逻辑，只补三类空白与一类误报：

| 家族 | 改前 | 改后 |
| --- | --- | --- |
| `top_limit` | 不可归因（fallback） | 可归因 `top_limit_changed`（limit + ORDER BY 合并为“行数范围”） |
| `cte` | CTE 内部加工变化被静默吞掉 | 可归因 `cte_changed`（投影 + WHERE + 聚合签名） |
| `order_by` | 不可归因 | **仍不可归因，显式 limitation**（理由见 §3） |
| 未归因兜底 | 被当作“口径影响” | 不再计入 `affects_caliber`，标注“（未归因 AST 变化）” |

家族覆盖度由 `36/39` 变为 `38/39`（`SQL_SEMANTIC_CLASSES`），**不追求 39/39**。

## 2. 代码入口

- 语句语义抽取：`backend/app/services/lineage/sql_parser.py`
  - `StatementSemantics` 新增 `row_limit` / `order_by` / `cte_signatures` / `filters`。
  - `_cte_signature(cte)`：返回 CTE body 的规范化投影 + WHERE 谓词多重集，**故意不含 CTE 名称**（重命名是等价重写）。
- 版本比较：`backend/app/services/lineage/version_diff.py`
  - `_semantic_ast`：按方言解析后做名称规范化再渲染，用于判断“是否存在任何 AST 差异”。
  - `_canonicalize_cte_names` / `_canonicalize_table_aliases` / `_normalize_transformation`：等价重写归一。
  - `_condition_changes(..., normalizer=...)`：血缘边属性比较；`transformation_expression` 使用限定符不敏感比较。
  - `ChangeItemSpec` 新增 `attributed` 字段；整段 AST 兜底项传 `attributed=False`。
- 语义标签与家族声明：`backend/app/services/lineage/sql_semantic_diff.py`
  - `SEMANTIC_LABELS`：`top_limit_changed`（取数行数范围（TOP/LIMIT）发生变化）、`cte_changed`（CTE 内部加工逻辑发生变化）、`filter_changed` 既有。
  - `change_item`：`affects_caliber = (not unattributed) and category in CALIBER_AFFECTING`；未归因项 label 追加“（未归因 AST 变化）”，statement 改为“未能把该变化归因到结构化语义维度，需人工对照 SQL 原文判断”。
  - `SEMANTIC_FAMILIES`：`top_limit` / `cte` 升级为 `DETECTION_COMPARATOR`；`order_by` 保持 `DETECTION_UNSUPPORTED` 并写明与 `top_limit`、`window_function` 的分工。
- 方言：`backend/app/services/lineage/dialects.py::resolve_dialect` 统一把上传方言字符串映射到 sqlglot 方言（`gbase` → `mysql`，`hive` → `hive`，未知 → `None` 并记录 warning），解析与比较共用同一映射。

## 3. `order_by` 为什么仍然不作为归因项

- 单独的 `ORDER BY` 通常只影响结果展示顺序，不改变写入目标表的集合；把它报成口径变化会制造大量误报。
- 但 `ORDER BY` 与 `LIMIT/TOP` 同时出现时，排序决定“取哪 N 行”，已由 `top_limit` 家族承接。
- 窗口函数内的 `ORDER BY`（`ROW_NUMBER() OVER (ORDER BY ...)`）参与选中记录，属于 `window_function` 家族，由既有逻辑比较。
- 只剩一种无法确证的场景：`ORDER BY` 变化但无 `LIMIT`，且下游消费方依赖行序。本轮不猜，输出**未归因 AST 变化**（`affects_caliber=False`），要求人工确认。理由写进 `SEMANTIC_FAMILIES["order_by"].note`，并由 `tests/test_vnext2_sql_rowlimit_cte.py` 与语法矩阵的 `order_by_only` 用例固定。

## 4. 本轮修复的真实缺陷

| # | 缺陷 | 代码入口 | 用户可见后果 | 修复 |
| --- | --- | --- | --- | --- |
| 1 | `gbase`/`hive` 方言字符串直接传给 `sqlglot.parse(read=...)`，抛 `ValueError: Unknown dialect` | `version_diff._semantic_ast` | 上传 GBase 脚本后“SQL 变化分析”整段 500，历史版本无法比较 | 统一走 `resolve_dialect`，未知方言降级为默认方言并记录 warning |
| 2 | CTE 内部 WHERE/投影/聚合变化，外层投影不变时被判为 `non_semantic`（“无实质变化”） | `version_diff._statement_semantic_changes` | 监管口径被 CTE 悄悄改掉，影响分析放行 | 新增 `cte_signatures` 维度 + `cte_changed` |
| 3 | CTE 签名包含 CTE 名称，纯重命名被报成“取值逻辑变化” | `sql_parser._cte_signature` | 等价重构触发人工复核与口径告警 | 签名不含名称；AST 侧对 CTE 名称与表别名做位置化规范化 |
| 4 | 普通 `SELECT` 的 WHERE 谓词变化没有任何结构化维度承接，掉进兜底桶 | `sql_parser.StatementSemantics` / `version_diff` | `where deal_status is not null` → `in ('ACTIVE','MATURED')` 这类真实过滤范围变化不再标记“影响口径” | 新增 `filters` 维度；边层已有 `filter_changed` 时不重复计数 |
| 5 | 整段 AST 兜底项按 category 表判定，导致未归因变化也宣称“可能改变统计口径” | `sql_semantic_diff.change_item` | 等价重写虚增 `caliber_affecting_count`，审核人被迫逐个核对 | `attributed` 标志；未归因项不计口径影响并显式标注 |
| 6 | 表别名/CTE 名称重命名在 AST 文本层面不同 → 报“未归因变化” | `version_diff` 规范化 | 等价重构产生噪声告警 | `_canonicalize_cte_names` + `_canonicalize_table_aliases` + 裸列限定符不敏感比较 |
| 7 | `semantic_impact.resolve_semantic_impact` 把 `target_field_ids` 当 `requirement_ids` 返回 | `backend/app/services/lineage/semantic_impact.py:31/215` | “受影响需求”实际是目标字段 id，页面关联到错误需求；SQL 变化无法正确追踪到监管需求 | 新增 `_requirements_for_target_fields`：按 `Requirement.project_id` + `scope_json.field_ids` 交集求真实需求；`api/lineage.py`、`impact_view.py`、`agent/tools/builtin.py` 的消费口径同步修正 |

第 7 项的连带修正：

- `backend/app/api/lineage.py`：影响详情输出真实需求摘要（name/content_version/target_table_id/field_ids），字段影响改按 `impact.affected_target_field_ids_json` 查询，不再拿需求 id 当 `TargetField.id`。
- `backend/app/services/lineage/impact_view.py`：关联类型由 `target_field` 改为 `requirement`。
- `backend/tests/test_sql_lineage.py`：原断言 `affected_requirement_ids_json == [target.id]`（把字段 id 当需求 id）按正确契约更新；`backend/tests/test_lineage_impact_detail.py` 的夹具改为真实需求 id。
- 回归证明：`tests/test_vnext2_sql_impact_requirement_link.py`（4 例，2 正例 2 反例）——JOIN 类型变化与 GROUP BY/ROW_NUMBER 变化能找到受影响需求并生成复核任务；仅格式/注释变化与等价 SQL 不生成复核任务，也不误关联无关项目需求。

## 5. 复合业务键（P1-B 4）

- `backend/app/services/lineage/join_plan.py`
  - `declared_key_columns(table_ref, entity)`：读取目标表声明的唯一键（支持 `is_primary_key` 之外的复合唯一键），返回全量列。
  - `_key_coverage(key_pairs)`：按“声明键是否被关联条件完整覆盖”计算 `complete` / `unique`。
  - `plan["key_coverage"]` / `plan["partial_unique_keys"]`：仅当**完整**覆盖声明唯一键时才允许 1:1 / N:1；只按 `PRODUCT_ID` 关联 `(PRODUCT_ID, TERM_NO)` 维度表时，基数保持 `unknown`。
- `backend/app/services/requirement_snapshot.py:981-1010`：`cardinality_basis != both_sides_declared` 时生成 `missing_join_cardinality` 待确认问题，文案明确“关联只覆盖了复合唯一键的一部分”“关联后行数会放大”“不得视为一对一”。
- **不自动拼接**缺失键：产品不会把 `PRODUCT_ID` 私自改成 `PRODUCT_ID + TERM_NO`，避免破坏与其它表的原始产品标识关联；只能由业务确认后回填（`requirement_snapshot._gap_actions` 已给出动作）。
- 测试：`backend/tests/test_vnext2_composite_business_key.py`（3 例）——复合键部分覆盖 → `partial_unique_keys` 命中且基数 unknown；完整覆盖 → 1:1；单列主键表不受复合逻辑影响。

## 6. GBase/Hive 语法矩阵

语料与断言集中在 `backend/tests/vnext2_sql_matrix_cases.py`（测试与证据脚本共用，避免漂移），执行器：

- 一键复跑：`backend\.venv\Scripts\python.exe scripts\vnext2_sql_dialect_matrix.py`（在 `ai-platform\backend` 目录下执行）
- 输出：控制台逐条状态 + `docs/audit/VNEXT2_SQL_DIALECT_MATRIX-20261023.json`

### 6.1 解析矩阵（15 例，15/15 与期望一致）

| 用例 | 方言 | 期望/实际 | 边数 | 目标表 |
| --- | --- | --- | --- | --- |
| `multi_layer_insert_join` | gbase | parsed | 9 | `MART.DW_LOAN_SNAPSHOT` |
| `temp_table_two_step` | gbase | parsed | 13 | `MART.DW_LOAN_SNAPSHOT`, `TMP.LOAN_BASE` |
| `cte_hive_partition` | hive | parsed | 6 | `mart.dw_loan_snapshot` |
| `union_all_hive` | hive | parsed | 7 | `mart.dw_loan_snapshot` |
| `group_by_case_when` | gbase | parsed | 6 | `mart.dw_loan_balance` |
| `window_row_number` | hive | parsed | 5 | `mart.dw_loan_latest` |
| `full_outer_join` | gbase | parsed | 6 | `mart.dw_product_diff` |
| `subquery_date_range` | gbase | parsed | 5 | `mart.dw_loan_snapshot` |
| `template_variable_resolved` | gbase | parsed | 3 | `mart.dw_loan_snapshot` |
| `template_variable_unresolved` | gbase | parsed | 3 | `mart.dw_loan_snapshot` |
| `null_concat_gbase` | gbase | parsed | 4 | `mart.dw_loan_snapshot` |
| `hive_functions` | hive | parsed | 6 | `mart.dw_loan_snapshot` |
| `column_alias_rename` | gbase | parsed | 3 | `mart.dw_loan_snapshot` |
| `unparsable_single` | gbase | failed | 0 | — |
| `partially_parsed_script` | gbase | partially_parsed | 3 | `mart.dw_loan_snapshot` |

说明：
- 这些用例覆盖任务书列出的多层 `INSERT SELECT`、临时表、CTE、子查询、`UNION ALL`、`GROUP BY`、`CASE WHEN`、日期过滤/分区增量、窗口函数/`ROW_NUMBER`、`FULL/LEFT/INNER JOIN`、字段重命名、库表限定名、变量替换、`NULL` 参与 `CONCAT`、GBase/Hive 特有函数。
- `unparsable_single` 证明“无法解析”会如实返回 `failed`，不伪造血缘。
- `partially_parsed_script` 证明“部分解析”独立存在：多语句脚本中第二段语法不被支持时，第一段仍产生血缘并标记 `partially_parsed`。
- **边数不等于字段血缘完整**：矩阵只断言“主链路可解析、目标表识别正确”，字段级完整性由 `tests/test_lineage_paths.py` 等既有用例覆盖，验收口径见 §7。

### 6.2 语义变化矩阵（8 例，8/8 与期望一致）

| 用例 | 语义变化 | 归因类别 | 口径影响 |
| --- | --- | --- | --- |
| `join_type_inner_to_left` | 是 | `join_type_changed` | 是（1） |
| `group_by_key_added` | 是 | `group_by_changed` | 是（1） |
| `row_limit_changed` | 是 | `top_limit_changed` | 是（1） |
| `cte_inner_filter_changed` | 是 | `cte_changed` + `filter_changed` | 是（2） |
| `formatting_and_comments_only` | 否 | `non_semantic` | 否 |
| `alias_rename_only` | 否 | `non_semantic` | 否 |
| `order_by_only` | 是（未归因） | `transformation_changed`（unattributed） | **否** |
| `function_variant_same_semantics` | 否 | `non_semantic` | 否 |

- 2 个有效变化正例（JOIN 类型、GROUP BY）与 2 个等价变化反例（格式/注释、CTE+别名重命名）满足任务书“至少两个正例两个反例”。
- 额外覆盖 `top_limit`（正例）、`cte`（正例）、`order_by`（变化存在但不可归因）、方言等价函数（不得误报）。

## 7. 测试清单与命令

```powershell
cd ai-platform\backend
$env:AUTH_MODE="optional"; $env:TASK_QUEUE_PROVIDER="inline"
.\.venv\Scripts\python.exe -m pytest tests/test_vnext2_sql_rowlimit_cte.py tests/test_vnext2_composite_business_key.py tests/test_vnext2_sql_impact_requirement_link.py -q
.\.venv\Scripts\python.exe -m pytest tests -q -k "sql or lineage or semantic or impact"
```

本轮实测：

| 范围 | 结果 |
| --- | --- |
| `test_vnext2_sql_rowlimit_cte.py`（12） | 通过 |
| `test_vnext2_composite_business_key.py`（3） | 通过 |
| `test_vnext2_sql_impact_requirement_link.py`（4） | 通过 |
| 语法矩阵证据脚本 | `parse_status_matched 15/15`、`change_expectations_matched 8/8` |
| `pytest -k "sql or lineage or semantic or impact"` | `365 passed, 1605 deselected`（261.55s） |

## 8. 仍然存在的限制（如实记录）

1. `order_by` 单独变化不归因；这会让“行序被下游依赖”的极少数场景只能通过人工确认。
2. 未归因变化（`unattributed_ast_change`）仍会出现在 facts 中，但 `affects_caliber=False`；审核人看到的是“需要人工对照 SQL 原文”，不是“已确认影响口径”。
3. 方言映射是白名单式（`gbase`→`mysql`、`hive`→`hive` 等）：银行现场若使用更少见的 GBase 8a 语法（如自定义函数、`LOAD DATA`、存储过程），解析可能落到 `partially_parsed`/`failed`，此时产品只报告 limitation，不做猜测。
4. 字段级血缘完整性依赖元数据（源表/字段是否已登记）：未登记时矩阵只保证“解析成功”，不宣称血缘完整。
5. 本轮未在真实 PostgreSQL 上重放 SQL 变化→需求→复核任务的完整链路（表结构无关，但接口链路只经 SQLite 事务测试与既有 `test_sql_lineage.py` 覆盖）；真实组件层面的复核任务证据见 `docs/vnext2/p0c-real-delivery.md` 与浏览器证据。
