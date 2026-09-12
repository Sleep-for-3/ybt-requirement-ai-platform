# Phase G 阶段报告：数据星云与业务化展示

状态：已完成
日期：2026-09-10
依赖阶段：Phase B（业务名称契约）、Phase C（血缘版本）、Phase D（端到端路径）、Phase E（脚本监控与影响业务化）、Phase F（结构化字段方案）
对应执行规格：第 7 节（前端终版设计）、第 9 节 Phase 18 门禁、第 11 节功能与回归验收
计划：`docs/upgrade/10-phase-g-plan.md`

## 1. 本阶段解决的问题

Phase A-F 已经产出契约（`StructuredRequirementSnapshot`、`AssetDisplayResolver`、`LineageRevision`、`LineagePathResponse`、影响详情、字段方案），但前端只有一个边表格：`frontend/components/LineageGraph.tsx` 第 19-68 行按行渲染边，没有层级概念，也没有把“源系统 -> 数仓 -> 监管集市 -> 一表通/EAST/1104”这条链路可视化。业务方看不到数据在哪个层级断掉，技术方也看不到某个字段到底经哪几个 Join 汇到监管指标。

本阶段新增数据星云页面，把 Phase D 的同一份 `LineagePathResponse` 同时渲染成分层图形和审计表格，并在每个节点上以中文业务名为主标题、技术名降为次要信息、缺失备注显式标记。

## 2. 实现内容

### 2.1 纯函数星云模型（新增）

`frontend/lib/lineage-nebula.mjs` + `frontend/lib/lineage-nebula.d.mts`，延续仓库既有 `lib/*.mjs` + `tests/*.test.mjs` 约定，所有逻辑可在 Node 中直接测试，不依赖 React 或图形库：

- `LAYER_ORDER`（第 15 行）：`SOURCE -> ODS -> DWD -> DWS -> MART -> TARGET -> CATALOG -> SCRIPT -> UNKNOWN`；`normalizeLayerCode`/`layerRank`/`layerLabel` 负责未知层级兜底；
- `resolveNebulaLabel`（第 105 行）：中文业务名/备注优先，技术名保留为次要信息，缺失时返回 `MISSING_BUSINESS_REMARK`（“缺少业务备注”，第 9 行）；
- `buildNebulaModel`（第 235 行）：分层、排序、聚焦高亮与弱化、逐层截断（默认每层 24 个节点）、缺口按类型与来源归并、统计与告警；
- `layoutNebula`/`edgeAnchors`/`curvePath`/`edgeGeometry`（第 420-478 行）：确定性坐标与贝塞尔连线，无随机数、无时间函数；
- `nebulaTableRows`/`nebulaFactSignature`（第 480-524 行）：图与表由同一模型投影，行数恒等于边数；
- `NEBULA_MOTION_NOTE`（第 11 行）：动效只表示已登记的结构关联，不表示脚本正在运行。

### 2.2 组件（新增）

`frontend/components/LineageNebula.tsx`：深色星云画布（SVG 贝塞尔连线，仅技术证据边启用流动虚线）、节点按钮（`aria-pressed` 表达聚焦）、节点详情、缺口列表、与图形同源的审计表格，以及 loading/error/empty/截断四态；第 44 行 `Escape` 取消聚焦，第 120 行渲染动效说明，第 31 行 `maxNodesPerLayer` 控制节点预算。

### 2.3 页面（新增）

`frontend/app/lineage/nebula/page.tsx`：读取项目上下文，支持 `rootType/rootId/direction/depth/view/revisionId` URL 参数；只调用 `GET /api/projects/{id}/lineage/path`（`include_unresolved=true`、`max_paths=60`）与 `GET /api/projects/{id}/lineage/revisions?status=published`，不新增后端接口。

### 2.4 样式与入口

- `frontend/app/globals.css`：新增星云样式（`.nebula-canvas`/`.nebula-node`/`.nebula-edge-flow` 等），第 201-205 行 `@media (prefers-reduced-motion: reduce)` 关闭流动动画；
- `frontend/app/lineage/page.tsx`：首页新增“数据星云”卡片（网格改 4 列）；
- `frontend/app/lineage/fields/[fieldId]/page.tsx`：字段血缘页新增“打开数据星云”入口；
- `frontend/lib/navigation-contract.mjs`：登记 `/lineage/nebula` 的父路由为 `/lineage`。

### 2.5 测试（新增）

`frontend/tests/lineage-nebula.test.mjs`：10 个用例——分层顺序与未知层级兜底、同输入同输出（含输入顺序变化）、业务名优先/技术名次要、聚焦高亮、聚焦时隐藏无关边、逐层截断同时丢弃悬挂边、图与表同源、布局与连线几何确定且有界、缺口建议保留评审字段并按类型与来源归并、动效文案与层级配色稳定。

## 3. 本阶段刻意不做的事

1. 不新增后端接口、模型或迁移（只用 Phase C/D 已发布的契约）。
2. 不引入图形库或 WebGL：用确定性坐标 + SVG，避免图形库内存状态成为唯一事实源。
3. 不做自由拖拽画布，避免图形替代审计列表。
4. 不改 `LineageGraph` 表格组件与其既有测试。
5. 不展示脚本实时运行状态，动效不承诺“数据正在流动”。

## 4. 验证

| 检查项 | 命令 | 结果 |
| --- | --- | --- |
| Phase G 定向用例 | `cd frontend; node --test tests/lineage-nebula.test.mjs` | 10 passed / 0 failed |
| 前端全量（除浏览器 CDP 用例） | `cd frontend; node --test tests/*.test.mjs`（排除 `semantic-catalog-browser.test.mjs`，共 19 个文件） | 102 passed / 0 failed |
| 前端浏览器用例 | 单跑 `tests/semantic-catalog-browser.test.mjs` | 沙箱内 12 failed（`CDP websocket closed`）；在沙箱外（用户已批准）**12 passed**；合计 **114 passed / 0 failed** |
| TypeScript | `cd frontend; node_modules/.bin/tsc --noEmit` | 退出码 0，无输出 |
| ESLint（改动文件） | `cd frontend; next lint --file components/LineageNebula.tsx --file app/lineage/nebula/page.tsx --file lib/lineage-nebula.mjs --file app/lineage/page.tsx --file "app/lineage/fields/[fieldId]/page.tsx" --file components/LineageGraph.tsx` | `No ESLint warnings or errors` |
| 生产构建 | `cd frontend; NEXT_TELEMETRY_DISABLED=1 node_modules/.bin/next build` | 通过，产物含 `/lineage/nebula 14.7 kB / 120 kB` |
| 后端回归 | 本阶段未修改后端文件 | 沿用 Phase F 的 536 passed；本轮未重跑后端全量 |

关于浏览器用例：`tests/semantic-catalog-browser-harness.mjs` 会启动本机 Edge/Chrome 并连接 CDP（第 460、630-639 行），在当前沙箱内于建立连接阶段被中断，报错不是断言失败；该测试文件与 harness 在本轮均未被修改（`git status` 无记录）。因此这 12 个失败是环境限制，不是 Phase G 引入的回归；在沙箱外运行时 12/12 全部通过。

## 5. 门禁对照（执行规格 Phase 18）

| 门禁 | 实现/证据 |
| --- | --- |
| 图和表格显示相同事实 | `nebulaTableRows` 只从模型投影（`lineage-nebula.mjs:480`）；用例 `the graph and the table are driven by exactly the same facts` 断言行数等于边数 |
| 业务名、技术名、证据和版本可相互跳转 | 节点详情渲染 `resolveNebulaLabel` 结果与技术名；页面提供 `revisionId` 选择；字段血缘页与星云互链 |
| 大图有限深、有限节点、渐进加载 | 查询 `depth`（1-10）与 `max_paths=60`；`buildNebulaModel` 逐层截断并标记 `hiddenCount`；`maxNodesPerLayer` 默认 24 |
| 键盘访问、降动画、空态/错误态 | `LineageNebula.tsx:44`（Escape）、`:167`（onKeyDown）、`:217`（aria-pressed）、`globals.css:201`（reduced-motion）、`:49/:61/:81`（loading/error/empty） |
| 不把动画当成运行事实 | `lineage-nebula.mjs:11` 文案常量 + `LineageNebula.tsx:120` 渲染 + 用例 `motion copy is explicit and every layer has a stable accent` |

## 6. 回滚边界

- 应用回滚：删除 `frontend/lib/lineage-nebula.mjs`、`frontend/lib/lineage-nebula.d.mts`、`frontend/components/LineageNebula.tsx`、`frontend/app/lineage/nebula/`、`frontend/tests/lineage-nebula.test.mjs`，并撤回 `globals.css`、`navigation-contract.mjs`、`app/lineage/page.tsx`、`app/lineage/fields/[fieldId]/page.tsx` 的附加改动即可；
- 无数据库迁移、无后端契约变化，回滚后系统等于 Phase F 行为；
- 入口都是附加链接（不替换既有卡片），星云不可用时其余血缘页面不受影响。

## 7. 已知边界与风险

1. `rootId` 目前需要手工输入数字 ID，页面没有对象选择器；后端也还没有“按名称搜索再取路径”的入口。
2. 星云布局是确定性的分层列布局，不是力导向图；它优先保证可复现与可审计，节点很多时靠逐层截断而不是缩放。
3. 本轮未对生产数据做端到端验证：所有验证都在本地 SQLite/夹具与静态构建层面完成。
4. 浏览器类前端用例必须在具备 GUI/CDP 权限的环境运行，沙箱内必然失败。
5. “动效只表达结构关系”由页面文案与用例保证；若将来有人把运行状态塞进同一条边，需要重新评审。

## 8. 交付物

新增：

- `frontend/lib/lineage-nebula.mjs`
- `frontend/lib/lineage-nebula.d.mts`
- `frontend/components/LineageNebula.tsx`
- `frontend/app/lineage/nebula/page.tsx`
- `frontend/tests/lineage-nebula.test.mjs`

修改：

- `frontend/app/globals.css`（星云样式与降动画）
- `frontend/lib/navigation-contract.mjs`（父路由 +1 行）
- `frontend/app/lineage/page.tsx`（入口卡片 +7 行）
- `frontend/app/lineage/fields/[fieldId]/page.tsx`（星云入口 +12 行）

以上改动均**未提交**。
