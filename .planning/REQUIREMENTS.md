# Requirements: Regulatory Data Intelligence V2

**Defined:** 2026-08-20
**Core Value:** 监管语义、口径、证据、血缘和治理关系是可持续资产，AI 只能消费并建议，不能越权成为事实。

## v2.0 Requirements

### Semantic Foundation

- [x] **SEM-01**: 授权用户可在项目内创建、查看、编辑和停用带类型、版本、置信度与治理状态的 SemanticConcept。
- [x] **SEM-02**: 授权用户可将概念绑定到 Target/Source/Mart 表字段、Scenario、KnowledgeUnit 和三类 Mapping/Lineage 实体，且服务验证实体真实存在并属于同一项目/机构。
- [x] **SEM-03**: 授权用户可建立受控类型的概念关系并进行有限深度邻居、上下游和路径查询。
- [x] **SEM-04**: AI 创建的概念、绑定与关系只能进入 `ai_suggested`，人工确认、拒绝和废弃转换受权限、证据和审计约束。
- [x] **SEM-05**: PostgreSQL 与 SQLite 均可无损升级/降级语义表，现有 formal semantic index、业务表和数据不被修改。
- [x] **SEM-06**: 语义 API 在 list/detail/create/update/status/graph 查询中强制 project 与 institution isolation，并对重复对象返回稳定冲突错误。
- [x] **SEM-07**: 系统可用 deterministic resolver 按 code/name/alias/comment/confirmed binding 等优先级返回候选与 provenance，LLM inference 仅为最后一级建议。

### Regulatory Context

- [x] **CTX-01**: 调用方可按 project 与可选 target table/field、scenario、mart field、semantic concept 构建稳定的 Pydantic RegulatoryContext。
- [x] **CTX-02**: Context 明确区分 confirmed、regulatory、approved mapping、verified lineage、metadata、historical、retrieved 与 inferred 权威等级。
- [x] **CTX-03**: Context 聚合语义、映射、技术血缘、知识证据、历史口径、冲突和待确认问题，但不复制现有事实模型。
- [x] **CTX-04**: Context 对缺失知识、缺失血缘、冲突事实和证据不足有确定性输出与测试。

### Generator Migration

- [x] **GEN-01**: Source→Mart Generator 主要消费 RegulatoryContext，同时保留现有 API、structured output 与 task-specific instruction。
- [x] **GEN-02**: Mart→YBT Generator 主要消费 RegulatoryContext，同时保留现有 API、structured output 与 Source→Mart 摘要语义。
- [x] **GEN-03**: Scenario generators 在适用范围消费同一 Context，confirmed/final 内容不会被 AI draft 覆盖。
- [x] **GEN-04**: 缺少证据时生成器产生 open question，不凭空创建不存在的表、字段或正式状态。

### Semantic Experience

- [ ] **SUI-01**: 用户可通过 `/semantics` 浏览、筛选语义目录并看到 loading/empty/error/unauthorized/pending 状态。
- [x] **SUI-02**: 用户可在 `/semantics/{id}` 浏览定义、绑定、关系、知识、证据、血缘、版本和治理状态。
- [ ] **WRK-01**: 需求工作台默认展示结构化口径，并提供血缘、证据、待确认和文档预览 tabs。
- [ ] **WRK-02**: 结构化口径能链接 SemanticConcept、Source/Mart/Target、Evidence、Knowledge 与 Lineage，旧 routes 保持可用。
- [ ] **WRK-03**: Deliverables 从同一份 Structured Requirement Snapshot 渲染现有 Excel/Word/Markdown 能力，渲染产物不是事实源。

### Intelligence and Quality

- [ ] **DSH-01**: 首页从真实 API 展示 semantic、mapping、lineage coverage、open questions、conflicts 与 project readiness。
- [ ] **DSH-02**: 覆盖率分母、分子和 eligible population 可追溯，不把空项目或 AI suggestion 计为 confirmed coverage。
- [ ] **DQA-01**: 授权用户可建立绑定语义概念和目标实体的结构化 DataQualityExpectation，并复用到 Requirement/Mapping/UAT。
- [ ] **DQA-02**: 质量规则支持 not_null、unique、range、enum、referential、consistency、custom_expression 与治理状态。

### Semantic Impact

- [ ] **IMP-01**: 现有 SQL change/ImpactAnalysis 可沿 LineageNode/Edge 与 SemanticBinding 找到受影响概念和监管规则，不复制技术血缘。
- [ ] **IMP-02**: 语义影响结果携带路径、证据、置信度和待确认状态，并可进入现有 Governance/ReviewTask。

## Future Requirements

- **FUTR-01**: 基于稳定 Semantic + Context 的完整 SQL Generator。
- **FUTR-02**: 在实际 PostgreSQL benchmark 证明必要后评估专用图基础设施。
- **FUTR-03**: 跨项目/全机构共享概念库及独立发布治理。

## Out of Scope

| Feature | Reason |
|---------|--------|
| Neo4j / GraphRAG infrastructure | 当前规模可用关系表和有界 traversal，避免内网运维复杂度 |
| 完整 SQL Generator | 必须排在 Semantic、Context、Requirement 和 Review 稳定之后 |
| 重写 Metadata/Knowledge/Lineage/Governance | 已有成熟能力，本里程碑只新增连接层 |
| Multi-Agent workflow demo | 采用 deterministic workflow + specialized AI steps |
| 公网或 SaaS-only dependency | 银行内网离线部署约束 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SEM-01, SEM-02, SEM-03, SEM-04, SEM-05, SEM-06, SEM-07 | Phase 8 | Complete |
| CTX-01, CTX-02, CTX-03, CTX-04 | Phase 9 | Complete |
| GEN-01, GEN-02, GEN-03, GEN-04 | Phase 10 | Complete |
| SUI-01, SUI-02 | Phase 11 | Gaps Found |
| WRK-01, WRK-02, WRK-03 | Phase 12 | Pending |
| DSH-01, DSH-02 | Phase 13 | Pending |
| DQA-01, DQA-02 | Phase 14 | Pending |
| IMP-01, IMP-02 | Phase 15 | Pending |

**Coverage:** 26 requirements, 26 mapped, 0 unmapped.

---
*Requirements defined: 2026-08-20*
