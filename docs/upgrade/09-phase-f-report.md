# Phase F 阶段报告：结构化字段方案与缺口建议增强

状态：已完成增量实现
日期：2026-09-10
依赖阶段：Phase A（结构化需求快照）、Phase B（业务名称契约）、Phase C（血缘版本）、Phase D（端到端路径）、Phase E（脚本监控与影响业务化）
计划文档：`docs/upgrade/08-phase-f-plan.md`

## 1. 本阶段解决的问题

执行规格第 6.2/6.3/6.4 节要求需求文档“精确到表、字段、关联条件和取数规则”，并要求当前数据不足时生成有证据的字段/表/桥接表/字典表建议。Phase A 的快照虽然已经冻结事实，但 `join_plans` 只有 `raw_condition` 文本、`structured` 恒为 `false`，缺口建议也只有 6 条无证据的固定规则，且没有把 Phase D 的端到端路径与路径缺口收进字段方案。

本阶段补齐这三块，并且在无法证明时明确返回“未解析”，不做推断。

## 2. 实现内容

### 2.1 确定性的关联条件结构化（新增模块）

`backend/app/services/lineage/join_plan.py`：`JoinPlanStructurer`

- 解析已在 `SourceToMartMapping.join_condition` / `MartToYbtMapping.join_condition` 中保存的文本：去注释、按括号深度切分 `AND`、识别等值与范围操作符、解析 `库.模式.表.字段` 限定名。
- 表解析只认项目内已登记的 `CatalogTable`、`MartTable`、`SourceTable`、`TargetTable`（支持物理表名、表编码、表名，以及 `schema.table` 形式）。
- **未知表限定符不再回退到“全局同名字段”**：`LEGACY_SYSTEM.CUST_ID` 这类写法必须保持未解析，避免把无法证明的关联写成事实（这一条由 Phase A 既有测试先暴露出来，已修正）。
- 基数只在有主键/唯一键证据时给出：双方都有声明 → `1:1`；只有一侧有 → `1:N`/`N:1` 并标记 `cardinality_basis`；无证据 → `unknown`。
- 时间对齐键（`dt/date/stat_date/统计日期/账期` 等）单独归入 `time_conditions`；非等值条件保留在 `range_conditions`，不推断。
- `structured=true` 仅在“所有键对都解析为项目内资产且无未解析写法”时成立；`unresolved_references` 记录无法解析的写法。

### 2.2 字段方案（RequirementFieldPlan）

`field_plan` 新增：`plan_version`、`target_field`、`source_paths`、`path_resolution`、`gap_summary`、`requires_review`，并把 `join_plans` 替换为结构化结果（兼容键 `mapping_type/mapping_id/raw_condition/status/structured/review_required/note` 全部保留）。

`source_paths` 复用 Phase D 的 `LineagePathResolver`：每个靶字段按“已发布血缘版本 + 深度 10 + 每字段最多 3 条路径”解析，并压缩为按层级排序的 `hops`（各层中文业务名、技术名、层级名、备注质量）、`transformations`（边上的 Join/Filter/聚合/码值/脚本行号）、`evidence_refs`、`complete`、`confidence`、`truncated`。

### 2.3 缺口建议（GapRecommendation）

每条缺口统一携带 `gap_type / problem_statement / recommended_change / alternative_options / rationale / evidence_refs / affected_assets / estimated_impact / confidence_level / approval_status / source / dedupe_key`，并区分两类来源：

- `source="requirement_snapshot"`：项目内事实缺口。新增/扩展类型：`business_mapping_missing`、`source_field_missing`、`source_field_incomplete`、`source_field_not_in_catalog`、`mart_mapping_missing`、`source_to_mart_mapping_missing`、`join_condition_missing`、`unresolved_join_key`、`missing_join_cardinality`、`missing_time_field`、`missing_dictionary_table`、`missing_bridge_table`。
- `source="lineage_path"`：Phase D 解析器的路径缺口（`no_lineage_path`、`missing_technical_evidence`、`missing_lineage_revision`、`incomplete_terminal_path`、`missing_business_comment`、`missing_asset_binding`），汇聚时把节点 ID 转换成中文业务名并补齐 `pending_review`。

覆盖执行规格 6.4 的建议项：新增字段、新增来源表、新增监管集市表、桥接表、字典/码表、统一业务主键、统计/生效日期、数据粒度、同步任务。

### 2.4 快照级方案摘要

`plan_summary` 提供 `field_plan_count`、`fields_with_gaps`、`fields_with_complete_path`、`join_plan_count`、`structured_join_count`、`structured_join_ratio`、`gap_counts_by_type`、`gap_counts_by_source`、`fields_missing_business_comment` 和 `path_resolution`（预算、截断、告警）。沿用 Phase 13 门禁：分母为空时 `structured_join_ratio` 返回 `null`，不显示 0%。

## 3. 本阶段刻意不做的事

1. 未新增 Alembic 迁移：结构化结果只存在于不可变快照 JSON，`alembic heads` 仍为 `202609100025`，不新增/修改任何表结构。
2. 未新增 JoinPlan/GapRecommendation 数据表，也未改动 `SourceToMartMapping` / `MartToYbtMapping` 字段语义（ADR-001）。
3. 未自动生成关联键、基数或时间口径；无法证明的一律标记未解析并要求人工评审（ADR-005）。
4. 未改前端：`source_paths` / `gap_summary` 等契约留给 Phase G 的星云与业务化展示消费。

## 4. 验证

| 检查项 | 命令 | 结果 |
| --- | --- | --- |
| Phase F 定向用例 | `python -m pytest -q tests/test_requirement_field_plans.py` | 9 passed |
| Phase A 快照回归 | `python -m pytest -q tests/test_requirement_snapshots.py` | 9 passed |
| 快照 + 方案 + 路径 + 版本 | `tests/test_requirement_snapshots.py`、`tests/test_requirement_field_plans.py`、`tests/test_lineage_paths.py`、`tests/test_lineage_revisions.py` | 28 passed |
| SQL 血缘/业务名/监控/影响详情 | `tests/test_sql_lineage.py`、`tests/test_asset_display.py`、`tests/test_lineage_monitoring.py`、`tests/test_lineage_impact_detail.py` | 41 passed |
| 交付与工作台投影 | `tests/test_deliverables.py`、`tests/test_requirement_workspace_projection.py` | 16 passed |
| 后端全量回归 | `cd backend; $env:STORAGE_DIR=<工作区隔离目录>; python -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp` | **536 passed, 0 failed**（15 分 57 秒；Phase E 为 527，新增 9 个用例） |
| 迁移链 | `python -m alembic heads` | `202609100025 (head)`，本阶段未新增迁移 |

覆盖的关键行为：

- 双侧都可解析时 `structured=true` 且 `key_pairs` 携带左右字段的中文业务名；
- 未知表限定符保持未解析并产生 `unresolved_join_key`（回归测试直接捕获过一次过度解析）；
- 双侧声明主键时 `1:1` 且不再产生基数缺口；无主键证据时 `unknown` + 缺口；
- 缺关联条件 / 缺字典表 / 缺桥接表 / 缺时间字段四类缺口同时命中，且每条都带理由、影响、备选方案与 `pending_review`；
- 技术溯源引用的字段未登记时产生 `source_field_not_in_catalog`；
- 路径缺口按 `source="lineage_path"` 汇聚，`affected_assets` 携带中文业务名而非节点 ID；
- 无 Join 方案时 `structured_join_ratio` 为 `null`；
- 路径预算截断时报告 `truncated`、告警和 `outside_path_budget`；
- 跨项目资产不进入当前快照。

## 5. 回滚边界

- 应用回滚：删除 `backend/app/services/lineage/join_plan.py`、删除 `backend/tests/test_requirement_field_plans.py`，并把 `backend/app/services/requirement_snapshot.py` 恢复到 Phase E 版本即可；已持久化的历史快照是不可变历史，不受影响。
- 数据回滚：无需数据库回滚（本阶段无迁移）。
- 契约回滚：新增键均为附加键，旧消费方按缺失键降级；`schema_version` 保持 `structured-requirement-v1`，方案代际由 `plan_version=requirement-field-plan-v1` 标识。

## 6. 已知边界与风险

1. 复杂 SQL（子查询、`OR`、函数包裹的多表条件）不会被结构化，只保留原文并标记未解析；这是刻意的保守行为。
2. `cardinality` 依赖主键/唯一键声明。当前只有 `CatalogTable.primary_key_columns_json` / `CatalogColumn.is_primary_key` 提供证据，集市、源、目标表尚无主键列，因此大量关联会停在 `N:1/1:N` + `missing_join_cardinality`，需要业务或元数据补齐。
3. `missing_dictionary_table` 依赖“项目内是否存在看起来像字典表”的启发式（表名/备注命中 `dict/dim/lookup/字典/码表`），命中的建议置信度为 `low`，必须人工评审。
4. `source_field_not_in_catalog` 只比对目录列与已登记源字段，未做模糊匹配；同名不同库的情况会保持未解析。
5. 路径解析按靶字段逐个执行，上限 20 个字段；超过上限时只报告截断，不静默丢弃。
6. 本次全量回归在沙箱内把 `STORAGE_DIR` 指向工作区隔离目录；生产默认路径下的 3 个 Excel 预览/导出用例未在本轮沙箱中复现（Phase E 已记录同一限制）。
7. 快照内容会先经过 `redact_summary`，键名命中 `token/secret/password/api_key/raw_sql` 等片段会被整体删除（ADR-015）。新增快照键必须避开这些片段。

## 7. 交付物

- 新增：`backend/app/services/lineage/join_plan.py`
- 修改：`backend/app/services/requirement_snapshot.py`
- 新增测试：`backend/tests/test_requirement_field_plans.py`
- 文档：`docs/upgrade/08-phase-f-plan.md`、`docs/upgrade/09-phase-f-report.md`、`docs/upgrade/02-adr-index.md`（ADR-014、ADR-015）
