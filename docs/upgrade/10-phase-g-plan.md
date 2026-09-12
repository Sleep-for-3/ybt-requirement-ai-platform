# Phase G 计划：数据星云与业务化展示

状态：已完成（见 `11-phase-g-report.md`）
日期：2026-09-10
依赖阶段：Phase B（业务名称契约）、Phase D（端到端路径）、Phase E（脚本监控与影响业务化）、Phase F（结构化字段方案）
对应执行规格：第 7 节（前端终版设计）、第 9 节 Phase 18 门禁、第 11 节功能与回归验收

## 1. 目标

把 `/lineage` 从“脚本 + 边表格”升级为可按层级浏览的血缘探索器：

- 数据星云总览：源系统 → ODS/DWD/DWS → 监管集市 → 一表通/EAST/1104 的分层布局，节点发光、连线带流动效果；
- 分层 DAG：同一份 `LineagePathResponse` 同时驱动图形与表格，二者必须显示同一事实；
- 版本与影响聚焦：可选择血缘版本、按节点聚焦上下游高亮；
- 业务名称优先：节点主标题用中文业务名，技术名降级为次要信息，缺失时显式提示；
- 可访问性：键盘可达、`prefers-reduced-motion` 降动画、空态/错误态/截断态齐全；
- 诚实性：动画只表示结构连接关系，不表示脚本正在运行或数据实时流动。

## 2. 范围

### 2.1 做

1. 新增纯函数模型 `frontend/lib/lineage-nebula.mjs`：分层、排序、聚焦、截断、缺口摘要、布局坐标、表格行投影。所有逻辑可在 Node 中直接测试（与仓库既有 `lib/*.mjs` + `tests/*.test.mjs` 约定一致）。
2. 新增 `frontend/components/LineageNebula.tsx`：深色星云画布 + 分层列 + 贝塞尔连线 + 图例 + 节点详情 + 缺口列表 + 同事实表格。
3. 新增 `frontend/app/lineage/nebula/page.tsx`：读取项目上下文，按 `rootType/rootId/revisionId/depth/view/focus` 查询 `GET /api/projects/{id}/lineage/path`，渲染星云与表格。
4. 在 `/lineage` 首页与技术血缘详情页加入口；在导航契约中登记 `/lineage/nebula` 的上级路由。
5. 新增 `frontend/tests/lineage-nebula.test.mjs` 覆盖分层顺序、未知层级兜底、确定性、聚焦高亮、逐层截断、缺口摘要、图与表同源。

### 2.2 不做

- 不新增后端接口：只消费 Phase D 的 `LineagePathResponse` 与 Phase C 的版本列表。
- 不引入图形库或 WebGL；用确定性坐标 + SVG 连线，避免用图形库内存状态代替数据库版本事实。
- 不改动既有 `LineageGraph` 表格组件与其测试。
- 不展示实时运行状态；动画与节点光效只表达“存在已登记的关联”。

## 3. 门禁（对应 Phase 18）

- 图形与表格由同一个 model 生成，表格行数必须等于 `model.edges.length`，且只引用 `model` 中存在的节点。
- 业务名、技术名、证据、版本在同一节点详情内互相可达。
- 大图有限层、有限节点（逐层上限 + 逐层截断标记）、渐进加载（按需查询单个根节点）。
- 键盘可聚焦每个节点按钮，`Escape` 取消聚焦；`prefers-reduced-motion: reduce` 时关闭流动动画。
- 空态、错误态、无权限（由 API 层统一处理）、截断态均有明确文案。
- 页面上必须出现“动画只表示结构关系，不表示实时运行”的说明。

## 4. 回滚边界

- 新增页面与组件可整体删除；`/lineage` 首页与导航契约的入口为附加链接，删除后回到 Phase F 行为。
- 无数据库、无迁移、无后端契约变化。
