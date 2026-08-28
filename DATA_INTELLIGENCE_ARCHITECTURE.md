# Data Intelligence Architecture

基于代码事实的架构映射（2026-08-28，`origin/main = 96fe837`）。本文件不是营销描述。

```text
Source Assets
  DataSource / CatalogTable / CatalogColumn / MetadataDriftEvent / BusinessSystem
        ↓
Curated Regulatory Data
  MartTable / MartField / TargetTable / TargetField / SourceToMartMapping / MartToYbtMapping
        ↓
Regulatory Semantic Layer
  SemanticConcept / SemanticConceptVersion / SemanticBinding / RegulatoryContext / Evidence
        ↓
Governed Metric Layer
  backend/app/services/analytics/metric_registry.py
  MetricDefinition + metric_query_service（当前实时 overview；Snapshot/ReportingCycle 待补）
        ↓
Analytics / AI
  analytics overview dataset / project dashboard / AI draft generation / RAG knowledge flows
        ↓
Governance / Lineage / Action
  WorkflowInstance / ReviewTask / ReviewDecision / Deliverable / UAT / ImpactAnalysis
```

## 当前真实落地

- Source、Curated、Semantic、Governance、Lineage 的对象和权限边界已存在，并继续复用。
- Metric Registry 现在是代码级唯一指标定义来源；Dashboard/Analytics 不应自行定义同名业务指标。
- `/api/projects/{project_id}/analytics/overview` 返回 `dataset_id`、`metrics`、`risk_distribution`、`filters`、`as_of` 与每个指标的定义/口径/维度/认证状态。
- AI 草稿仍通过现有 Mapping 与上下文链路工作，不能绕过 Semantic 或 Metric Layer 直接生成统计数字。
- Impact Analysis 已有从变更到语义、需求和审核任务的 JSON scope；后续 Dashboard Risk 应消费该真实链路，而不是复制另一套 Lineage 模型。

## 尚未落地

- ReportingCycle、MetricSnapshot 的持久化模型和 migration。
- 按周期的历史趋势、机构级 `/cockpit`、矩阵/分布/aging/Pareto/Sankey 等分析 Dataset。
- 统一 ECharts 按需基础设施、URL-owned Global Filter Bar、Cross-filter 和 Drill-through。
- Metric provenance 的正式可视化页面、结构化 AI Insight Rail、真正独立的 16:9 Presentation Mode。

## 信任边界

当前 `analytics overview` 只使用实时数据库事实与 `as_of` 时间戳；不存在历史快照时不返回伪造趋势。ratio 指标在分母为 0 时返回 `value: null`，前端必须显示“暂无可计算对象/N/A”，不能渲染为 0% 或 100%。

