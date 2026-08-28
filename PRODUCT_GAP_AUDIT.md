# Product Gap Audit

审计日期：2026-08-28  
基线：`origin/main = f5262099bf71852773941a5911d237e68374acbe`  
项目：Sleep-for-3/ybt-requirement-ai-platform

## 审计范围与方法

本审计基于当前 `main` 代码、前端路由/组件、后端 API/模型/服务、已有测试和运行时配置完成。未使用旧规划文档替代代码事实；未回滚或覆盖工作区已有未提交内容。

分类含义：

- `IMPLEMENTED`：已有真实代码与调用链，当前无需重做。
- `PARTIAL`：已有基础能力，但仍有产品体验、统一性或治理闭环缺口。
- `MISSING`：当前没有可复用的正式实现。
- `REFACTOR`：已有实现可用，但结构或入口需要收敛。

## 总览

| Area | Status | Evidence | Product gap / decision |
|---|---|---|---|
| AppShell | PARTIAL | `frontend/components/AppShell.tsx` 有分组导航、响应式抽屉、项目选择、后台任务提示 | Sidebar 桌面宽度固定 248px；品牌仍是旧“一表通口径平台”；导航仍按模块分组，缺少角色首页和“我的工作”统一入口 |
| WorkspaceHeader | IMPLEMENTED | `frontend/components/WorkspaceHeader.tsx` 提供 breadcrumb、确定性 parent return、URL query 恢复 | 保留；只补统一语言和窄屏验证 |
| navigation-contract | IMPLEMENTED | `frontend/lib/navigation-contract.mjs`、`StatefulLink`、相关测试 | 保留；不重复实现返回/returnTo |
| ProjectContext | PARTIAL | `frontend/components/ProjectContext.tsx` 支持 projectId URL、localStorage、项目切换 | 项目切换缺少统一 query-cache 清理协议；仍有旧页面自行请求，易产生请求竞态和旧数据短暂展示 |
| RequirementWorkspace | PARTIAL | `RequirementWorkspace.tsx` 使用 projection、field detail、evidence lazy query | 主容器仍有 `min-w-[1180px]`，布局 `390px + 720px` 固定下限；1366px 在 AppShell 后可用空间不足；Inspector 不是独立可折叠层 |
| Semantic Catalog | IMPLEMENTED | `semantic-catalog/*`、controller/view-model、浏览器 harness 和 contract tests | 保留；后续只接入统一产品语言和真实入口 |
| Datasources | IMPLEMENTED | `DatasourceWizard.tsx` 有 connector registry、driver 检测、连接诊断、schema 选择和首次 sync | 保留；页面仍需统一 DataGrid 和真实 driver 状态解释 |
| Catalog | PARTIAL | `frontend/app/catalog/page.tsx` 有筛选、分页、审计状态和局部横向滚动 | 使用手写 grid；未抽象为统一 EnterpriseDataGrid；需保留 URL 状态/返回恢复 |
| Fields | PARTIAL | `frontend/app/fields/page.tsx` 与 field detail/scenarios 已存在 | 手写列表、业务枚举/step 文案分散；质量规则/场景页仍暴露内部 ID/枚举 |
| Review tasks | PARTIAL | `/review-tasks` 和 `/tasks/[taskId]` 存在，后端复用 ReviewTask/Workflow | 与 `/tasks` 信息架构重叠；列表显示 `step_key`、status 等内部语言；缺少 Review Workspace |
| Tasks | REFACTOR | `/tasks` 同时承载审核任务和 Safe Query；后端有 review task 与 natural language task 两类服务 | 重构为 `/work` 我的工作；Safe Query 迁移到 `/tools/safe-query`，保留兼容入口 |
| Notifications | PARTIAL | 后端 Notification 有 project/resource/read_at；前端有未读列表和 mark-read | 缺少 severity/category/action_href/actor 的完整产品表达；点击不能稳定进入业务对象；无全部/未读/审核/风险/系统筛选 |
| Quality | PARTIAL | 后端 `DataQualityExpectation` 与前端 `/quality` 已存在，React Query 已使用 | 创建表单仍要求 `entity_type`、`entity_id`、JSON 参数；需要 asset picker 和按 rule type 的业务表单 |
| Dashboard | PARTIAL | `/projects/{projectId}/dashboard` 与后端 dashboard API 已有角色视图和 readiness/risk 卡片 | 无正式 ReportingCycle、Metric Definition/Metric Snapshot；机构级 cockpit、趋势快照、热力矩阵和真实下钻未形成 |
| Projects | IMPLEMENTED | `/projects`、项目成员、权限服务、项目切换已存在 | 保留；首页角色化和业务名称统一待补 |
| Onboarding | IMPLEMENTED | `/projects/{id}/onboarding`、readiness 服务和页面存在 | 保留；需与 ReportingCycle/交付 preflight 对齐 |
| Readiness | IMPLEMENTED | 后端 readiness projection、前端 readiness 页面、阻断项展示存在 | 保留；当前指标仍以项目当前状态为主，缺少按报送期快照 |
| Lineage | IMPLEMENTED | 脚本、SQL、解析、节点、变更、影响链和图组件已存在 | 保留；Impact 页面需要业务故事化 UI，隐藏原始 JSON/内部 step |
| Impact | PARTIAL | `lineage/impacts` 与 semantic impact service 已形成 SQL→Lineage→Semantic→Requirement→ReviewTask 链 | UI 仍混合技术字段/JSON；缺少“发生了什么/风险/谁处理/截止时间”的统一故事视图 |
| Deliverables | PARTIAL | deliverable engine、模板、版本、校验、渲染、审批和下载已存在 | 创建路径还不是 ReportingCycle-aware 的五步 preflight wizard；阻断/警告需产品化呈现 |
| Jobs | PARTIAL | 后端 BackgroundJob、前端 JobProgressPanel、轮询 hook 已存在 | `/jobs` 仍是技术任务页；缺少与“我的工作”分层，后台任务和审核任务语义未统一 |
| UAT | IMPLEMENTED | UAT suites/runs/findings/signoffs、自动/手工流程和报告已存在 | 保留；前端仍需统一表格、状态语言和业务入口 |
| Knowledge | IMPLEMENTED | Knowledge documents/items/RAG/evaluation/indexing 已存在 | 保留；部分页面仍直接展示 JSON，不符合业务 UI 原则 |
| Admin | PARTIAL | institutions/users/permissions/system-health/model profiles/audit 已存在 | 管理边界存在；角色 landing、健康指标业务语言和桌面宽度需统一 |
| frontend lib/api | PARTIAL | `api.ts`、错误契约、query client、navigation contract、job polling 等存在 | React Query 只在 AppShell、Workspace、Quality 使用；大量页面仍 useEffect + 手写请求，cache/cancellation 不统一 |
| React Query | PARTIAL | `@tanstack/react-query` 已安装并有 QueryProvider、workspace/query-client | 迁移范围不足；不应重写已有 query contract，优先迁移高价值列表和项目切换缓存协议 |
| Loading/error/empty | PARTIAL | `PageState`、feedback components、error contract 已存在，许多页面有独立状态 | 使用不一致；仍有 raw JSON、技术错误、内部枚举和局部 silent failure |
| 1280/1366/1440/1920 desktop | PARTIAL | 多数页面使用 Tailwind responsive；已有 semantic/catalog browser tests | RequirementWorkspace 的 1180px 硬下限是明确 1366 风险；没有统一四视口真实浏览器验收记录 |
| Backend dashboard metrics | PARTIAL | readiness、coverage、risk、question、deliverable 等聚合存在 | 缺少 numerator/denominator/eligible/scope/as_of/cycle 的统一 Metric Definition；历史趋势没有 snapshot |
| Permission model | IMPLEMENTED | `CurrentPrincipal`/`RealPrincipal`、PermissionService、resource guard、机构/项目隔离测试存在 | 保留；新入口必须复用现有权限，不建第二套治理体系 |

## Wave H — Product UX Consolidation

| Item | Classification | Finding | First implementation target |
|---|---|---|---|
| H1 Desktop Workspace | REFACTOR | 固定 `min-w-[1180px]` 和 `390px + 720px` 在 1366px 下挤压主区；Inspector 永久占位 | 先改 Workspace 为 `min-w-0`、可折叠左导航/右 Inspector、局部表格滚动，并补四视口浏览器证据 |
| H2 EnterpriseDataGrid | MISSING | 没有共享 DataGrid contract；catalog/fields/review/jobs/UAT/deliverables 各自手写 | 建立轻量共享 contract，先迁移 fields、review/work、catalog |
| H3 我的工作 | REFACTOR | `/review-tasks` 与 `/tasks` 并存，Safe Query 混入任务中心 | 建立 `/work` 统一业务入口，保留旧路径兼容，Safe Query 独立到 `/tools/safe-query` |
| H4 通知中心 | PARTIAL | 数据模型有 resource/project/read_at，但 UI 只读/已读 | 先补产品分类、严重级别映射、action href 和筛选；复用 Notification 模型 |
| H5 反馈体验 | PARTIAL | feedback primitives 已有，但页面采用不一致 | 建立核心列表/详情 interaction contract，禁止 alert 和无状态提交 |
| H6 产品语言 | REFACTOR | `step_key`、`entity_type`、状态映射散落各页 | 建立 `frontend/lib/product-language.ts`，逐步替换核心页面 |

## Wave I — Reporting Cycle & Trusted Metrics

| Item | Classification | Finding | Decision |
|---|---|---|---|
| I1 ReportingCycle | MISSING | 未发现 ReportingCycle 模型、migration、API 或正式页面 | 需要新增正式业务对象；必须设计 legacy compatibility，不强行改写历史数据 |
| I2 Metric Definition Registry | MISSING | Dashboard 聚合无统一 definition registry | 先代码级 registry 与类型 contract，必要时再持久化 |
| I3 Coverage correctness | PARTIAL | 当前 readiness/dashboard 有覆盖类聚合，但不是统一 eligible mapping 分子/分母 contract | 统一核心 coverage 计算，0 denominator 返回 N/A；补 deterministic tests |
| I4 Metric Snapshot | MISSING | 无按报送期保存的 numerator/denominator/value snapshot | 依赖 ReportingCycle；新增 migration/API/后台计算入口 |

## Wave J — Executive Cockpit 2.0

| Item | Classification | Finding | Decision |
|---|---|---|---|
| J1 Institution Cockpit | MISSING | 未发现 `/cockpit` 页面或机构级聚合 API | 新增机构入口，复用 PermissionService 和现有项目 dashboard 聚合 |
| J2 Project Dashboard 2.0 | PARTIAL | 现有 dashboard 是角色卡片/readiness 风险摘要 | 逐步补报送期、准备度矩阵、真实趋势和 Top Risk 下钻 |
| J3 Role views | PARTIAL | executive/business/technical view 已有基础条件渲染 | 改为真实角色目标，不只隐藏卡片 |
| J4 Presentation mode | PARTIAL | 已有 dashboard view 参数，但无完整 PresentationMode shell | 新增纯 16:9 展示层，不改变现有 dashboard API |
| J5 chart truthfulness | PARTIAL | 当前没有假随机趋势证据，但历史 snapshots 缺失 | 无 snapshot 时明确显示“暂无历史报送期数据” |

## Wave K — Governance Experience

| Item | Classification | Finding | Decision |
|---|---|---|---|
| K1 Review Workspace | MISSING | 任务详情/字段场景页分散，没有统一 review workspace | 复用 ReviewTask/Decision/Workflow，先统一详情 shell |
| K2 Business Diff | PARTIAL | 有部分 JSON/summary 展示和版本数据，但无统一人类 diff | 新增共享 diff view model，JSON 仅放技术详情 |
| K3 Quality Rule Builder | REFACTOR | 前端直接输入 entity_type/entity_id 和参数 JSON | 按 rule_type 动态表单 + asset picker；后端 contract 保持兼容 |
| K4 Impact Story | PARTIAL | 后端链完整，前端 `JSON.stringify` 和内部 task key 较多 | 只重构 UI，不重做 impact chain |
| K5 Deliverable Preflight | MISSING | 现有创建/生成/审批流程存在，但无 ReportingCycle-aware wizard | 新增 preflight UI，复用现有 validation/readiness engine |

## Wave L — Product Finish

| Item | Classification | Finding | Decision |
|---|---|---|---|
| L1 Saved Views | MISSING | 没有统一保存视图 contract | 先 local project/user preference contract，保留未来 server persistence seam |
| L2 Recent/Favorite | PARTIAL | GlobalSearch 已有 recent | 统一 Recent Assets，Favorite 后置 |
| L3 Role-aware landing | MISSING | 登录后固定工作台入口 | 增加默认 landing/shortcut，不限制跨角色访问 |
| L4 Contextual help | PARTIAL | 页面有零散说明 | 建立少量业务术语 tooltip/empty guidance |
| L5 Accessibility | PARTIAL | semantic/catalog 有较完整 keyboard/ARIA 测试，其他页面不一致 | 迁移 DataGrid、Dialog、导航时同步补焦点与 aria |
| L6 Performance pass | PARTIAL | 已有 query cancellation/polling/semantic browser harness | 需要真实浏览器 profiling，不以 hidden loading 或假 cache 代替 |
| L7 Branding | REFACTOR | 当前品牌是“一表通口径平台 / 字段级口径 · 智能辅助” | 只改展示层为“监管数据智能治理平台 / 监管语义 · 需求口径 · 数据血缘 · 智能治理” |

## 推荐执行顺序

1. H1/H6：先修 Workspace 1366 响应式和统一产品语言，直接改善核心使用门槛。
2. H2/H3/H4：建立 DataGrid、我的工作、通知的共享 contract，避免继续扩大页面分叉。
3. I1-I4：ReportingCycle → Metric Definition → Coverage → Snapshot，先把指标事实层立住。
4. J：机构驾驶舱与项目 dashboard 2.0，全部基于真实 cycle/snapshot。
5. K：Review Workspace、Business Diff、Quality Builder、Impact Story、Deliverable Preflight。
6. L：Saved Views、role landing、帮助、可访问性和真实浏览器性能 profiling。

## 明确不做

本审计不建议重写 Semantic Layer、RegulatoryContext、Generator、Workflow、Lineage、UAT backend，不引入 Neo4j、多 Agent、移动端或新技术栈，不使用假数据填充 Dashboard，不覆盖已有未提交工作区内容。
