# Roadmap: Regulatory Data Intelligence V2

## Milestone Goal

把现有 Metadata、Knowledge、Mapping、Lineage、Governance 和 Deliverables 连接到统一、受治理的监管语义与上下文层，并在每个阶段保持系统可启动、可测试和 API 兼容。

### Phase 8: Semantic Foundation

**Goal:** 建立可治理、可查询、隔离安全的 Regulatory Semantic Layer。
**Requirements:** SEM-01, SEM-02, SEM-03, SEM-04, SEM-05, SEM-06, SEM-07
**Plans:** 4 plans
**Status:** Complete (2026-08-20)
**Success Criteria:**

1. 可创建“客户、同业客户、客户统一编号、客户类型”并绑定 TargetField、MartField、SourceField、KnowledgeUnit。
2. AI suggestion 不能直接 confirmed，状态转换和所有写操作可审计。
3. 邻居、上下游、entity semantics 和有限路径查询在项目边界内返回稳定结果。
4. SQLite migration upgrade/downgrade 与语义 API 测试通过，现有后端回归不退化。

### Phase 9: Regulatory Context

**Goal:** 建立统一、版本明确、带权威等级和 provenance 的 RegulatoryContext Contract。
**Requirements:** CTX-01, CTX-02, CTX-03, CTX-04
**Plans:** 4/4 plans complete

- [x] 09-01-PLAN.md
- [x] 09-02-PLAN.md
- [x] 09-03-PLAN.md
- [x] 09-04-PLAN.md

**Status:** Complete (2026-08-23) — 4/4 plans verified; CTX-01 through CTX-04 satisfied
**Success Criteria:**

1. 指定 project/target_field/scenario 可得到稳定结构化 Context。
2. confirmed 事实稳定压过 historical/retrieved/inferred 候选。
3. 缺失、冲突、证据和 open question 可被机器识别和测试。

### Phase 10: Generator Refactor

**Goal:** 让现有 Mapping/Scenario Generator 渐进消费统一 Context，保持旧 API 和治理边界。
**Requirements:** GEN-01, GEN-02, GEN-03, GEN-04
**Plans:** 8/8 plans complete

- [x] 10-05-PLAN.md
- [x] 10-06-PLAN.md
- [x] 10-07-PLAN.md
- [x] 10-08-PLAN.md

**Wave 1**

- [x] 10-01-PLAN.md

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 10-02-PLAN.md

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 10-03-PLAN.md

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 10-04-PLAN.md

**Status:** Complete (2026-08-24) — 8/8 plans verified; GEN-01 through GEN-04 satisfied
**Success Criteria:**

1. 两个 Mapping Generator 的共享事实查询从 ContextBuilder 获取。
2. Generator 独有 task instruction 与 structured output 保留。
3. AI draft 不覆盖 final/confirmed，缺少证据产生问题而非幻觉。

### Phase 11: Semantic Catalog UI

**Goal:** 在现有 Next.js 与 Design Tokens 中提供完整语义目录和详情体验。
**Requirements:** SUI-01, SUI-02
**Plans:** 3/4 plans executed
**Success Criteria:**

1. `/semantics` 和 `/semantics/{id}` 可浏览真实 API 数据。
2. binding、relation、knowledge、evidence、lineage 和 governance 状态可追溯。
3. loading/empty/error/unauthorized/no-binding/conflict/pending-review 均有测试状态。

Plans:
**Wave 1**

- [x] 11-01-PLAN.md — Establish authoritative semantic catalog projection and tracer route

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 11-02-PLAN.md — Build grouped catalog browsing, filtering, and navigation UI

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 11-04-PLAN.md — Build governed semantic detail backend projections and security contract

**Wave 4** *(blocked on Wave 3 completion)*

- [ ] 11-03-PLAN.md — Build governed semantic detail frontend and traceability regions

### Phase 12: Requirement Workspace V2

**Goal:** 将现有需求工作台升级为结构化口径优先，文档降级为 renderer。
**Requirements:** WRK-01, WRK-02, WRK-03
**Success Criteria:**

1. 默认 tab 是结构化口径，其他 tabs 为血缘、证据、待确认、文档预览。
2. 结构化事实可以跳转到语义、数据资产、知识和血缘详情。
3. 现有 Deliverables 使用 snapshot 投影，不把生成文档回写为事实源。

### Phase 13: Intelligence Dashboard

**Goal:** 用真实、可解释的覆盖率和待办替换 AI 聊天优先首页。
**Requirements:** DSH-01, DSH-02
**Success Criteria:**

1. semantic/mapping/lineage coverage 与 eligible population 可追溯。
2. open questions、conflicts、impacted entities 和 readiness 来自真实 API。
3. 空项目不产生误导百分比或静态假数据。

### Phase 14: Quality Expectations

**Goal:** 把文本质量规则提升为可复用、可治理的 DataQualityExpectation。
**Requirements:** DQA-01, DQA-02
**Success Criteria:**

1. 质量规则可绑定概念和现有目标实体并支持首批规则类型。
2. Requirement、Mapping 与 UAT 可引用同一条规则。
3. AI suggestion 和人工 confirmed 仍严格区分。

### Phase 15: Semantic Impact Analysis

**Goal:** 连接 SQL change → technical lineage → semantic concept → regulatory requirement → governance。
**Requirements:** IMP-01, IMP-02
**Success Criteria:**

1. 现有 ImpactAnalysis 可扩展返回受影响概念、规则和需求路径。
2. 不复制 LineageNode/Edge，跨层连接由 SemanticBinding 完成。
3. 影响结果带证据和待确认状态，并进入现有 ReviewTask。

## Phase Ordering Rationale

Semantic Foundation 是所有后续事实连接的先决条件；Context 在语义稳定后统一事实；Generator 只在 Contract 可测后迁移；UI、Dashboard、Quality 和 Impact 依次消费已稳定后端能力。完整 SQL Generator 明确延后。

---
*Created: 2026-08-20*
