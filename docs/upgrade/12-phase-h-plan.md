# Phase H 计划：真实覆盖率与业务看板

状态：已完成（见 `13-phase-h-report.md`）
日期：2026-09-10
依赖阶段：Phase A（结构化需求快照）、Phase C（血缘版本）、Phase D（端到端路径）、Phase E（脚本监控与影响业务化）
对应执行规格：第 9 节 Phase 13、第 11 节验收标准

## 1. 目标

让项目驾驶舱显示的每一个比例都能回答三件事：分子是什么、分母是什么、谁被排除。具体要求：

- 只统计 `confirmed/approved` 的正式事实，AI 草稿与未确认记录一律不进分子；
- 分母只使用真实可计算对象（目标字段 × **启用**场景），不得用 `max(x, 1)` 之类的兜底伪造分母；
- 分母为 0 时返回 `null` / “暂无可计算对象”，不得显示 0%；
- 每个指标必须挂在治理登记表（`METRIC_REGISTRY`）的定义上，包含分子/分母/排除项/维度/负责人/版本。

## 2. 现状（Phase H 之前）

仓库已经有两套并行的覆盖率口径，互相矛盾：

| 位置 | 现状 | 问题 |
| --- | --- | --- |
| `backend/app/services/analytics/metric_query_service.py` | 有治理指标登记表、空分母返回 `null` | 业务/技术覆盖率用**记录数**做分子，AI 草稿也算覆盖；`open_question_rate`、`lineage_unresolved_rate` 只在登记表里定义、从未计算 |
| `backend/app/api/dashboard.py` | 分子用 `confirmed` 计数 | 分母是 `field_count * max(scenario_count, 1)`（场景数含停用场景、且空分母被兜底成 1），分子被 `min()` 夹住，证据分子用“证据引用条数”而不是“有证据的映射对象数” |

前端 `projects/[projectId]/dashboard` 已经在为空分母显示“暂无可计算对象”，因此本阶段的改动集中在服务端口径与定义对齐。

## 3. 做

1. 在 `metric_registry.py` 新增 `target_field_lineage_coverage`（目标字段血缘覆盖率）定义。
2. 在 `metric_query_service.build_project_overview` 中：
   - 业务/技术覆盖率分子改为 `business_confirmed`/`technical_confirmed`；
   - 新增 `open_question_rate`、`target_field_lineage_coverage`、`lineage_unresolved_rate` 的计算；
   - 新增 `coverage_context`，显式暴露“记录数 vs 计入数”和排除状态，便于审计对账；
   - 把内部 `_metric_payload` 提升为公共 `build_metric_payload`（保留私有别名，兼容既有测试）。
3. 在 `api/dashboard.py` 中改用同一套治理口径：分母用启用场景数、去掉 `min()` 夹取、证据分子改为去重映射对象数，并复用 `build_metric_payload`。
4. 前端驾驶舱把新指标渲染成卡片，并在卡片上显示治理口径版本与负责人，便于业务追问“这个比例怎么算的”。
5. 新增 `backend/tests/test_coverage_metrics.py`：用真实 API + ORM 夹具覆盖草稿不计入、停用场景不进入分母、空分母不可用、血缘覆盖率与未解析率、证据去重、待确认问题率。

## 4. 不做

- 不新增数据库迁移、不新增事实表；
- 不做“冲突”指标：语义上下文冲突目前是按目标字段按需计算的上下文事实，没有项目级持久化事实，伪造一个 0 会直接违反本阶段门禁；改为在报告里登记为已知限制；
- 不改动准备度评分 (`build_project_readiness`) 的口径；
- 不引入前端图表库，沿用既有 `stat-card` 样式。

## 5. 门禁

- 任意比例指标都带 `metric_code`、`numerator`、`denominator`、`value`、`scope`、`definition`；
- `denominator == 0` 时 `value is None`，前端显示“暂无可计算对象”；
- 分子只来自 `confirmed/approved`（血缘类指标来自 `LineageNode` 的解析状态）；
- 同一指标在两个接口（`/analytics/overview`、`/projects/{id}/dashboard`）上定义一致。

## 6. 回滚边界

- 后端可回滚 `metric_registry.py`、`metric_query_service.py`、`api/dashboard.py` 三个文件；
- 前端可回滚驾驶舱页面的指标卡片；
- 无迁移、无数据写入，回滚不影响已持久化事实。
