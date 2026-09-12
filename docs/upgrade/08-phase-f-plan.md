# Phase F 计划：结构化字段方案与缺口建议增强

状态：已完成（实现与验证见 `09-phase-f-report.md`）
日期：2026-09-10
依赖阶段：Phase A（结构化需求快照）、Phase B（业务名称契约）、Phase C（血缘版本）、Phase D（端到端路径）、Phase E（脚本监控与影响业务化）
对应执行规格：第 6.2、6.3、6.4 节，第 9 节 Phase 15/16 门禁，第 10.3 节缺口夹具

## 1. 本阶段要解决的问题

Phase A 已经能冻结结构化快照，但快照里的字段方案仍停留在“把映射字段原样搬运”：

- `join_plans` 只知道 `raw_condition` 文本，`structured` 恒为 `false`，无法回答“哪张表和哪张表、按哪个键、什么基数关联”；
- `gap_recommendations` 只有 6 条固定规则，没有证据、没有替代方案、没有审批状态语义，也没有覆盖“缺字段 / 缺表 / 缺桥接表 / 缺字典表 / 缺时间字段”；
- 快照没有把 Phase D 的端到端路径与路径级缺口收进字段方案，需求文档因此无法做到“精确到表、字段、关联条件和取数规则”；
- 缺少可被前端和导出器共同消费的方案摘要，无法判断一份需求是否真的可交付。

本阶段把上述内容补齐，且不新增数据库表、不新增迁移、不新增平行模型。

## 2. 范围

### 2.1 做

1. 新增确定性的关联条件结构化器：把 `SourceToMartMapping.join_condition` 与 `MartToYbtMapping.join_condition` 解析为键对、关联类型、基数、时间条件和未解析标记。
2. 扩展字段方案：每个 `field_plan` 增加 `plan_version`、`source_paths`（有界的端到端路径摘要）、结构化 `join_plans`、增强版 `gap_recommendations`。
3. 扩展缺口建议契约：`gap_type / problem_statement / recommended_change / alternative_options / rationale / evidence_refs / affected_assets / estimated_impact / confidence_level / approval_status`，并额外标注 `source`（`requirement_snapshot` 或 `lineage_path`）与稳定去重键。
4. 把 Phase D `LineagePathResolver` 的路径缺口汇聚进字段方案，并把节点 ID 转成中文业务名，避免前端再拼标签。
5. 快照内容增加 `plan_summary`：字段数、结构化 Join 比例、缺口分布、缺业务备注数量、路径解析预算与截断标记。

### 2.2 不做

- 不新增 Alembic 迁移，不改动任何已有表结构（仍为 `202609100025`）。
- 不新增 JoinPlan / GapRecommendation 数据表；结构化结果只存在于不可变快照 JSON 中。
- 不自动推断关联键、基数或时间口径；无法证明的一律标为未解析并要求人工确认。
- 不修改 `SourceToMartMapping` / `MartToYbtMapping` 的既有字段语义。
- 不做 Phase G 的星云看板与前端改造（本阶段只提供契约）。

## 3. 契约变更

### 3.1 JoinPlan（`field_plan.join_plans[]`）

保留 Phase A 的兼容键 `mapping_type`、`mapping_id`、`raw_condition`、`status`、`structured`、`review_required`、`note`，新增：

```text
parse_status        structured / partial / unresolved / missing
fully_resolved      布尔，是否所有键对都落到项目内资产
left_entity         左表资产（业务名优先）
right_entity        右表资产（业务名优先）
left_keys           解析出的左键列表
right_keys          解析出的右键列表
key_pairs           每对关联键：左右 token、解析结果、操作符、是否时间键
join_type           inner / left / right / full / unknown
cardinality         1:1 / 1:N / N:1 / unknown（仅在有主键证据时给出）
time_conditions     时间对齐键对
range_conditions    非等值条件（保留原文，不推断）
unresolved_references  未能解析的关联写法（刻意不叫 token：快照内容会先经过平台的敏感键脱敏策略，键名包含 token 会被整体丢弃）
confidence_level    high / medium / low
```

`structured` 只在 `parse_status == "structured"` 时为 `true`，即“所有键对都解析到项目内资产”，可直接当作事实使用。

### 3.2 RequirementFieldPlan（`field_plan`）

```text
plan_version        requirement-field-plan-v1
target              目标字段资产（业务名优先，Phase B 契约）
source_paths        有界端到端路径摘要：hops（各层中文名）、转换、证据、完整性与置信度
join_plans          结构化关联方案
transformation_rules / quality_rules   保持 Phase A 契约
gap_recommendations 增强版缺口建议
gap_summary         按来源和类型的计数
readiness_status / requires_review
```

### 3.3 GapRecommendation

```text
gap_type            缺口类型（见 4）
problem_statement   问题陈述
recommended_change  建议动作（新增字段 / 表 / 桥接表 / 字典表 / 统一业务主键 / 时间字段 / 粒度 / 同步任务）
alternative_options 备选方案
rationale           理由
evidence_refs       证据
affected_assets     受影响资产（业务名优先）
estimated_impact    影响范围
confidence_level    置信度
approval_status     pending_review（建议不得直接改生产模型）
source              requirement_snapshot / lineage_path
dedupe_key          稳定去重键
```

### 3.4 缺口类型

项目内事实缺口：`business_mapping_missing`、`source_field_missing`、`source_field_incomplete`、`source_field_not_in_catalog`、`source_table_missing`、`mart_mapping_missing`、`source_to_mart_mapping_missing`、`join_condition_missing`、`unresolved_join_key`、`missing_join_cardinality`、`missing_time_field`、`missing_dictionary_table`、`missing_bridge_table`。

路径级缺口（来自 `LineagePathResolver`，`source = "lineage_path"`）：`no_lineage_path`、`missing_technical_evidence`、`missing_lineage_revision`、`incomplete_terminal_path`、`missing_business_comment`、`missing_asset_binding`。

### 3.5 快照级 `plan_summary`

```text
field_plan_count / field_plan_truncated
fields_with_complete_path / fields_with_gaps
join_plan_count / structured_join_count / structured_join_ratio（分母为空时为 null）
gap_counts_by_type / gap_counts_by_source
fields_missing_business_comment
path_resolution: { resolved_fields, truncated, max_fields, warnings }
```

沿用 Phase 13 门禁：分母为空时返回 `null`，不显示为 0%。

## 4. 复用关系（不重复建模）

| 需求 | 复用的既有对象 |
| --- | --- |
| 关联条件结构化 | `SourceToMartMapping.join_condition`、`MartToYbtMapping.join_condition`、`CatalogTable.primary_key_columns_json`、`CatalogColumn.is_primary_key` |
| 键解析证据 | `CatalogColumn`、`MartField`、`SourceField`、`TargetField` 及其表实体 |
| 路径与路径缺口 | `LineagePathResolver`（Phase D）、`LineageRevision`（Phase C） |
| 业务名称 | `AssetDisplayResolver`（Phase B） |
| 缺口契约 | `LineageGapRecommendation`（`backend/app/schemas/lineage.py`）字段名保持一致，仅补充 `source` / `dedupe_key` |
| 快照存储 | `StructuredRequirementSnapshot.content_snapshot_json`（Phase A，不改表结构） |

## 5. 验收门禁

- 结构化 Join 只在键对全部解析成功时标记 `structured = true`；未解析 token 必须出现在 `unresolved_tokens` 且产生 `unresolved_join_key` 缺口。
- 缺少主键证据时 `cardinality = "unknown"`，并产生 `missing_join_cardinality` 缺口，不得猜测。
- 每条缺口都有 `rationale`、`evidence_refs`、`affected_assets`、`confidence_level`、`approval_status`。
- 路径解析有界（字段数上限 20，深度 10），超限以 `truncated` 和告警显式标记，不静默丢失。
- 快照跨项目隔离：其他项目的表、字段、映射、路径缺口不得进入当前快照。
- 幂等：相同事实连续冻结两次返回同一快照与同一 `content_hash`；事实变化必须产生新版本且旧版本不被覆盖。
- 现有 Phase A–E 测试与 `tests/test_requirement_snapshots.py` 保持通过；新增定向测试覆盖 10.3 缺口夹具。

## 6. 回滚边界

- 应用回滚：恢复 `backend/app/services/requirement_snapshot.py` 并删除新增的 `backend/app/services/lineage/join_plan.py`；已持久化快照是不可变历史，不受回滚影响。
- 数据回滚：本阶段无迁移，`alembic head` 保持 `202609100025`。
- 新键均为附加键，旧消费方按缺失键降级即可；`schema_version` 保持 `structured-requirement-v1` 以兼容既有行，内部以 `plan_version` 区分方案代际。

## 7. 风险

1. 解析器面对复杂 SQL（子查询、函数、`OR`、多层括号）时只能保留原文并标记未解析，不能声称结构化。
2. 路径解析按字段逐个执行，字段数上限 20；超大项目仍可能触发截断，需要在报告和 UI 中显式提示。
3. 字典表、桥接表、时间字段建议来自项目级事实（是否存在字典表、映射是否含时间条件），属于“建议”，必须人工评审后才能改动生产模型。

## 下一步

按本文实现并在完成后补充 `docs/upgrade/09-phase-f-report.md`，同时更新 `02-adr-index.md` 与 `00-baseline.md`。
