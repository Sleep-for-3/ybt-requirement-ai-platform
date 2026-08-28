# Product Intelligence Gap Audit

审计日期：2026-08-28  
事实基线：`origin/main = 96fe83768bf68c2d025b5d31a5c434db007195b5`  
审计范围：V3 总控提示词要求的 Data Intelligence、Metric、Analytics、Dashboard 与治理消费链。

## 结论

现有 Semantic Catalog、RegulatoryContext、Mapping、Evidence、Lineage、QualityExpectation、Workflow/ReviewTask、Deliverable、UAT、权限隔离和基础 Dashboard 事实源均应 KEEP。当前产品的主要问题不是缺少后台实体，而是缺少统一 Metric Layer、Analytics Dataset、Reporting Cycle 维度和以视觉分析为主体的驾驶舱消费层。

## 现状分类

| 范围 | 分类 | 代码证据 | 决策 |
|---|---|---|---|
| AppShell / 项目切换 | KEEP / PARTIAL | `frontend/components/AppShell.tsx`、`ProjectContext.tsx` | 保留现有权限与项目边界，后续只接入角色化首页 |
| GlobalSearch / 导航 | KEEP / PARTIAL | `frontend/components/GlobalSearch.tsx`、`navigation-contract.mjs` | 保留契约；低频技术工具继续收敛 |
| Semantic Layer | KEEP | `backend/app/models/semantic.py`、`frontend/app/semantics` | 不重做，作为 Metric/AI Context 来源 |
| Source / Catalog / Metadata | KEEP | `backend/app/models/entities.py`、`frontend/app/catalog`、`datasources` | 不重做，补数据健康 Dataset |
| Lineage / Impact | KEEP | `backend/app/models/lineage.py`、`frontend/app/lineage` | 不重做，补 Metric provenance 和风险下钻 |
| Quality | PARTIAL | `backend/app/models/quality.py`、`frontend/app/quality` | 保留 Expectation；区分规则覆盖与执行结果 |
| Workflow / Review / Notification | KEEP / PARTIAL | `backend/app/models/governance.py`、对应 API | 保留治理状态；补业务上下文与 SLA Dataset |
| Requirement Workspace | KEEP / PARTIAL | `frontend/components/requirement-workspace` | 已完成响应式修复；继续接入 Metric/Reporting Cycle |
| Project Dashboard | REFACTOR | `backend/app/api/dashboard.py`、`frontend/app/projects/[projectId]/dashboard/page.tsx` | 保留事实查询与权限，新增 Analytics Dataset 消费层，逐步退出 Card Soup |
| Institution Cockpit | MISSING | 未发现 `/cockpit` 与机构级 analytics API | 后续新增，复用项目 dashboard 聚合和 PermissionService |
| Metric Definition Registry | MISSING | 当前指标定义嵌在 Dashboard API 返回值 | 当前波次优先新增代码级 registry，Define Once, Use Everywhere |
| Metric Snapshot | MISSING | 未发现对应模型、migration、API | 依赖 ReportingCycle，后续新增 additive migration |
| ReportingCycle | MISSING | 全仓库未发现正式模型 | 后续新增单一业务模型，不改写历史数据 |
| Analytics Dataset API | MISSING | 仅有 `/projects/{id}/dashboard` scalar response | 当前波次新增 overview dataset；后续拆分 trend/matrix/risk/aging |
| Chart engine | MISSING | `frontend/package.json` 无 ECharts 或其他图表库 | 后续评估轻量按需引入，先不以图表库掩盖事实层缺口 |
| Cross-filter / Drill-through | PARTIAL | 现有 URL filters 与 detail return state | 后续统一 URL-owned analytics filters |
| Presentation Mode | PARTIAL | Dashboard 有 `reportMode` 开关 | 后续重做为独立 16:9 canvas，不改变事实 API |
| AI Insight | PARTIAL | AI 草稿与知识问答已存在，Dashboard 无结构化 insight | 后续只允许消费 Metric + Semantic Context，并带 supporting metrics |
| 产品语言 | PARTIAL | 已有 `frontend/lib/product-language.ts` | 继续替换核心页面内部 enum；不改 wire values |
| 浏览器 UAT | PARTIAL | Semantic/Catalog 有浏览器 harness | V3 所要求的 Dashboard 四视口与 Presentation Mode 尚未验证 |

## V3 缺口优先级

1. Metric Registry + truthful core coverage（当前实施）
2. ReportingCycle + MetricSnapshot（需要 additive migration）
3. Analytics Dataset API（当前实施 overview，后续分 dataset）
4. ECharts foundation + Executive Cockpit `/cockpit`
5. URL-owned filters、cross-filter、drill-through、Metric provenance
6. Business / Technical / Quality analytics、Presentation Mode、结构化 AI Insight

## 明确未做

本轮不重写 Semantic、RegulatoryContext、Lineage Graph、Next.js、后端框架；不引入 Neo4j、外部 BI SaaS、移动端或假趋势。没有历史 MetricSnapshot 时，趋势必须返回空态而不是合成数据。

