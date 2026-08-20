# 监管数据智能平台

## What This Is

面向银行监管报送的 Regulatory Data Intelligence Platform。系统把监管制度、模板、历史口径、数据资产、知识、映射和血缘组织为可治理、可追溯的结构化事实；AI 通过统一 Regulatory Context 工作，而不是直接面对零散数据库与文档自由生成。

## Core Value

银行自己的数据语义、监管口径、证据、血缘和治理关系是核心资产；模型可替换，AI 草稿永远不能越过人工确认成为正式事实。

## Current Milestone: v2.0 Regulatory Data Intelligence V2

**Goal:** 以 additive architecture 建立业务监管语义层，并逐步让 Context、Generator、前端、质量与影响分析消费同一套受治理事实。

**Target features:**

- SemanticConcept / SemanticBinding / SemanticRelation 与完整治理、审计和有限深度图查询。
- RegulatoryContextBuilder 及权威优先级、证据来源、冲突与待确认契约。
- 在保持 API 兼容的前提下迁移现有 Mapping/Scenario Generator。
- 语义目录、结构化需求工作台、真实指标首页、质量期望与语义影响分析。

## Requirements

### Validated

- ✓ Project、Target/Source/Mart、Scenario、双层 Mapping 与场景口径模型已存在。
- ✓ KnowledgeUnit、HybridRetriever、向量索引治理、证据与 RAG evaluation 已存在。
- ✓ LineageNode/Edge、SQL 解析、版本差异与 ImpactAnalysis 已存在。
- ✓ Governance、ReviewTask、Audit、Deliverables 与 UAT 已存在。
- ✓ v1.0 前端工作台实现已保留为 legacy snapshot。

### Active

- [ ] 建立 project-scoped、institution-aware 的监管语义对象、绑定和关系。
- [ ] 建立统一 Regulatory Context Contract 与 authority priority。
- [ ] 让生成器逐步消费统一 Context，保持现有 API 与人工最终内容边界。
- [ ] 将语义、结构化口径、真实覆盖率和技术/业务影响呈现在现有前端中。
- [ ] 将文档定位为结构化事实的 renderer，而不是事实源。

### Out of Scope

- Neo4j、JanusGraph、Neptune、GraphRAG 专用基础设施或新的独立数据库。
- 完整 SQL Generator、微服务拆分、Kafka、Kubernetes、多 Agent swarm。
- 重写 Metadata、Knowledge、Lineage、Governance、RAG、Deliverables 或前端 Design System。
- 公网/SaaS-only 依赖、云端托管图数据库或更换现有 LLM Gateway。

## Context

- Git 基线仍为 `21715fd114475cd879ac7896f26d12a6dfe85e4d`，当前分支包含未提交的 v1.0 前端成果，必须保留。
- Alembic head 为 `202607300014`; 该 formal semantic index 只治理 embedding/vector index，不是业务语义层。
- PostgreSQL 是生产目标，SQLite 是测试与兼容模式；所有迁移必须双兼容、可升级且尽量可降级。
- 详细代码取证与 15 个架构问题结论见 `.planning/codebase/REGULATORY-SEMANTIC-ASSESSMENT.md`。

## Constraints

- **Compatibility:** 不删除或大规模重命名现有 API、模型与 routes；采用增量架构和渐进迁移。
- **Isolation:** 所有语义查询和写入必须同时验证 project scope；存在 institution 时还必须匹配 Project.institution_id。
- **Governance:** AI 只能产生 `ai_suggested`; `confirmed` 必须走人工权限与审计边界。
- **Evidence:** 正式事实、confirmed mapping 和 verified lineage 高于历史/RAG/AI inference。
- **Deployment:** 银行内网友好，无新增公网依赖；继续复用 confidentiality 与 model runtime 控制。
- **Delivery:** Structured Requirement 是事实投影；Word/Excel/Markdown/PDF 仅为 renderer。

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| v2.0 phases 延续编号 8–15 | 保留旧里程碑编号，不伪造缺失历史 | Accepted |
| SemanticConcept 第一版 project-scoped，并复制 institution_id 作隔离索引 | 现有知识、映射、血缘均以 project 为主；跨项目共享需要独立治理，当前不安全 | Accepted |
| SemanticBinding 使用受控 entity_type + entity_id | 复用现有多类实体且避免 JSON 关系堆积；服务层验证实体存在与 scope | Accepted |
| SemanticRelation 使用 PostgreSQL/SQLite 邻接表与有界 BFS | 当前规模无需图数据库，运维和内网部署更简单 | Accepted |
| formal_semantic_index 保持不变 | 它治理向量索引版本，与业务语义职责不同 | Accepted |
| Phase 8 不实现 ContextBuilder 或 Generator 重构 | 先稳定模型、治理、查询和测试契约，避免大爆炸式迁移 | Accepted |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `$gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `$gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-08-20 for milestone v2.0*
