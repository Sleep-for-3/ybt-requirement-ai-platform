# Product Intelligence Completion Report

报告日期：2026-08-28
当前事实基线：`origin/main = 96fe83768bf68c2d025b5d31a5c434db007195b5`
本地后续提交：`d3d2ab7`、`80f5d33`、`bd1e4d6`、`abab817`
状态：**Internal Product**

> 本报告按 V3 总控提示词记录实际落地范围，不把测试通过等同于产品完成，也不把未验证能力标记为生产候选。

## 1. 已落地

- 最新 `main` 审计与 `PRODUCT_INTELLIGENCE_GAP_AUDIT.md`。
- 统一产品语言：状态、严重级别、工作流步骤、实体名称；不改变 API wire enum。
- Requirement Workspace 响应式收敛：移除页面级 `min-w-[1180px]`，左侧资产区在窄屏可折叠，中间区域优先获得空间。
- `/work` 作为“我的工作”兼容入口，`/review-tasks` 保留；导航不再把审核中心命名为技术任务。
- 通知中心产品化筛选：全部、未读、审核、风险、系统；可用业务对象跳转。
- Metric Registry：代码级 Define Once, Use Everywhere，当前注册 11 个核心指标。
- Analytics Overview Dataset：`GET /api/projects/{project_id}/analytics/overview`，返回 metric definition、numerator、denominator、value、scope、as_of、risk_distribution 和 drill target。
- Evidence Coverage 按“有至少一条合格证据的 Mapping 对象 / eligible Mapping 对象”计算，不按证据条数冒充覆盖对象数。
- ReportingCycle 与 MetricSnapshot additive 模型、schema、migration、项目级周期 API；当前 overview 可绑定周期并使用 data cutoff，历史 snapshot 尚未自动计算。
- 项目 Dashboard 开始消费 governed analytics overview，并展示统一指标条带与风险结构。
- 机构级 `/cockpit`：仅消费当前用户可见项目，展示准备度排序、风险结构与项目驾驶舱下钻。
- `DATA_INTELLIGENCE_ARCHITECTURE.md`：记录 Source → Curated → Semantic → Metric → Analytics/AI → Governance/Lineage 的真实代码映射。

## 2. Databricks Data Intelligence 映射

| 层 | 当前代码映射 | 状态 |
|---|---|---|
| Source Assets | `DataSource`、Catalog、Metadata Drift、BusinessSystem | 已有并保留 |
| Curated Regulatory Data | Mart/Target/Source-to-Mart/Mart-to-YBT | 已有并保留 |
| Semantic Layer | SemanticConcept/Version/Binding、RegulatoryContext、Evidence | 已有并保留 |
| Metric Layer | `backend/app/services/analytics/metric_registry.py`、overview service | 已落地第一版 |
| Analytics / AI | overview dataset、项目 Dashboard、AI Draft/RAG | 部分落地 |
| Governance / Lineage | ReviewTask、Workflow、Deliverable、UAT、ImpactAnalysis | 已有并保留 |

## 3. Metric Registry

当前代码级 Registry 包含：

`readiness_score`、`business_definition_coverage`、`technical_lineage_coverage`、`evidence_coverage`、`review_completion_rate`、`review_sla_compliance`、`open_question_rate`、`high_risk_impact_count`、`schema_drift_count`、`lineage_unresolved_rate`、`deliverable_readiness`、`ai_draft_adoption_rate`。

每个定义均包含 numerator/denominator、eligible/excluded population、dimensions、owner、version、certification status。零分母返回 `value: null`。

## 4. Analytics Datasets 与 Dashboard 图表

已验证 Dataset：

- `project-analytics-overview`
- `institution-cockpit`

已消费视图：统一指标条带、风险结构条形分布、项目准备度排名。尚未实现的 V3 图表包括历史趋势、准备度热力图、Pareto、SLA Aging、Impact Sankey、质量趋势和 AI Insight Rail；没有历史快照时不得合成这些图。

## 5. Cross-filter / Drill-through

已具备：项目权限过滤、风险项 drill target、项目 Dashboard → readiness/lineage/knowledge/work、机构 Cockpit → 项目 Dashboard。

未完成：统一 URL-owned Global Filter Bar、跨图联动、周期/表/场景/严重级别组合筛选与返回状态完整恢复。

## 6. 测试与验证

- 前端现有测试：88 项通过。
- 前端 TypeScript：通过。
- 前端生产构建：成功。
- 后端 Metric Registry/Analytics 定向测试：5 项通过；治理 Dashboard 兼容测试通过。
- Python `compileall`：通过。
- Alembic head：`202608280020`。
- 本地 `alembic check`：未通过，因为本地测试数据库仍停留在旧 head；没有执行升级，避免修改用户环境。
- 真实浏览器四视口 Dashboard/Cockpit UAT：未完成。

## 7. 尚未完成项

- ReportingCycle 与 MetricSnapshot 的自动计算、周期历史趋势和快照 API。
- Analytics Dataset 拆分：readiness trend/matrix、risk、aging、quality、impact flow、data health、AI effectiveness。
- 按需图表基础设施（ECharts 或等价轻量库）、统一主题和 ResizeObserver。
- Executive Presentation Mode 的独立 16:9 canvas、全屏/打印/PDF/PNG 快照。
- Business/Technical/Quality Analytics 完整视图。
- Metric provenance 可视化与结构化 AI Insight（supporting metrics、confidence、drill targets）。
- EnterpriseDataGrid 全面迁移、Quality Rule Builder、Deliverable Preflight、Business Diff。
- 四视口真实浏览器验收及 staging PostgreSQL 并发/备份恢复/driver matrix。

## 8. Staging 才能验证项

- PostgreSQL head migration 与真实周期/快照写入。
- 多用户并发创建周期、快照唯一约束与锁行为。
- 大规模项目下 overview 查询性能和索引计划。
- DataSource driver matrix、Metadata Drift 真实事件。
- 浏览器 1366×768、1440×900、1920×1080 及 Presentation Mode。
- 生产认证、机构/项目隔离、备份恢复、性能基准和可观测性。

## 9. 当前产品状态判定

**Internal Product**。原因：事实层、治理链和第一版可信 Metric/Analytics 已可供内部持续使用；但 V3 要求的完整交互式驾驶舱、历史周期趋势、Presentation Mode 和 staging 验证尚未全部完成，因此不能称为 UAT Ready 或 Production Candidate。
