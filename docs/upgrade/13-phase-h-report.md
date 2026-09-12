# Phase H 阶段报告：真实覆盖率与业务看板

状态：已完成
日期：2026-09-10
依赖阶段：Phase A、C、D、E
对应执行规格：第 9 节 Phase 13、第 11 节验收标准
计划：`docs/upgrade/12-phase-h-plan.md`

## 1. 本阶段解决的问题

升级前项目驾驶舱上有两套互相矛盾的覆盖率口径：治理分析服务用“记录数”当分子（AI 草稿也算覆盖），驾驶舱接口用 `confirmed` 当分子但把分母兜底成 `field_count * max(scenario_count, 1)` 并用 `min()` 夹住结果。业务方看到百分比时无法判断分子里是不是包含了 AI 建议，也无法判断分母为什么是这个数。

本阶段把两个接口统一到同一套可追溯口径：分子只含 `confirmed/approved`，分母是“目标字段 × 启用场景”，空分母返回 `null`，并新增血缘覆盖率、未解析血缘率、待确认问题率三项真实指标。

## 2. 实现内容

### 2.1 新增治理指标定义

`backend/app/services/analytics/metric_registry.py` 新增 `target_field_lineage_coverage`（目标字段血缘覆盖率）：分子“至少存在一个 `unresolved_flag=false` 的 `LineageNode` 的项目目标字段”，分母“项目内全部目标字段”，排除项显式写明“仅有未解析节点或完全没有血缘节点的字段；端到端完整性由 Phase D 路径接口按需计算”。登记表中此前只定义未计算的 `open_question_rate`、`lineage_unresolved_rate` 现在都有实现。

### 2.2 分析服务口径修正

`backend/app/services/analytics/metric_query_service.py`：

- 业务/技术覆盖率分子从 `business_count`/`technical_count` 改为 `business_confirmed`/`technical_confirmed`，AI 草稿与未确认记录不再计入；
- 新增 `open_question_rate`（有未闭环问题的映射对象 / 映射对象总数）、`target_field_lineage_coverage`、`lineage_unresolved_rate`（未解析 `LineageNode` / 全部 `LineageNode`）；
- 新增 `coverage_context`：同时给出“记录数”和“计入数”，以及 `numerator_statuses`、`excluded_numerator_statuses`，任何比例都能与原始记录对账；
- 把内部 `_metric_payload` 提升为公共 `build_metric_payload` 并保留私有别名，避免驾驶舱再写一套口径。

### 2.3 驾驶舱接口不再伪造分母

`backend/app/api/dashboard.py`：

- 删除 `max(counts["scenario_count"], 1)` 兜底，分母改为 `field_count × 启用场景数`；
- 删除 `min(numerator, denominator)` 夹取，分子改为“范围内且状态为 confirmed/approved 的业务映射/技术溯源”；
- 证据完备率的分子从“证据引用条数”改为“至少一条合格证据的去重映射对象数”（与登记表定义一致）；
- 三个指标统一通过 `build_metric_payload` 生成，返回 `metric_code`、`value`、`scope` 与完整定义（含排除项、负责人、版本）。

### 2.4 前端驾驶舱

`frontend/app/projects/[projectId]/dashboard/page.tsx`：

- 指标条从 6 项扩展到 9 项（新增“血缘覆盖”“未解析血缘”“待确认问题”），网格自适应；
- 覆盖率卡片改为读取服务端 `value` 字段，分母为 0 时显示“暂无可计算对象”，不再由前端自算百分比；
- 卡片增加 hover 说明（分子/分母/排除项）与“口径版本 + 负责人”，业务方可以直接追问口径来源。

## 3. 验证

| 检查项 | 命令 | 结果 |
| --- | --- | --- |
| Phase H 新增用例 | `cd backend; python -m pytest -q tests/test_coverage_metrics.py` | 5 passed |
| 指标与分析回归 | `tests/test_analytics_api.py`、`tests/test_metric_registry.py`、`tests/test_product_integrity.py`、`tests/test_governance.py` | 60 passed |
| 前端契约回归 | `cd frontend; node --test tests/project-dashboard-contract.test.mjs` | 2 passed |
| 前端全量（除浏览器 CDP 用例） | `cd frontend; node --test tests/*.test.mjs`（20 个文件，排除 `semantic-catalog-browser.test.mjs`） | 102 passed / 0 failed（浏览器用例与 Phase G 结论一致，需 GUI 权限） |
| TypeScript | `cd frontend; node_modules/.bin/tsc --noEmit` | 退出码 0 |
| ESLint | `cd frontend; next lint --file "app/projects/[projectId]/dashboard/page.tsx"` | No ESLint warnings or errors |
| 前端生产构建 | `cd frontend; NEXT_TELEMETRY_DISABLED=1 node_modules/.bin/next build` | 通过（全部既有静态页面 + `/lineage/nebula`） |
| 后端全量回归 | `cd backend; $env:STORAGE_DIR=<工作区隔离目录>; python -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp` | **541 passed, 0 failed**（16 分 40 秒；Phase F 为 536，新增 5 个覆盖率用例） |
| 迁移链 | `cd backend; python -m alembic heads` | `202609100025 (head)`，本阶段无新增迁移 |

新增用例覆盖的不可伪造点：

1. 空项目：`/analytics/overview` 与 `/dashboard` 的覆盖率 `value` 都是 `null`，`denominator` 为 0；
2. `draft` 状态业务映射不计入分子，改为 `confirmed` 后分子变为 1；
3. 停用场景不进分母，停用场景下的确认记录不膨胀分子；驾驶舱 `eligible_field_scenario_pairs` 等于“字段 × 启用场景”；
4. 血缘覆盖率与未解析血缘率来自 `LineageNode.unresolved_flag`；
5. 同一映射挂两条证据引用时证据完备率分子仍为 1（验证此前的“证据条数当分子”缺陷已修复）。

## 4. 未做的部分与理由

执行规格 Phase 13 还要求展示“冲突”。当前语义上下文冲突由 `backend/app/services/semantic/context_conflicts.py:25` 按目标字段**按需计算**，没有项目级持久化事实；为了不在看板上伪造一个 0，本阶段没有提交冲突指标，而是把它登记为已知限制（见下节）。这条选择与 Phase 13 的门禁一致：宁可显示“暂无可计算对象”，也不显示虚假的 0。

## 5. 已知边界与风险

1. 冲突数仍不可在驾驶舱按项目聚合，需要先在语义上下文层引入持久化的冲突事实（属于 Phase 15 语义影响分析的候选范围）。
2. `target_field_lineage_coverage` 只表示“目标字段存在已解析血缘节点”，不等同于“端到端路径完整”；端到端完整性必须通过 Phase D 的路径接口按目标字段查询。
3. 覆盖率分母仍是“字段 × 启用场景”的笛卡尔积口径，若业务希望改成“字段维度”或“场景维度”，需要新增指标定义而不是修改现有指标，以免历史报表口径漂移。
4. 本轮验证均在本机 SQLite 与夹具层面完成，未连接生产库；生产库上的数据分布可能让某些分母显著变大。

## 6. 回滚边界

- 后端：回滚 `backend/app/services/analytics/metric_registry.py`、`backend/app/services/analytics/metric_query_service.py`、`backend/app/api/dashboard.py`；
- 前端：回滚 `frontend/app/projects/[projectId]/dashboard/page.tsx`；
- 无迁移、无新表、无数据写入，回滚不影响已持久化事实。

## 7. 交付物

修改：

- `backend/app/services/analytics/metric_registry.py`（新增 `target_field_lineage_coverage`）
- `backend/app/services/analytics/metric_query_service.py`（确认态分子、新指标、`coverage_context`、`build_metric_payload`）
- `backend/app/api/dashboard.py`（真实分母、去重证据分子、统一治理口径）
- `frontend/app/projects/[projectId]/dashboard/page.tsx`（9 项指标条、口径可追溯卡片）

新增：

- `backend/tests/test_coverage_metrics.py`

以上改动均**未提交**。
