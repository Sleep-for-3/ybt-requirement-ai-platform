# Phase 09: Regulatory Context - Research

**Researched:** 2026-08-20 [VERIFIED: runtime date]
**Domain:** Project-scoped governed semantic hardening, temporal semantic concept versions, and read-only RegulatoryContext projection [VERIFIED: .planning/PROJECT.md:7-22; .planning/phases/09-regulatory-context/09-CONTEXT.md:7-30]
**Confidence:** MEDIUM/HIGH — current repository behavior and Phase 8 evidence are HIGH confidence; the temporal bootstrap policy, additive REST shape, binding scope, reporting-period boundary, and local/staging qualification split are now locked planning decisions. Live PostgreSQL execution remains an external release qualification gate. [VERIFIED: .planning/phases/08-semantic-foundation/08-VERIFICATION.md:41-53; .planning/phases/09-regulatory-context/09-CONTEXT.md]

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:5-30 — verbatim source block]

- **D-01 Phase boundary:** Phase 9 starts with Semantic Hardening, then defines and builds RegulatoryContext. Phase 10 Generator migration, frontend routes, SQL generation, DataQualityExpectation, semantic impact propagation, graph infrastructure and product multi-agent features remain out of scope.
- **D-02 Trusted semantic policy:** Default business-fact queries use `confirmed` only. `draft` and `ai_suggested` are visible only through an explicit candidate/review mode. `rejected` and `deprecated` are audit/history-only and can never re-enter trusted graph paths, resolver recommendations or generated facts.
- **D-03 Shared policy:** Concept, binding, relation and version lifecycle filtering is defined once in a semantic status-policy module. Graph, resolver and ContextBuilder consume that module instead of maintaining local status sets.
- **D-04 Resolver boundary:** A `SemanticEntityAdapter` explicitly maps every supported binding entity into a stable semantic descriptor. Resolver performs matching/ranking only and does not assemble ORM-specific fields through an expanding generic `getattr` chain.
- **D-05 Deterministic ranking:** Resolver ranking is stable and deterministic. Confirmed binding has the highest confidence, followed by exact concept code, canonical name, alias, regulatory text and metadata/definition text. Keyword, embedding and LLM tiers remain additive future candidates and cannot create confirmed truth.
- **D-06 Candidate provenance:** Every resolver candidate carries `match_reason`, evidence and provenance, remains `ai_suggested`, and never auto-confirms.
- **D-07 Stable identity and temporal content:** `SemanticConcept` remains the project-scoped stable identity keyed by `(project_id, concept_type, concept_code)`. `SemanticConceptVersion` stores governed meaning, version number and effective dates. The unique identity constraint is retained on Concept, not duplicated across versions.
- **D-08 Version authority:** Semantic version rows are the canonical source for versioned definition, description, aliases, domain, owner, provenance and confirmation metadata. Legacy Concept fields remain as an explicitly documented compatibility projection during the milestone and must not become a second independently editable truth.
- **D-09 Effective-period semantics:** `effective_from` and `effective_to` are inclusive business dates. A confirmed version is selected when `effective_from <= as_of` and (`effective_to` is null or `effective_to >= as_of`). Confirmed periods for one Concept may not overlap.
- **D-10 Version governance:** `draft` and `ai_suggested` versions may coexist. A confirmed version is immutable; changed meaning is a new version. `rejected` and `deprecated` versions are never selected by effective-date resolution.
- **D-11 Migration:** Alembic revision after `202608200015` creates the version table and bootstraps exactly one version per existing Concept using its current row content and lifecycle status. A legacy row with `version > 1` still becomes one bootstrap version because the old number is an edit counter, not recoverable history.
- **D-12 Binding and relation scope:** SemanticBinding continues to target stable Concept identity. An optional version-specific binding is permitted only when a technical entity is genuinely version-limited; old bindings are not copied per version. Relations remain identity-level in Phase 9; a temporal graph is not introduced.
- **D-13 Context date:** `as_of` is the effective business date used to select semantic versions. `reporting_period` may be accepted only as a normalized input/label using an existing project convention; Phase 9 does not add a new reporting-period persistence system.
- **D-14 Context contract:** `RegulatoryContext` is a versioned Pydantic contract (`context_schema_version = "1.0"`) with scope, target, scenario, semantic, regulatory, candidate, mapping, lineage, knowledge/evidence, historical, quality, conflicts, open questions and build metadata sections. It returns compact normalized facts and references, not ORM dumps.
- **D-15 Fact model:** All sections use a shared typed `ContextFact` envelope with `fact_type`, structured value, authority, state, source type/id, evidence references, version/effective period, observed time and confidence. Structured value types remain bounded by section schemas rather than an unconstrained JSON store.
- **D-16 Authority and state:** Authority ranking is code-defined and separate from state. Human-confirmed and formal regulatory facts outrank confirmed semantic versions, approved mappings, verified lineage, metadata, confirmed history, retrieved knowledge and AI inference. Retrieval similarity never promotes knowledge to confirmed.
- **D-17 Projection only:** ContextBuilder is an orchestration/projection service over existing Metadata, Mapping, Knowledge, Evidence, HistoricalCaliber and Lineage models. It persists no copied context facts, mappings or lineage and introduces no cache/snapshot table in Phase 9.
- **D-18 Deterministic gaps:** Conflicts and open questions are produced deterministically for missing confirmed semantic binding/version, missing Source-to-Mart or Mart-to-YBT mapping, missing/stale lineage, missing evidence, historical-only definitions and conflicting facts. The builder does not silently choose between authoritative contradictions.
- **D-19 Candidate collection:** Source/Mart candidates are ranked by confirmed bindings/mappings, exact code/name, semantic evidence, metadata keywords, historical mappings, lineage neighborhood and retrieval evidence. Database natural order plus `.limit(50)` is not an acceptable ContextBuilder strategy.
- **D-20 Isolation and confidentiality:** Every query is project-scoped, honors Project institution ownership, preserves current permissions, propagates knowledge confidentiality/source/retrieval-log provenance and never leaks cross-project or cross-institution data.
- **D-21 Compatibility:** Phase 8 Concept/Binding/Relation CRUD, status, graph and resolver endpoints remain available. Version endpoints and current/latest effective version fields are additive; no current endpoint or field is removed in Phase 9.
- **D-22 Performance:** Collectors batch by ids with `IN`, joins or select-in patterns. Tests include a query-count/N+1 sanity check. Phase 9 does not add a cache layer.
- **D-23 API behavior:** Provide a read-only/debug Context build API under the existing project-aware FastAPI style. Building context does not modify authoritative facts.
- **D-24 Acceptance scenario:** The primary end-to-end fixture is target table `2.3 同业客户表`, field `客户统一编号`, with date-sensitive versions, mappings/evidence/lineage when present, and deterministic conflicts/open questions when absent.

### the agent's Discretion [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:32-37 — verbatim source block]

- Exact module split under `backend/app/services/semantic/`, provided builder orchestration, collectors, policy, conflict detection and question generation remain separable and no God Service is created.
- Exact REST shapes for additive SemanticConceptVersion and RegulatoryContext endpoints, provided project scope and backward compatibility remain explicit.
- Whether an optional `semantic_concept_version_id` is added to Binding in Phase 9. Default is identity-only; add it only if current data or a concrete test proves version-specific binding is necessary.
- Exact enum member names for authority/state, provided their ranking and separation satisfy D-16 and serialization remains stable.

### Deferred Ideas (OUT OF SCOPE) [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:7-8, .planning/STATE.md:58-63]

`09-CONTEXT.md` has no separate `## Deferred Ideas` heading. Its verbatim scope fence is D-01 above; the project state separately defers full SQL Generator work and institution/global shared concept publication. Do not pull those items into Phase 9.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CTX-01 | 调用方可按 project 与可选 target table/field、scenario、mart field、semantic concept 构建稳定的 Pydantic RegulatoryContext。 [VERIFIED: .planning/REQUIREMENTS.md:18-23] | Contract must expose explicit scope/target/scenario inputs, inclusive `as_of`, compact typed sections, and an additive project-aware read-only build endpoint. |
| CTX-02 | Context 明确区分 confirmed、regulatory、approved mapping、verified lineage、metadata、historical、retrieved 与 inferred 权威等级。 [VERIFIED: .planning/REQUIREMENTS.md:18-23] | A code-defined authority rank must be separate from lifecycle state; every `ContextFact` carries both plus provenance. |
| CTX-03 | Context 聚合语义、映射、技术血缘、知识证据、历史口径、冲突和待确认问题，但不复制现有事实模型。 [VERIFIED: .planning/REQUIREMENTS.md:18-23] | Builder collectors reuse existing models and `HybridRetriever`; no context persistence, duplicate lineage, or snapshot table. |
| CTX-04 | Context 对缺失知识、缺失血缘、冲突事实和证据不足有确定性输出与测试。 [VERIFIED: .planning/REQUIREMENTS.md:18-23] | Deterministic conflict/question codes, stable ordering, acceptance fixture, isolation tests, migration lifecycle tests, and query-count instrumentation are required. |
</phase_requirements>

## Summary

Phase 8 created the right additive semantic tables and project-aware routes, but the current trusted-read boundary is not safe for Phase 9. `SemanticGraphService` defaults traversal to `("confirmed", "draft", "ai_suggested")` and uses `status != "deprecated"` in entity/path helpers; `SemanticResolver` uses the same deprecated-only concept filter and discovers descriptor text through a generic `getattr` chain. The current `SemanticConcept.version` is incremented in place by concept PATCH, so it is an edit counter rather than recoverable effective-dated history. [VERIFIED: backend/app/services/semantic/graph_service.py:15-23,69-82,130-140; backend/app/services/semantic/resolver.py:23-57,60-77; backend/app/api/semantic.py:98-120; backend/app/models/semantic.py:9-38]

Use four sequential plans. Make 09-01 a standalone semantic hardening and temporal-version migration slice: centralize lifecycle policy, add explicit entity descriptors, repair deterministic resolver ordering, add `SemanticConceptVersion`, and prove `202608200016` bootstrap/up/down behavior. Then 09-02 defines the typed Pydantic contract and authority/state vocabulary, 09-03 builds a projection-only batched ContextBuilder with conflict/open-question detection, and 09-04 adds additive read-only APIs plus regression/performance qualification. [ASSUMED: proposed four-plan split]

**Primary recommendation:** Treat `SemanticConcept` as stable identity, move governed meaning to immutable date-effective version rows, and make every trusted graph/resolver/context query consume one shared policy and one explicit adapter registry before any ContextBuilder work proceeds. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:8-29]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Semantic lifecycle policy and trusted/candidate/audit visibility | API / Backend | Database / Storage | The current graph/resolver filters are service predicates, and the locked decision requires one shared policy consumed by graph, resolver, and builder. [VERIFIED: backend/app/services/semantic/graph_service.py:22,77-80,138-140; .planning/phases/09-regulatory-context/09-CONTEXT.md:8-10] |
| Explicit 12-type semantic entity descriptors | API / Backend | Database / Storage | Binding targets already live in existing SQLAlchemy models; the adapter owns stable text extraction while the database remains the source of entity rows. [VERIFIED: backend/app/services/semantic/binding_service.py:24-37; backend/app/models/entities.py:50-249,505-514] |
| Temporal concept version persistence and effective-date resolution | Database / Storage | API / Backend | Version rows, uniqueness, foreign keys, and date checks are persisted in Alembic/SQLAlchemy; service code enforces overlap and immutable-confirmed transitions portably. [VERIFIED: backend/app/models/semantic.py:9-38; .planning/phases/09-regulatory-context/09-CONTEXT.md:13-18; ASSUMED: portable service enforcement for interval overlap]
| RegulatoryContext contract and fact normalization | API / Backend | Database / Storage | CTX-01/02 require a stable Pydantic contract, while collectors read existing project-scoped rows and return compact references instead of ORM dumps. [VERIFIED: .planning/REQUIREMENTS.md:20-23; .planning/phases/09-regulatory-context/09-CONTEXT.md:20-23] |
| Mapping, knowledge, evidence, lineage, and historical collection | API / Backend | Database / Storage | ContextBuilder is an orchestration/projection service over existing models and must batch project-scoped reads. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:23-28] |
| Read-only context/debug endpoint and authorization | API / Backend | Browser / Client | Existing routers use project path parameters plus `PermissionService`; Phase 9 adds no frontend route. [VERIFIED: backend/app/api/semantic.py:39-84; backend/app/main.py:152-182; .planning/phases/09-regulatory-context/09-CONTEXT.md:7,27-29] |

## Project Constraints (from AGENTS.md)

No `./AGENTS.md` exists at the repository root, so there are no additional file-based directives to copy. [VERIFIED: project-root listing 2026-08-20] The phase must nevertheless preserve the embedded project guardrails supplied by the orchestrator: do not edit or delete unrelated user changes, do not modify Phase 10/frontend code, preserve API compatibility, keep PostgreSQL/SQLite qualification explicit, and do not commit or push from this research task. [VERIFIED: orchestrator task boundary; .planning/phases/09-regulatory-context/09-CONTEXT.md:7,27-29]

## Current HEAD and Repository Baseline

- `HEAD` is `529781c8120ad6f28067cb5f4e6a2501a7594747`, and `origin/main` resolves to the same commit; backend semantic files are clean. [VERIFIED: `git show-ref`/`git status` probe 2026-08-20]
- The working tree contains unrelated user changes, including `.planning/STATE.md`, frontend files, and untracked learning/demo artifacts; they must remain untouched. [VERIFIED: `git status --short --branch` probe 2026-08-20]
- Phase 8 is documented complete with 8 semantic/migration tests, 96 high-risk targeted tests, and 255 full-suite passes plus two unchanged Windows-only failures. [VERIFIED: .planning/phases/08-semantic-foundation/08-03-SUMMARY.md; .planning/phases/08-semantic-foundation/08-VERIFICATION.md:14-37]
- Re-running `python -m pytest -q tests/test_semantic_layer.py tests/test_semantic_migration.py` on this HEAD produced `8 passed in 19.43s`. [VERIFIED: test command probe 2026-08-20]
- `backend/local_main_test.db` is at Alembic revision `202608200015` and currently has one project but zero rows in `semantic_concepts`, `semantic_bindings`, and `semantic_relations`; migration tests still need to seed legacy Concept rows to prove bootstrap behavior. [VERIFIED: read-only SQLite probe 2026-08-20]
- `.planning/config.json` sets `workflow.research` and `workflow.nyquist_validation` to `false`, while `plan_check` and `verifier` are enabled. [VERIFIED: .planning/config.json:7-13]
- No `.planning/graphs/graph.json` exists, so no graph context was available for this research. [VERIFIED: graph-file probe 2026-08-20]

## Standard Stack

### Core

| Library / runtime | Verified version | Purpose | Why standard |
|---|---:|---|---|
| Python | 3.12.4 | Backend runtime and Alembic/pytest execution | The current backend runs on Python and the installed runtime is 3.12.4. [VERIFIED: runtime probe 2026-08-20] |
| FastAPI | 0.139.0 installed; `>=0.115,<1` declared | Project-aware API and Pydantic integration | Existing routers, dependencies, and `main.py` use FastAPI; no new web framework is needed. [VERIFIED: backend/requirements.txt:1; backend/app/api/semantic.py:1-36; runtime probe 2026-08-20] |
| Pydantic | 2.13.4 installed; supplied by current FastAPI stack | Strict versioned `RegulatoryContext`, facts, enums, and endpoint schemas | Phase 9 explicitly locks a versioned Pydantic contract and Phase 8 already uses Pydantic v2 `model_dump`/validators. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:20-21; backend/app/schemas/semantic.py:1-4,25-98; runtime probe 2026-08-20] |
| SQLAlchemy | 2.0.51 installed; `>=2,<3` declared | ORM models, batched collectors, portable predicates | Existing models use SQLAlchemy 2 mapped columns and all semantic services use `select`; retain that style. [VERIFIED: backend/requirements.txt:4; backend/app/models/semantic.py:1-6; backend/app/services/semantic/graph_service.py:1-8; runtime probe 2026-08-20] |
| Alembic | 1.18.5 installed; `>=1.13,<2` declared | `202608200016` schema/data migration and reversible lifecycle | Current head is `202608200015`, and its migration uses explicit `op.create_table`/indexes rather than `Base.metadata`. [VERIFIED: backend/requirements.txt:7; backend/alembic/versions/202608200015_regulatory_semantic_layer.py:7-17,27-126; runtime probe 2026-08-20] |
| pytest | 8.4.2 installed; `>=8,<9` declared | Focused semantic, contract, builder, migration, and regression tests | Phase 8 test fixtures use in-memory SQLite, `StaticPool`, TestClient, and `pytest` subprocess migration tests. [VERIFIED: backend/requirements.txt:23; backend/tests/conftest.py:1-31; backend/tests/test_semantic_layer.py:354-378; runtime probe 2026-08-20] |

### Supporting

| Dependency | Verified version / status | Purpose | When to use |
|---|---|---|---|
| SQLite | SQLite 3.45.3 | Fast unit/API fixtures and real Alembic upgrade/downgrade qualification | Run every semantic/context test and migration lifecycle locally. [VERIFIED: runtime probe; backend/tests/conftest.py:18-30] |
| psycopg | 3.3.4 installed; `psycopg[binary]>=3.1,<4` declared | PostgreSQL target dialect/runtime | Use for offline SQL compilation and staging/live migration qualification; no local server is available in this session. [VERIFIED: backend/requirements.txt:5; runtime probe 2026-08-20; .planning/STATE.md:52-56] |
| Existing `PermissionService` | In-repo service | Project membership, institution role, and permission checks | Every context/version read or write endpoint must call it; do not invent a second authorization layer. [VERIFIED: backend/app/services/auth/permission_service.py:47-99; backend/app/api/semantic.py:46,73,94,106] |
| Existing `AuditLog` / `record_audit` | In-repo service | Before/after mutation and governance provenance | Use for version/status changes and migration-independent writes; context build remains read-only. [VERIFIED: backend/app/services/governance/audit.py:37-72; backend/app/services/governance/workflow.py:435-455; .planning/phases/09-regulatory-context/09-CONTEXT.md:23,29] |
| Existing `HybridRetriever` | In-repo service | Optional knowledge/evidence retrieval with scope, confidentiality, scores, and RetrievalLog | Builder may use it as a candidate/evidence collector, but similarity remains `retrieved`, never `confirmed`. [VERIFIED: backend/app/services/retrieval/hybrid_retriever.py:18-67,151-257,302-318; .planning/phases/09-regulatory-context/09-CONTEXT.md:22,26] |

### Alternatives Considered

| Instead of | Could use | Decision / tradeoff |
|---|---|---|
| Existing adjacency table and bounded graph | Neo4j/GraphRAG | Do not add it: project requirements explicitly keep graph infrastructure out of Phase 9 and the current graph is bounded/deterministic. [VERIFIED: .planning/PROJECT.md:37-44; .planning/phases/09-regulatory-context/09-CONTEXT.md:7; backend/app/services/semantic/graph_service.py:15-67] |
| Pydantic contract over existing models | Unconstrained JSON snapshot | Do not use it: the locked contract requires typed `ContextFact` envelopes and bounded section value types, with no copied context store. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:20-23] |
| Identity-level Binding/Relation | Copy bindings or introduce temporal graph edges per version | Do not copy rows; D-12 retains Concept identity bindings and identity-level relations unless concrete evidence proves a version-limited binding is required. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:18,36] |
| Phase 9 ContextBuilder projection | Refactor generators now | Defer generator consumption to Phase 10; current generator-specific prompts/output contracts remain untouched in this phase. [VERIFIED: .planning/ROADMAP.md:26-32; .planning/phases/09-regulatory-context/09-CONTEXT.md:7] |

**Installation:** No new external package is recommended or installed for Phase 9; reuse the declared backend requirements. [VERIFIED: backend/requirements.txt:1-24]

## Package Legitimacy Audit

No new package install is part of this phase, so the package-legitimacy gate has no new candidates to approve or remove. The implementation should use the already declared FastAPI/Pydantic/SQLAlchemy/Alembic/pytest stack above rather than introducing a temporal, graph, retrieval, or validation package. [VERIFIED: backend/requirements.txt:1-24; .planning/PROJECT.md:37-44; ASSUMED: no new dependency is needed]

## Architecture Patterns

### System Architecture Diagram

```text
Caller (project_id + optional target/table/field/scenario/mart/concept + as_of)
        |
        v
Project-aware FastAPI read-only endpoint
  PermissionService: project membership + institution ownership
        |
        v
RegulatoryContextBuilder (orchestration only; no writes/copies)
  |-- Shared semantic status policy --> trusted confirmed OR explicit candidate mode
  |-- SemanticConceptVersion resolver --> one confirmed version for inclusive as_of
  |-- SemanticEntityAdapter registry --> stable descriptors for all 12 binding types
  |-- Batched collectors (IN/join/select-in)
  |     |-- Target/Source/Mart metadata + Scenario
  |     |-- Semantic bindings/relations + mapping rows/evidence
  |     |-- LineageNode/Edge and existing mapping lineage state
  |     |-- KnowledgeUnit + HybridRetriever visibility/confidentiality/RetrievalLog
  |     |-- HistoricalCaliber + deliverable snapshots where applicable
  |     v
  |  Authority/state/provenance normalization
  |  Deterministic candidate ranking
  |  Conflict + open-question detection (no silent winner)
        |
        v
Versioned Pydantic RegulatoryContext 1.0
  compact typed facts + references + conflicts/questions + build metadata
```

The entry point, processing stages, decision between trusted/candidate mode, existing service boundaries, and read-only output are prescribed by the locked Phase 9 decisions. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:8-29; ASSUMED: exact internal class names]

### Recommended Project Structure

```text
backend/app/
├── models/semantic.py                         # existing Concept/Binding/Relation + [ASSUMED] Version
├── schemas/semantic.py                        # existing additive semantic API schemas
├── schemas/regulatory_context.py              # [ASSUMED] typed ContextFact/RegulatoryContext contract
├── services/semantic/
│   ├── status_policy.py                       # [ASSUMED] one lifecycle visibility policy
│   ├── entity_adapter.py                      # [ASSUMED] explicit 12-type descriptor registry
│   ├── version_service.py                     # [ASSUMED] temporal selection/governance/projection
│   ├── context_authority.py                   # [ASSUMED] authority rank separate from state
│   ├── context_builder.py                     # [ASSUMED] orchestration only
│   ├── context_collectors.py                  # [ASSUMED] batched model collectors
│   └── context_conflicts.py                   # [ASSUMED] deterministic conflicts/questions
└── api/
    ├── semantic.py                            # existing routes + additive version fields/endpoints
    └── regulatory_context.py                  # [ASSUMED] additive read-only/debug route
```

The split keeps policy, adapters, versioning, orchestration, collectors, conflict detection, and question generation separable as required by the agent-discretion boundary; the new filenames are recommendations and need confirmation during planning. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:32-37; ASSUMED]

### Pattern 1: One Shared Semantic Status Policy

**Current evidence:** status filtering is duplicated and unsafe. `traverse()` defaults to `("confirmed", "draft", "ai_suggested")`; `entity_concepts()` and `_adjacent()` use `status != "deprecated"`; `resolve()` filters concepts with `status != "deprecated"`; API list routes apply a status predicate only when the caller supplies one. [VERIFIED: backend/app/services/semantic/graph_service.py:15-23,69-82,130-140; backend/app/services/semantic/resolver.py:33-42; backend/app/api/semantic.py:63-84,158-179,246-266]

**Use:** add one `[ASSUMED]` `status_policy.py` API consumed by graph, resolver, version service, and ContextBuilder. The API should expose a small mode vocabulary such as `[ASSUMED]` `trusted_statuses()`, `candidate_statuses()`, `audit_only_statuses()`, and `status_predicate(column, mode)`, with `trusted` returning only the locked value `confirmed`, candidate mode returning the locked values `confirmed`, `draft`, and `ai_suggested`, and audit-only values excluded from all trusted/candidate reads. Keep policy decisions centralized; callers must not pass ad-hoc tuples except through the policy. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:8-9; ASSUMED: exact function names]

**Required behavior:** rejected and deprecated concepts, bindings, relations, and versions are eligible only for explicitly named audit/history queries. A default entity semantics, graph, path, resolver, effective-version, or ContextBuilder query must never include them. Candidate mode may add drafts and AI suggestions but still excludes both audit-only statuses. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:8,43-44]

### Pattern 2: Explicit SemanticEntityAdapter Registry

`binding_service.py` already has an allow-list of exactly 12 model mappings. The source quote is: `"target_table": TargetTable`, `"target_field": TargetField`, `"mart_table": MartTable`, `"mart_field": MartField`, `"source_table": SourceTable`, `"source_field": SourceField`, `"scenario": ProductScenario`, `"knowledge_unit": KnowledgeUnit`, `"source_to_mart_mapping": SourceToMartMapping`, `"mart_to_ybt_mapping": MartToYbtMapping`, `"scenario_business_mapping": ScenarioBusinessMapping`, `"scenario_technical_lineage": ScenarioTechnicalLineage`. [VERIFIED: backend/app/services/semantic/binding_service.py:24-37]

The adapter should load through that registry, enforce project scope, and emit a plain stable descriptor such as `[ASSUMED]` `{entity_type, entity_id, project_id, code, name, aliases, semantic_text, metadata, source_refs}`. Resolver then receives the descriptor and ranks matches; it must not inspect ORM attributes through an expanding `getattr` chain. The descriptor is a projection, not a new database model. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:10,47; ASSUMED: descriptor field names]

#### Required mapping coverage

| Entity type | Explicit code/name fields | Explicit semantic/regulatory text | Stable metadata/source references |
|---|---|---|---|
| `target_table` | `table_code`, `table_name` | `description` | `project_id`, `id` [VERIFIED: backend/app/models/entities.py:50-60] |
| `target_field` | `field_code`, `field_name` | `field_definition`, `regulatory_description`, `regulatory_original_definition`, `regulatory_refined_definition`, `east_definition`, `internal_definition`, `remarks` | `target_table_id`, `field_type`, `data_category`, `data_format`, `report_name`, `report_field_name`, `project_id`, `id` [VERIFIED: backend/app/models/entities.py:63-86] |
| `mart_table` | `table_code`, `table_name` | `table_comment`, `description`, `subject_area` | physical database/schema/table fields, `project_id`, `id` [VERIFIED: backend/app/models/entities.py:140-157] |
| `mart_field` | `field_code`, `field_name` | `field_comment`, `description` | `mart_table_id`, `field_type`, `physical_column_name`, `project_id`, `id` [VERIFIED: backend/app/models/entities.py:160-174] |
| `source_table` | `table_code`, `table_name` | `table_comment`, `description` | `business_system_id`, database/schema/physical table fields, `project_id`, `id` [VERIFIED: backend/app/models/entities.py:105-121] |
| `source_field` | `field_code`, `field_name` | `field_comment`, `description` | `source_table_id`, `field_type`, `physical_column_name`, `project_id`, `id` [VERIFIED: backend/app/models/entities.py:124-137] |
| `scenario` (`ProductScenario`) | `scenario_code`, `scenario_name` | `description` | `scenario_type`, `business_owner`, `tech_owner`, `enabled`, `project_id`, `id` [VERIFIED: backend/app/models/entities.py:177-191] |
| `knowledge_unit` | `title`, target field/table codes and names, source names | `content`, `normalized_content`, `source_heading`, tags/metadata | `knowledge_type`, `knowledge_scope`, `institution_name`, `document_id`, `document_version_id`, `scenario_id`, `confidentiality_level`, `enabled`, `project_id`, `id` [VERIFIED: backend/app/models/entities.py:505-507] |
| `source_to_mart_mapping` | `mapping_name`, source system/table/field summaries | `business_rule`, `filter_condition`, `join_condition`, `priority_rule`, `merge_rule`, `code_mapping_rule`, `null_handling_rule`, `exception_rule`, `quality_check_rule`, `open_questions`, `final_content`, `ai_generated_content` | `mapping_status`, `mart_field_id`, `confidence_level`, `lineage_status`, `lineage_last_verified_at`, `project_id`, `id` [VERIFIED: backend/app/models/entities.py:336-365] |
| `mart_to_ybt_mapping` | `mapping_name`, mart table/field summaries | `business_rule`, `filter_condition`, `join_condition`, `code_mapping_rule`, `null_handling_rule`, `reporting_condition`, `validation_rule`, `open_questions`, `final_content`, `ai_generated_content` | `mapping_status`, `target_field_id`, `mart_field_id`, `confidence_level`, `lineage_status`, `lineage_last_verified_at`, `project_id`, `id` [VERIFIED: backend/app/models/entities.py:368-395] |
| `scenario_business_mapping` | `target_field_id`, `scenario_id`, `business_owner` | `business_definition`, `remarks`, `final_content`, `ai_generated_content`, `open_questions` | `business_confirm_status`, `confidence_level`, `project_id`, `id` [VERIFIED: backend/app/models/entities.py:193-217] |
| `scenario_technical_lineage` | `target_field_id`, `scenario_id`, source system/database/schema/table/field names | `processing_logic`, `remarks`, `final_content`, `ai_generated_content`, `open_questions` | `processing_logic_type`, `tech_confirm_status`, `lineage_status`, `lineage_last_verified_at`, `business_mapping_id`, `confidence_level`, `project_id`, `id` [VERIFIED: backend/app/models/entities.py:219-251] |

The source field vocabulary above is grounded in the model declarations: `TargetField` contains `field_definition`, `regulatory_description`, `regulatory_original_definition`, `regulatory_refined_definition`, `east_definition`, `internal_definition`, and `remarks`; the mapping classes contain their explicit rule/open-question/final-content fields; and `KnowledgeUnit` contains `content`, `normalized_content`, source location, target references, scope, confidentiality, and `enabled`. [VERIFIED: backend/app/models/entities.py:63-83,336-395,505-507]

### Pattern 3: Deterministic Resolver with Evidence, Not Confirmation

The current resolver scores exact code `1.0`, exact name `0.95`, alias `0.9`, metadata comment `0.75`, and confirmed binding `0.7`, then sorts by score and concept id; it therefore places confirmed binding below text matching. The exact source quote is: `if normalized_code ... return 1.0, "exact_code"`; `if normalized_name ... return 0.95, "exact_name"`; `if normalized_name ... in aliases ... return 0.9, "exact_alias"`; `if matched ... return 0.75, "metadata_comment"`; `if concept.id in confirmed_ids ... return 0.7, "confirmed_historical_binding"`. [VERIFIED: backend/app/services/semantic/resolver.py:59-77]

Implement the locked order as deterministic tiers: (1) confirmed binding, (2) exact normalized concept code, (3) exact canonical name, (4) exact alias, (5) regulatory text, (6) metadata/definition text. A candidate may combine evidence from several tiers, but its primary tier must be the highest matching tier and its final ordering must include stable tie-breakers such as normalized reason order and Concept id. Keyword, embedding, and LLM signals remain additive future candidates and cannot change lifecycle state. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:11-12; ASSUMED: integer tier implementation and tie-breaker details]

Every candidate must carry `semantic_concept_id`, deterministic score/tier, `match_reason`, a bounded evidence object, and provenance that identifies the descriptor entity type/id, source field, concept id/version, binding id/status, and retrieval/evidence references where applicable. The response status remains the locked value `ai_suggested`, even if evidence includes a confirmed binding; resolver output is a recommendation and never an auto-confirm operation. [VERIFIED: backend/app/schemas/semantic.py:248-254; .planning/phases/09-regulatory-context/09-CONTEXT.md:11-12]

Use adapter-produced fields only. Do not add more `getattr` fallbacks to `resolver.py`; the current sequence `field_code/table_code/scenario_code` and `field_name/table_name/scenario_name/title` misses mapping, knowledge, and scenario-specific text. [VERIFIED: backend/app/services/semantic/resolver.py:23-32,84-85; .planning/phases/09-regulatory-context/09-CONTEXT.md:10,56]

### Pattern 4: Stable Identity with Temporal Version Content

#### Final model choice

Keep the existing Concept identity constraint exactly as the source quote `UniqueConstraint("project_id", "concept_type", "concept_code", name="uq_semantic_concept_project_type_code")`; use a new `SemanticConceptVersion` table keyed by `semantic_concept_id` plus `version_no`, not by a duplicated `(project_id, concept_type, concept_code)` identity. [VERIFIED: backend/app/models/semantic.py:9-18; .planning/phases/09-regulatory-context/09-CONTEXT.md:13]

The new version row should be the canonical owner of versioned definition, description, aliases, domain, owner, provenance, source references, confidence/confirmation metadata, lifecycle status, `effective_from`, `effective_to`, and timestamps. `[ASSUMED]` Use a foreign key to Concept, `UniqueConstraint("semantic_concept_id", "version_no")`, a date-order check equivalent to `effective_to IS NULL OR effective_to >= effective_from`, and indexes on `(semantic_concept_id, status, effective_from, effective_to)` and `(project_id, semantic_concept_id)` for project-bounded reads. The exact new column names are a planning recommendation, not current in-repo values.

Effective dates are inclusive business dates. The exact selection rule is the locked quote `effective_from <= as_of` and `(effective_to is null or effective_to >= as_of)`; only confirmed rows participate, and one Concept must produce zero or one match. If a query returns more than one confirmed match, raise a deterministic temporal conflict rather than ordering away a data-integrity violation. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:15-16; ASSUMED: exception type and query implementation]

`draft` and `ai_suggested` versions may coexist and may overlap because they are review candidates, not trusted effective truth. A confirmed version cannot be patched in place; a changed meaning creates a new version and the old confirmed interval is closed or replaced through a governed transition. Rejected/deprecated versions never participate in effective-date resolution. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:16,45-46]

#### Database constraints versus service duties

- Portable database duties: foreign keys, non-null Concept identity, unique `(semantic_concept_id, version_no)`, date-order check, indexes, and ordinary status/source column constraints. [ASSUMED: exact constraint names]
- Service duties for both PostgreSQL and SQLite: normalize dates, enforce no overlap among confirmed intervals in one transaction, reject confirmed-row edits, enforce lifecycle transitions, and reject partial writes on conflict. Use a Concept-row lock on PostgreSQL and the database's serialized write transaction behavior on SQLite; add a dialect-specific PostgreSQL exclusion constraint only if staging proves it can be maintained without breaking SQLite migration parity. [ASSUMED: locking and optional exclusion implementation]
- Do not rely on `order_by(version_no.desc()).first()` to hide overlap. Conflict detection must return a machine-readable conflict/open-question result or reject the write. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:24; ASSUMED: error mapping]

#### Binding, relation, and legacy projection

SemanticBinding remains identity-level. Existing bindings are not copied for each version; add `semantic_concept_version_id` only if a concrete version-limited entity and test require it. Relations remain identity-level and the graph remains non-temporal in Phase 9. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:18,36]

Legacy Concept columns are a compatibility projection. The migration must populate one version from the current Concept row, then version create/confirm/deprecate/update services must update the projection in the same transaction from the canonical version; no API may independently edit both. Existing CRUD routes and response fields remain available, but version endpoints and current/latest effective fields are additive, and direct confirmed Concept PATCH must become a new version operation or a clear compatibility error. [VERIFIED: backend/app/api/semantic.py:98-120; backend/app/schemas/semantic.py:101-122; .planning/phases/09-regulatory-context/09-CONTEXT.md:14,27; ASSUMED: exact projection sync helper and endpoint names]

### Pattern 5: `202608200016` Additive Bootstrap Migration

The next revision must set `down_revision = "202608200015"`; the current head and prior migration chain establish that revision as the single semantic-layer head. [VERIFIED: backend/alembic/versions/202608200015_regulatory_semantic_layer.py:1-14; backend/tests/test_semantic_migration.py:11-14; `alembic heads` probe 2026-08-20]

Upgrade sequence:

1. Create `semantic_concept_versions` with explicit Alembic operations, portable SQLAlchemy types, foreign key to `semantic_concepts`, identity/version uniqueness, effective-date checks, and indexes. Do not import runtime models or use `Base.metadata` in the migration; the existing Phase 8 migration is tested for this property. [VERIFIED: backend/alembic/versions/202608200015_regulatory_semantic_layer.py:7-17,27-57; backend/tests/test_semantic_migration.py:30-35]
2. Read existing Concept rows using the migration bind and insert exactly one bootstrap version per row. Copy current definition/description/aliases/domain/owner/status/source/confidence/confirmation fields. Set bootstrap `version_no` to one, not the legacy Concept `version`, because the locked source states that a legacy `version > 1` is an edit counter and not recoverable history. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:17; backend/app/models/semantic.py:26-38; ASSUMED: exact bootstrap column list]
3. Use a documented deterministic bootstrap effective date. Recommended `[ASSUMED]` policy: use the row's existing `created_at` calendar date when present; if legacy data lacks it, use the migration's fixed release date and mark the row as a bootstrap projection in provenance. Do not fabricate earlier historical versions or treat the old edit counter as an effective version. This is the main open planning decision because D-11 specifies content/count but not a date.
4. Make the migration idempotent for a partially applied database only if it can prove the existing table/schema is complete; otherwise fail loudly like `202608200015` does for partial semantic schema. Never duplicate bootstrap rows on retry. [VERIFIED: backend/alembic/versions/202608200015_regulatory_semantic_layer.py:17-26; ASSUMED: idempotence guard details]

Downgrade must drop only `semantic_concept_versions` and its indexes/constraints, leaving `semantic_concepts`, bindings, relations, the formal `embedding_index_versions`, and all business data untouched. A round trip must be tested as empty→head, 015→head, head→015→head, and populated legacy Concept→head→015 with a deliberate assertion that the bootstrap version is removed only with the new table. [VERIFIED: backend/tests/test_semantic_migration.py:16-28; backend/alembic/versions/202608200015_regulatory_semantic_layer.py:126-130; ASSUMED: populated legacy case]

### Pattern 6: Projection-Only ContextBuilder

The builder reads existing `Target/Source/Mart`, `ProductScenario`, the three mapping/lineage entity families, `KnowledgeUnit`, `MappingEvidenceReference`, `LineageNode/Edge`, `HistoricalCaliberItem`, and version/snapshot tables; it does not create copied facts or a cache. [VERIFIED: backend/app/models/entities.py:50-249,336-456,459-514; backend/app/models/lineage.py:114-165; backend/app/models/deliverables.py:157-236; .planning/phases/09-regulatory-context/09-CONTEXT.md:23]

Collectors should accept a project id and bounded identifier sets, issue project/institution predicates in every query, batch with `IN`/joins/select-in, and return typed fact candidates. `context_builder.py` should orchestrate: scope normalization → semantic policy/version selection → adapter descriptors → metadata/mapping/lineage/knowledge/history collectors → authority/state/provenance normalization → deterministic ranking → conflicts/questions → Pydantic serialization. The orchestrator must not own every SQL query or become a God Service. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:23-29; ASSUMED: exact collector signatures]

#### Authority, state, provenance, and fact envelope

The contract must preserve the locked field vocabulary: `fact_type`, `structured value`, `authority`, `state`, `source type/id`, `evidence references`, `version/effective period`, `observed time`, and `confidence`. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:20-22]

Use separate `[ASSUMED]` serialized enums (exact names are discretionary) for:

- Authority rank, ordered from human-confirmed/formal regulatory, then confirmed semantic version, approved mapping, verified lineage, metadata, confirmed history, retrieved knowledge, and AI inference. Preserve both the rank and source type; do not let retrieval similarity rewrite rank. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:22]
- Lifecycle/fact state, which describes governance or observation state and is not a substitute for authority. A retrieved fact can be high-similarity but remains retrieved; an AI candidate remains inferred/ai-suggested until a human workflow changes the source row. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:8,12,22]
- Provenance, which must include project/institution scope, source model/type/id, version/effective dates, evidence ids/citations, retrieval log id where HybridRetriever was used, confidentiality level for knowledge, and observed timestamp. [VERIFIED: backend/app/services/retrieval/hybrid_retriever.py:205-257; backend/app/models/entities.py:505-507,560-582; .planning/phases/09-regulatory-context/09-CONTEXT.md:21,26]

Keep section value types bounded (for example, typed semantic/mapping/lineage/knowledge fact models or discriminated unions) rather than `dict[str, Any]` everywhere. This makes conflict comparison and API regression deterministic. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:20-21; ASSUMED: exact Pydantic discriminators]

#### Deterministic candidate, conflict, and open-question rules

Candidate Source/Mart collection should rank, in order, confirmed bindings/mappings; exact code/name; semantic evidence; metadata keywords; historical mappings; lineage neighborhood; and retrieval evidence. Always add a final stable key such as entity id/type, never rely on database natural order, and do not use the current generator pattern of `.limit(50)` as the builder's ranking algorithm. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:25; backend/app/services/mapping/source_to_mart_generator.py:98-110]

Emit deterministic machine-readable gaps for at least the locked cases: missing confirmed semantic binding/version, missing Source-to-Mart or Mart-to-YBT mapping, missing/stale lineage, missing evidence, historical-only definition, and conflicting authoritative facts. The acceptance example requires the exact source quote `MISSING_SOURCE_MAPPING`; conflicting current semantic and historical caliber facts must be a structured conflict rather than an inferred winner. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:24,49; ASSUMED: remaining conflict code names]

#### Retrieval, lineage, and confidentiality

`HybridRetriever.search()` already applies project/global/institution visibility and `KnowledgeUnit.enabled`, optionally filters knowledge type/scenario, returns confidentiality/source location/scores, and commits a `RetrievalLog` containing query/filter/result ids/latency. The builder should call it only through a collector that carries project/institution permissions and records the log id in provenance; similarity is evidence for a retrieved candidate, not confirmation. [VERIFIED: backend/app/services/retrieval/hybrid_retriever.py:22-67,151-257,302-318; backend/app/models/entities.py:505-507,560-561; .planning/phases/09-regulatory-context/09-CONTEXT.md:22,26]

Lineage must be reused, not copied. `LineageNode` already stores project/institution and source/mart/target entity ids; `LineageEdge` stores project/institution, source/target node ids, transformation rules, confidence/evidence, and enabled state. Scenario/mapping lineage status and `lineage_last_verified_at` are separate existing fields and should become facts or deterministic stale-lineage gaps. [VERIFIED: backend/app/models/lineage.py:114-165; backend/app/models/entities.py:219-251,336-365,368-395; .planning/phases/09-regulatory-context/09-CONTEXT.md:23-24]

Every query must constrain `project_id` and validate the owning Project/institution through `PermissionService`; do not trust client-supplied `institution_id`, free-text `institution_name`, or a source row's project without checking it against the requested project. Knowledge visibility may include global/institution rows only under the existing retriever policy, while semantic/mapping/lineage rows remain project-local. [VERIFIED: backend/app/models/entities.py:31-42; backend/app/services/auth/permission_service.py:84-99,147-195; backend/app/services/retrieval/hybrid_retriever.py:37-52,302-318; .planning/phases/09-regulatory-context/09-CONTEXT.md:26]

### Anti-Patterns to Avoid

- **Deprecated-only filtering:** `status != "deprecated"` admits rejected rows; replace with the shared trusted/candidate policy. [VERIFIED: backend/app/services/semantic/graph_service.py:77-80,138-140; backend/app/services/semantic/resolver.py:33-36]
- **Broad default graph traversal:** the current default includes drafts and AI suggestions; trusted business-fact paths must default to confirmed only. [VERIFIED: backend/app/services/semantic/graph_service.py:15-23; .planning/phases/09-regulatory-context/09-CONTEXT.md:8]
- **Resolver `getattr` accretion:** adding more fallback attributes keeps the ORM leak and still misses mapping/knowledge fields; use explicit adapter descriptors. [VERIFIED: backend/app/services/semantic/resolver.py:23-32; .planning/phases/09-regulatory-context/09-CONTEXT.md:10]
- **Version-as-edit-counter:** incrementing Concept.version and editing definition in place destroys temporal meaning; write immutable version rows and project legacy fields. [VERIFIED: backend/app/api/semantic.py:98-120; .planning/phases/09-regulatory-context/09-CONTEXT.md:13-17]
- **Copying context/lineage/mappings:** a snapshot/cache or duplicate graph would create a second fact source and violate the projection boundary. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:23,27-29]
- **Natural-order candidate limits:** a database `.limit(50)` without explicit scoring can omit the best candidate and is not deterministic across data plans. [VERIFIED: backend/app/services/mapping/source_to_mart_generator.py:98-110; .planning/phases/09-regulatory-context/09-CONTEXT.md:25]
- **Silent authority winner:** choosing one contradictory semantic/history/mapping fact without emitting a conflict makes the Context look confirmed when it is not. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:24,49]
- **ORM dump in prompts/contracts:** returning whole rows can leak fields and confidentiality; emit bounded typed values and references. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:20-23; backend/app/services/mapping/scenario_draft_generator.py:63-73]

## Don't Hand-Roll

| Problem | Don't build | Use instead | Why |
|---|---|---|---|
| Project/institution authorization | A Context-specific permission checker | Existing `PermissionService.require_project_permission()` plus project/institution checks | The existing service is the canonical permission set and visible-project boundary. [VERIFIED: backend/app/services/auth/permission_service.py:47-109,147-195] |
| Audit provenance | A second context audit table | Existing `record_audit`/`AuditLog` for mutations; read-only build metadata for context | Existing audit redacts sensitive keys and stores before/after/project/institution. [VERIFIED: backend/app/services/governance/audit.py:10-72] |
| Knowledge retrieval | Custom keyword/vector search or direct embedding calls | `HybridRetriever` with its visibility/confidentiality/RetrievalLog behavior | Existing retrieval already combines keyword/vector candidates and records source/score/log metadata. [VERIFIED: backend/app/services/retrieval/hybrid_retriever.py:18-32,151-257,302-318] |
| Semantic lifecycle filtering | Per-service status sets | One shared `[ASSUMED]` status policy API | Three current services already diverge; central policy is a locked decision. [VERIFIED: backend/app/services/semantic/graph_service.py:15-23,69-82,130-140; backend/app/services/semantic/resolver.py:33-42; .planning/phases/09-regulatory-context/09-CONTEXT.md:9] |
| Entity text discovery | More generic reflection or ORM dumps | Explicit `SemanticEntityAdapter` registry | Twelve binding target models have materially different fields, including regulatory/mapping/knowledge text. [VERIFIED: backend/app/services/semantic/binding_service.py:24-37; backend/app/models/entities.py:63-251,336-395,505-507] |
| Temporal overlap enforcement | “Pick latest row” or a custom in-memory history | Database date check plus transactional service overlap guard; optional PostgreSQL-specific constraint only with SQLite fallback | Confirmed periods must not overlap while both dialects remain supported. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:15-18; ASSUMED: implementation split] |
| Schema migration | `Base.metadata.create_all()` or runtime model imports | Explicit Alembic operations modeled on `202608200015` | Migration tests require runtime-model independence and reversible SQLite behavior. [VERIFIED: backend/alembic/versions/202608200015_regulatory_semantic_layer.py:7-17; backend/tests/test_semantic_migration.py:30-35] |

**Key insight:** Phase 9 is a governed projection seam. Custom copies, reflection, local status lists, and retrieval reimplementations would each create a second authority boundary and make CTX-02/CTX-04 impossible to prove. [VERIFIED: .planning/PROJECT.md:7-22; .planning/phases/09-regulatory-context/09-CONTEXT.md:8-29]

## Runtime State Inventory

This phase includes a schema/data migration and therefore requires an explicit runtime-state inventory. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:17]

| Category | Items found | Action required |
|---|---|---|
| Stored data | `backend/local_main_test.db` is at `202608200015` with one project and zero semantic Concept/Binding/Relation rows; production databases were not available. [VERIFIED: read-only SQLite probe 2026-08-20] | Migration must still handle deployed databases with existing Concept rows: one data-migration bootstrap version per Concept, no fabricated history, and an up/down test with `version > 1`. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:17; ASSUMED: deployed data shape beyond repository fixture] |
| Live service config | No external live semantic configuration was visible in the repository; no deployed UI/database/service was inspected. [VERIFIED: repository search 2026-08-20; LOW confidence for systems outside this checkout] | No code edit; planner must keep runtime/staging migration qualification explicit. |
| OS-registered state | No matching Windows Scheduled Task name/path for `semantic` or `regulatory` was found (or task enumeration was unavailable). [VERIFIED: `Get-ScheduledTask` probe 2026-08-20] | None for this schema migration; do not add a scheduled job. |
| Secrets/env vars | Only `backend/.env.example` is present; no semantic/version/context-specific environment key was found in repository env/scripts. [VERIFIED: backend env listing and `rg` probe 2026-08-20] | None; ContextBuilder must use existing DB/retrieval/runtime configuration and must not introduce a secret. |
| Build artifacts / installed packages | Existing `__pycache__` directories are non-authoritative Python caches; no semantic package or generated context artifact is installed. [VERIFIED: backend listing and requirements inspection 2026-08-20] | No data migration; ignore caches and keep source/migration files authoritative. |

## Common Pitfalls

### Pitfall 1: Rejected rows leak into trusted semantics

**What goes wrong:** Graph entity semantics, adjacent/path queries, resolver candidates, or Context facts include rejected data. [VERIFIED: backend/app/services/semantic/graph_service.py:69-82,130-140; backend/app/services/semantic/resolver.py:33-36]

**Why it happens:** Existing code treats deprecated as the only excluded status and traversal defaults to three statuses. [VERIFIED: backend/app/services/semantic/graph_service.py:15-23,77-80]

**How to avoid:** Route every lifecycle predicate through the shared policy; add tests for rejected/deprecated Concept, Binding, Relation, and Version in trusted, candidate, audit modes. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:8-9,43-44; ASSUMED: test names]

**Warning signs:** A trusted query's SQL contains `!= 'deprecated'`, a default status tuple with draft/AI values, or a candidate response contains a rejected id. [VERIFIED: current source lines above; ASSUMED: SQL inspection assertion]

### Pitfall 2: Resolver confidence contradicts governance

**What goes wrong:** Text match outranks a confirmed binding or a candidate appears confirmed. [VERIFIED: backend/app/services/semantic/resolver.py:59-77]

**Why it happens:** Current score order puts confirmed historical binding at `0.7` after metadata comment `0.75`, and response status is hard-coded `ai_suggested` without a provenance field. [VERIFIED: backend/app/services/semantic/resolver.py:70-77; backend/app/schemas/semantic.py:248-254]

**How to avoid:** Use integer/enum tiers, explicit evidence/provenance, stable tie-breakers, and no status mutation from resolver. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:11-12; ASSUMED: scoring representation]

### Pitfall 3: Adapter silently misses business text

**What goes wrong:** Target regulatory definitions, Mapping rules, KnowledgeUnit content, or Scenario fields are absent from resolver/context evidence. [VERIFIED: backend/app/models/entities.py:63-83,193-251,336-395,505-507]

**Why it happens:** Resolver currently reads only generic field/table/scenario/title attributes and does not know Mapping/Knowledge/Scenario-specific fields. [VERIFIED: backend/app/services/semantic/resolver.py:23-32; .planning/phases/09-regulatory-context/09-CONTEXT.md:56]

**How to avoid:** Implement and test one explicit descriptor adapter per the 12-value allow-list, with a stable descriptor contract and source field names. [VERIFIED: backend/app/services/semantic/binding_service.py:24-37; .planning/phases/09-regulatory-context/09-CONTEXT.md:10,47; ASSUMED: adapter class API]

### Pitfall 4: Legacy Concept fields become a second fact source

**What goes wrong:** A version row says one definition while a PATCH-ed Concept projection says another, or a confirmed row is edited in place. [VERIFIED: backend/app/api/semantic.py:98-120; .planning/phases/09-regulatory-context/09-CONTEXT.md:14,16]

**How to avoid:** Bootstrap one version, make version rows canonical, synchronize legacy fields transactionally, and route confirmed meaning changes through new version creation. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:13-17; ASSUMED: sync helper]

### Pitfall 5: Overlapping confirmed intervals are hidden

**What goes wrong:** `as_of` resolution returns whichever row happens to sort first, producing unstable regulatory meaning. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:15,24; ASSUMED: failure scenario]

**How to avoid:** Store inclusive date checks, transactionally reject confirmed overlap on both dialects, and raise/report a structured temporal conflict when existing bad data contains multiple matches. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:15-16,24; ASSUMED: service strategy]

### Pitfall 6: Migration manufactures history or breaks downgrade

**What goes wrong:** Old `SemanticConcept.version > 1` is treated as historical versions, bootstrap runs twice, or downgrade drops Phase 8 tables. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:17; backend/app/models/semantic.py:33; backend/alembic/versions/202608200015_regulatory_semantic_layer.py:126-130]

**How to avoid:** Always bootstrap exactly one `version_no=1`, guard duplicate table/row application, and test populated upgrade/down/up against 015. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:17; ASSUMED: migration guard details]

### Pitfall 7: Context leaks scope or confidential knowledge

**What goes wrong:** A project sees another project's binding, institution, mapping, or restricted knowledge. [VERIFIED: .planning/PROJECT.md:30-35; .planning/phases/09-regulatory-context/09-CONTEXT.md:26]

**How to avoid:** Apply project predicates and `PermissionService` to every collector, preserve `HybridRetriever` visibility/confidentiality/source/retrieval-log fields, and test two projects/two institutions with same codes. [VERIFIED: backend/app/services/auth/permission_service.py:84-99,147-195; backend/app/services/retrieval/hybrid_retriever.py:37-52,302-318; ASSUMED: fixture shape]

### Pitfall 8: N+1 and natural-order candidate retrieval

**What goes wrong:** The builder performs `db.get()` per binding/mapping/lineage row or truncates arbitrary Source/Mart rows before ranking, making latency and output unstable. [VERIFIED: backend/app/services/mapping/source_to_mart_generator.py:98-110; .planning/phases/09-regulatory-context/09-CONTEXT.md:25,28]

**How to avoid:** Collect ids first, batch `IN`/join/select-in reads, sort in Python by explicit ranking/tie-breaker, and add a SQLAlchemy query-count sanity test for a representative Context build. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:25,28; ASSUMED: instrumentation implementation and threshold]

### Pitfall 9: ContextBuilder mutates facts

**What goes wrong:** A read/debug build writes context snapshots, changes authoritative statuses, or silently adopts AI/retrieved text. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:23,29]

**How to avoid:** Use read-only collectors, return typed projection objects, and assert no row count/status/timestamp changes during API build tests. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:23,29; ASSUMED: test assertion]

## Code Examples

### Existing unsafe status query (grounding evidence)

```python
# Existing source: backend/app/services/semantic/graph_service.py:15-23, 44-49
def traverse(..., statuses: tuple[str, ...] = ("confirmed", "draft", "ai_suggested")):
    rows = select(SemanticRelation).where(
        SemanticRelation.project_id == self.project_id,
        SemanticRelation.status.in_(statuses),
    ).order_by(SemanticRelation.id)
```

The literal status values are the source-verified schema values `draft`, `ai_suggested`, `confirmed`, `rejected`, and `deprecated`. [VERIFIED: backend/app/schemas/semantic.py:7-9; backend/app/services/semantic/graph_service.py:22]

### Recommended policy seam (design skeleton)

```python
# [ASSUMED] proposed API; exact names are discretionary.
class SemanticStatusPolicy:
    def statuses_for(self, mode): ...
    def predicate(self, column, mode): ...
    def is_visible(self, status, mode): ...

# Graph, resolver, version service, and ContextBuilder call this seam.
rows = select(SemanticRelation).where(
    SemanticRelation.project_id == project_id,
    policy.predicate(SemanticRelation.status, mode),
)
```

The modes and allowed lifecycle values are constrained by the verbatim decision that trusted mode is `confirmed` only, candidate mode is `confirmed`, `draft`, and `ai_suggested`, and `rejected`/`deprecated` are audit/history-only. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:8-9]

### Recommended effective-version seam (design skeleton)

```python
# [ASSUMED] proposed service API; effective dates use the locked inclusive rule.
def resolve_effective_version(concept_id: int, as_of: date):
    matches = query_confirmed_versions(concept_id, as_of)
    if len(matches) > 1:
        raise TemporalConflict("overlapping confirmed periods")
    return matches[0] if matches else None
```

The locked selection expression is `effective_from <= as_of` and `(effective_to is null or effective_to >= as_of)`, with no overlap for confirmed periods. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:15-16]

### Recommended batched context collection (design skeleton)

```python
# [ASSUMED] collector shape; use explicit project predicates and stable ordering.
binding_rows = session.scalars(
    select(SemanticBinding).where(
        SemanticBinding.project_id == project_id,
        SemanticBinding.semantic_concept_id.in_(concept_ids),
    ).order_by(SemanticBinding.entity_type, SemanticBinding.entity_id, SemanticBinding.id)
).all()
```

The existing semantic indexes include project/entity/status and project/concept/status access paths, and the locked decision requires batch `IN`, joins, or select-in patterns. [VERIFIED: backend/app/models/semantic.py:43-50; .planning/phases/09-regulatory-context/09-CONTEXT.md:28]

## State of the Art

| Old/current approach | Phase 9 approach | When changed | Impact |
|---|---|---|---|
| `SemanticConcept.version` is incremented during Concept PATCH | Stable Concept identity plus canonical immutable date-effective Version rows | Phase 9, migration `202608200016` [ASSUMED: planned revision] | Effective-date meaning, overlap checks, and additive version APIs become representable without duplicating identity. [VERIFIED: backend/app/api/semantic.py:98-120; .planning/phases/09-regulatory-context/09-CONTEXT.md:13-17] |
| Each graph/resolver path owns a local status filter | One shared policy supplies trusted/candidate/audit visibility | Phase 9 hardening [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:8-10] | Rejected/deprecated contamination is removed consistently. |
| Resolver reads generic ORM attributes | Explicit adapters emit stable descriptors | Phase 9 hardening [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:10,47] | Mapping/Knowledge/Scenario domain text becomes visible without reflection growth. |
| Generator-specific independent context queries | Phase 9 provides a read-only projection; Phase 10 migrates generators | Phase 10 boundary [VERIFIED: .planning/ROADMAP.md:26-32; .planning/phases/09-regulatory-context/09-CONTEXT.md:7] | Existing generator APIs and task-specific prompts remain stable during Context contract rollout. |

**Deprecated/outdated:**

- Treating `rejected` as visible because only `deprecated` is filtered: unsafe under D-02. [VERIFIED: backend/app/services/semantic/graph_service.py:77-80,138-140; .planning/phases/09-regulatory-context/09-CONTEXT.md:8]
- Treating a high retrieval score as confirmation: prohibited because retrieval similarity cannot promote knowledge to confirmed. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:22]
- Using `Base.metadata` or runtime model imports in a data migration: the existing semantic migration tests explicitly reject this pattern. [VERIFIED: backend/tests/test_semantic_migration.py:30-35]

## Suggested Four-Plan Boundaries

| Plan | Scope and files | Dependencies | Exit evidence / main risk |
|---|---|---|---|
| **09-01 Semantic Hardening + temporal version migration** | Existing `backend/app/models/semantic.py`, `schemas/semantic.py`, `services/semantic/{__init__,binding_service,graph_service,resolver}.py`; new `[ASSUMED]` `status_policy.py`, `entity_adapter.py`, `version_service.py`; new Alembic `202608200016`; focused `test_semantic_layer.py` and `test_semantic_migration.py` additions or dedicated hardening tests. | None; must start from 015. | Standalone: rejected/deprecated never trusted; all 12 adapters descriptor-testable; confirmed binding ranks first; confirmed versions resolve by inclusive date; confirmed overlap/patch rejection is atomic; SQLite up/down/populated bootstrap passes. Main risks are migration bootstrap date, projection sync, and cross-dialect interval enforcement. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:8-18,43-49; ASSUMED: exact file split] |
| **09-02 RegulatoryContext Contract** | New `[ASSUMED]` `backend/app/schemas/regulatory_context.py` and `backend/app/services/semantic/context_authority.py`; contract/fact/authority/state/provenance/conflict/open-question tests. | 09-01 policy/version/adapter behavior. | Stable `context_schema_version = "1.0"`, bounded section types, deterministic serialization, separate authority/state, no ORM dumps, no persistence. Main risk is enum/shape churn; lock the contract before builder implementation. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:20-22,32-37; ASSUMED: module path] |
| **09-03 Projection ContextBuilder** | New `[ASSUMED]` `context_builder.py`, `context_collectors.py`, `context_conflicts.py`; fixture and builder tests. Reuse Metadata/Mapping/Knowledge/Evidence/HistoricalCaliber/Lineage/HybridRetriever. | 09-01 and 09-02. | Acceptance fixture returns project/date-effective facts, authority/state/provenance, candidates, conflicts and questions; missing mapping emits `MISSING_SOURCE_MAPPING`; no writes; query-count/N+1 sanity passes. Main risks are scope/confidentiality leaks, contradictory authority, and collector N+1. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:23-29,48-49; ASSUMED: module path] |
| **09-04 Additive API + regression qualification** | New `[ASSUMED]` `backend/app/api/regulatory_context.py`; additive version/current-effective routes in existing `backend/app/api/semantic.py`; `backend/app/main.py` registration; API, governance, isolation, migration and full regression tests. | 09-02 contract and 09-03 builder; 09-01 migration must be green. | Read-only project-aware/debug Context API; current Phase 8 routes unchanged; SQLite lifecycle and offline PostgreSQL compilation documented; full backend result compared to 247-pass/2-failure baseline. Main risk is route/auth compatibility and mis-scoping the API into Phase 10/frontend. [VERIFIED: backend/app/main.py:152-182; .planning/phases/08-semantic-foundation/08-VERIFICATION.md:27-37; ASSUMED: exact route names] |

Plan 09-01 must be independently executable and summarizable: it must not depend on the unimplemented ContextBuilder and must leave the existing context/generator/frontend surface unchanged. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:7,27-29; ASSUMED: plan execution order]

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|---|---|---|
| A1 | New modules will use the suggested `status_policy.py`, `entity_adapter.py`, `version_service.py`, `context_authority.py`, `context_builder.py`, `context_collectors.py`, and `context_conflicts.py` paths. [ASSUMED] | Architecture / plan boundaries | Planner may need to rename files while preserving separable responsibilities. |
| A2 | Bootstrap `effective_from` should derive from legacy `created_at` with a fixed-date fallback. [ASSUMED] | `202608200016` migration | Wrong date semantics can hide or expose a Concept for historical `as_of` queries; requires a locked decision before implementation. |
| A3 | Confirmed interval overlap will be enforced in a transaction at the service layer, with only portable date checks in the schema and optional PostgreSQL-specific strengthening. [ASSUMED] | Temporal model | Concurrency behavior differs by dialect; staging must qualify it. |
| A4 | Exact additive version/context endpoint paths and response field names are recommendations, not existing contracts. [ASSUMED] | API / four plans | Incorrect naming could break clients or require plan adjustment. |
| A5 | Authority/state/source vocabulary is fixed by the implemented 09-02 Contract: `AuthorityRank`, `FactState`, registered source types in `context_authority.py`, and `authority_for_source()` are the only builder vocabulary; every ContextFact fails closed on an unknown or mismatched source authority. Conflict/open-question codes remain the builder catalog required by D-18. [RESOLVED/VERIFIED: backend/app/services/semantic/context_authority.py; backend/app/schemas/regulatory_context.py; backend/tests/test_regulatory_context_contract.py] | Contract / builder | Executors must consume the Contract rather than create parallel enum or source vocabularies. |
| A6 | A representative Context build can be held to a bounded query-count budget after measurement; the numeric budget is not yet known. [ASSUMED] | Validation / performance | An arbitrary threshold could hide N+1 or over-constrain valid collector joins. |
| A7 | Live deployment state outside this checkout has no semantic scheduled task, secret, or context cache. [ASSUMED/LOW] | Runtime State Inventory | Production systems may require a separate migration/config audit. |

## Open Questions — Resolved for Planning

1. **Bootstrap effective date — RESOLVED.** Existing Concepts receive one bootstrap version whose `effective_from` is the calendar date of the legacy Concept's `created_at`. If that timestamp is absent, use the fixed migration release date `2026-08-20`. The row records bootstrap provenance; `version_no` is always `1`, regardless of the legacy edit counter. Tests cover dates before and on/after the bootstrap boundary. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:15-17; ASSUMED: fixed fallback selected for 09-01]

2. **Binding scope — RESOLVED.** Phase 9 bindings remain attached to stable `SemanticConcept` identity. No `semantic_concept_version_id` is added because current models, fixtures, and acceptance scenarios contain no concrete version-limited binding. A future additive FK requires separate evidence and migration. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:18,36; backend/tests/test_semantic_layer.py:67-103,313-351]

3. **Additive REST shape — RESOLVED.** Preserve all Phase 8 endpoints. Add project-scoped version routes under `/api/projects/{project_id}/semantic-concepts/{concept_id}/versions`; declare the static `/versions/effective` route before dynamic `/versions/{version_id}`. Add a read-only `GET /api/projects/{project_id}/regulatory-context` debug/build endpoint with typed query parameters. [VERIFIED: backend/app/api/semantic.py:39-84; backend/app/main.py:152-182; ASSUMED: additive paths selected for Phase 9]

4. **`reporting_period` semantics — RESOLVED.** It is an optional normalized label carried in scope/build metadata only. `as_of` remains the sole effective-date selector. Phase 9 adds no reporting-period table and never infers an authoritative date from the label. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:19; backend/app/models/entities.py:336-395; backend/app/models/deliverables.py:171-236]

5. **PostgreSQL qualification — RESOLVED.** Local execution must prove SQLite online lifecycle and isolated PostgreSQL SQL/dialect compatibility. Confirmed-interval creation locks the stable Concept row on PostgreSQL before the portable overlap check; SQLite relies on its serialized write transaction plus the same check. A live staging PostgreSQL migration and concurrent-overlap test is a documented pre-release gate, not a hidden local pass condition. [VERIFIED: environment probe 2026-08-20; .planning/STATE.md:52-56; ASSUMED: staging gate]

6. **Authority/state/source vocabulary — RESOLVED.** The completed 09-02 Contract is the sole authority: builders import its `AuthorityRank` and `FactState`, use only source types registered by `context_authority.py`, and derive each fact's authority with `authority_for_source(source_type)`. `RegulatoryKnowledgeItem` is source type `regulatory_knowledge_item` with regulatory authority and a non-confirmed state because its model has no governance status; HybridRetriever facts use source type `retrieved_knowledge`, retrieved authority/state, and RetrievalLog provenance. No parallel authority label or lifecycle state is introduced. [VERIFIED: backend/app/services/semantic/context_authority.py; backend/app/schemas/regulatory_context.py; backend/tests/test_regulatory_context_contract.py]

## Environment Availability

| Dependency | Required by | Available | Version / result | Fallback |
|---|---|---|---|---|
| Python | Backend, tests, Alembic | ✓ | 3.12.4 | — [VERIFIED: runtime probe 2026-08-20] |
| FastAPI/Pydantic/SQLAlchemy/Alembic/pytest | Implementation and tests | ✓ | 0.139.0 / 2.13.4 / 2.0.51 / 1.18.5 / 8.4.2 | — [VERIFIED: runtime probe 2026-08-20] |
| SQLite | Local migration and API tests | ✓ | SQLite 3.45.3; in-memory fixtures and `local_main_test.db` available | — [VERIFIED: runtime probe; backend/tests/conftest.py:18-30] |
| PostgreSQL client | Offline dialect qualification | ✓ | PostgreSQL tools 18.4; psycopg 3.3.4 | Use offline SQL compilation and document live qualification gap. [VERIFIED: runtime probe 2026-08-20] |
| PostgreSQL server | Live migration/concurrency qualification | ✗ | `127.0.0.1:5432 - no response` | Stage against PostgreSQL before release; not a local implementation blocker. [VERIFIED: `pg_isready` probe; ASSUMED: staging availability] |
| Docker | Optional local PostgreSQL service | ✗ | Command missing | Use installed SQLite/PostgreSQL CLI or external staging. [VERIFIED: command probe 2026-08-20] |
| Graph database / external retrieval service | Not required by Phase 9 | ✗/not applicable | Out of scope; existing bounded graph and HybridRetriever are reused | No fallback needed. [VERIFIED: .planning/PROJECT.md:37-44; .planning/phases/09-regulatory-context/09-CONTEXT.md:7,23] |

**Missing dependencies with no fallback:** None for local implementation; live PostgreSQL qualification remains an external release gate. [VERIFIED: environment probe 2026-08-20; ASSUMED: staging gate]

**Missing dependencies with fallback:** PostgreSQL server has SQLite/offline SQL fallback for development, but not for final production qualification. [VERIFIED: .planning/STATE.md:52-56]

## Validation Architecture

`workflow.nyquist_validation` is explicitly false, so this is a supplemental phase qualification map rather than a generated Nyquist gate. [VERIFIED: .planning/config.json:7-13]

### Test Framework

| Property | Value |
|---|---|
| Framework | pytest 8.4.2 installed; `pytest>=8,<9` declared. [VERIFIED: runtime probe; backend/requirements.txt:23] |
| Config file | No dedicated pytest config was found; shared fixtures are in `backend/tests/conftest.py`. [VERIFIED: backend/tests/conftest.py:1-31; repository file inventory 2026-08-20] |
| Quick run command | `cd backend; python -m pytest -q tests/test_semantic_layer.py tests/test_semantic_migration.py` — current result: 8 passed. [VERIFIED: test probe 2026-08-20] |
| Full suite command | `cd backend; python -m pytest -q` — compare to Phase 8 baseline of 255 passed and the two unchanged Windows failures. [VERIFIED: .planning/phases/08-semantic-foundation/08-VERIFICATION.md:27-37] |

### Phase Requirements → Test Map

| Req ID | Behavior | Test type | Automated command | File exists / planned gap |
|---|---|---|---|---|
| CTX-01 | Project/target/scenario/mart/concept inputs build stable Pydantic Context with `context_schema_version = "1.0"`. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:19-21] | Contract + API | `python -m pytest -q tests/test_regulatory_context_contract.py tests/test_regulatory_context_api.py -x` [ASSUMED: filenames] | New Wave 0/09-02 tests. |
| CTX-02 | Authority rank and lifecycle state serialize separately; confirmed/formal outrank lower authority and retrieval never confirms. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:21-22] | Unit + builder | `python -m pytest -q tests/test_regulatory_context_contract.py -k authority -x` [ASSUMED: test name] | New Wave 0/09-02 tests. |
| CTX-03 | Context aggregates semantic/mapping/knowledge/evidence/history/lineage references without persistence/copies. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:23] | Integration | `python -m pytest -q tests/test_regulatory_context_builder.py -k projection -x` [ASSUMED: filename/test] | New Wave 0/09-03 tests. |
| CTX-04 | Missing mapping/lineage/evidence, stale lineage, historical-only and contradictions produce stable conflicts/questions. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:24,49] | Integration + regression | `python -m pytest -q tests/test_regulatory_context_builder.py tests/test_semantic_hardening.py -k 'conflict or missing or rejected' -x` [ASSUMED: filenames/test names] | New Wave 0/09-01 and 09-03 tests. |

### Mandatory 09-01 hardening tests

- Extend or isolate `backend/tests/test_semantic_layer.py` to create rejected/deprecated Concept/Binding/Relation rows and assert trusted entity semantics, graph/path, resolver, and Context-facing policy exclude them while explicit candidate mode includes only the locked candidate statuses. [VERIFIED: existing test file and context acceptance lines; ASSUMED: test additions]
- Add adapter tests for all 12 allow-listed entity types, especially the real TargetField regulatory text, Source/Mart field comments/descriptions, all three mapping/lineage families, KnowledgeUnit content, and Scenario fields. [VERIFIED: backend/app/services/semantic/binding_service.py:24-37; backend/app/models/entities.py:63-251,336-395,505-507]
- Add resolver tests for confirmed-binding > code > name > alias > regulatory text > metadata/definition, stable ties, evidence/provenance, and no auto-confirm/LLM call. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:10-12]
- Add version tests for 2026 v1/2027 v2 `as_of` selection, inclusive end points, draft/AI coexistence, rejected/deprecated exclusion, overlap/confirmed immutability, atomic rejection, identity-level Binding/Relation, and legacy projection sync. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:15-18,43-46]

### Migration lifecycle and dialect qualification

1. SQLite: run `python -m pytest -q tests/test_semantic_migration.py -x` with empty→head, 015→head, head→015→head, and populated legacy Concept bootstrap cases; inspect unique/check/index definitions and ensure formal `embedding_index_versions` survives. [VERIFIED: backend/tests/test_semantic_migration.py:16-52; .planning/phases/08-semantic-foundation/08-VERIFICATION.md:22-23; ASSUMED: added populated case]
2. Offline PostgreSQL: compile the new revision's explicit Alembic operations for PostgreSQL and assert no SQLite-only SQL leaks; the full historical chain currently fails `alembic upgrade head --sql` at existing `202607070002` because it calls SQLAlchemy inspector on Alembic's MockConnection, so isolate/directly exercise the new revision or record this as a baseline limitation rather than misclassifying it as a 09-01 regression. [VERIFIED: `python -m alembic upgrade head --sql` probe 2026-08-20; backend/alembic/versions/202607070002_template_datasource_nl_task.py:12-18]
3. Live PostgreSQL: rerun the same lifecycle on a staging PostgreSQL instance, including confirmed-interval concurrency/overlap rejection, foreign keys, date checks, project/institution isolation, and API response compatibility. [VERIFIED: .planning/STATE.md:52-56; ASSUMED: staging checklist]

### Isolation, confidentiality, and performance

- Seed two institutions/projects with identical Concept codes, entity ids, mappings, and knowledge names; assert all Semantic/Context queries are project scoped and institution ownership is checked, while permitted knowledge scope behavior remains exactly the existing retriever policy. [VERIFIED: backend/app/services/auth/permission_service.py:84-99,147-195; backend/app/services/retrieval/hybrid_retriever.py:41-52,302-318; ASSUMED: fixture]
- Attach restricted/confidential KnowledgeUnits and assert Context preserves confidentiality/source/retrieval-log provenance and does not expose unauthorized content. [VERIFIED: backend/app/models/entities.py:505-507,560-582; backend/app/services/retrieval/hybrid_retriever.py:205-257; ASSUMED: test]
- Instrument `before_cursor_execute` or the existing SQLAlchemy engine event in a builder integration test, build the acceptance Context with multiple bindings/mappings/knowledge/lineage rows, and assert a measured bounded query count plus no per-row `db.get()` pattern. The exact threshold must be measured and then locked in the plan, not guessed here. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:28; ASSUMED: instrumentation/threshold]

### Baseline Windows failures to preserve

The existing baseline has two pre-existing Windows-only failures: ACL inspection returns `Protected=null`, and the interactive lifecycle script does not exit within its test timeout; Phase 8 recorded 247 passes before semantic work and the same two failures after it. They are not Phase 9 regressions unless their count/signature changes. [VERIFIED: .planning/STATE.md:52-56; .planning/phases/08-semantic-foundation/08-VERIFICATION.md:27-37]

## Security Domain

Security enforcement is enabled because `.planning/config.json` does not set `security_enforcement=false`. [VERIFIED: .planning/config.json:1-17; developer research contract]

### Applicable ASVS Categories

| ASVS category | Applies | Standard control |
|---|---|---|
| V2 Authentication | Yes for every Context/version API | Reuse `CurrentPrincipal`/secured router dependencies and `PermissionService`; do not add anonymous context access. [VERIFIED: backend/app/api/semantic.py:24-36; backend/app/main.py:152-182] |
| V3 Session Management | Yes | Preserve existing principal/session dependency chain and request-scoped permission checks; the builder itself must not bypass caller identity. [VERIFIED: backend/app/services/auth/permission_service.py:47-99; backend/app/api/semantic.py:39-46] |
| V4 Access Control | Yes, critical | Project path scope plus Project.institution ownership; every collector query has project predicates; no client-supplied institution override. [VERIFIED: backend/app/models/entities.py:31-42; backend/app/services/auth/permission_service.py:84-99,147-195; .planning/phases/09-regulatory-context/09-CONTEXT.md:26] |
| V5 Input Validation | Yes, critical | Pydantic `extra="forbid"`, allow-listed entity types, bounded limits, normalized codes, validated inclusive dates, and explicit `as_of`; never accept unconstrained fact JSON or raw ORM dumps. [VERIFIED: backend/app/schemas/semantic.py:25-59,125-176,238-246; .planning/phases/09-regulatory-context/09-CONTEXT.md:19-21] |
| V6 Cryptography | Indirect | No new crypto is needed; reuse existing security/redaction and never hand-roll token/encryption logic. Preserve knowledge confidentiality and audit redaction. [VERIFIED: backend/app/services/governance/audit.py:10-34; backend/requirements.txt:17-19; ASSUMED: no new cryptographic field]

### Known Threat Patterns for FastAPI + SQLAlchemy semantic context

| Pattern | STRIDE | Standard mitigation |
|---|---|---|
| Cross-project Concept/Binding/Mapping/Lineage read | Information disclosure | Project predicates, `PermissionService`, same-project entity validation, two-project tests. [VERIFIED: backend/app/services/semantic/binding_service.py:53-62; backend/app/services/auth/permission_service.py:84-99] |
| Cross-institution knowledge visibility | Information disclosure | Preserve current HybridRetriever scope rules and confidentiality/source/retrieval-log provenance; do not equate free-text institution name with ownership. [VERIFIED: backend/app/services/retrieval/hybrid_retriever.py:41-52,302-318; .planning/phases/09-regulatory-context/09-CONTEXT.md:26] |
| Rejected/AI fact treated as trusted | Tampering / repudiation | Shared policy, separate authority/state, human workflow for confirmation, audit rows, no resolver auto-confirm. [VERIFIED: backend/app/services/governance/workflow.py:60-109,435-455; .planning/phases/09-regulatory-context/09-CONTEXT.md:8-12,22] |
| Temporal overlap or confirmed in-place edit | Tampering | Date checks, transactional overlap guard, immutable confirmed version, deterministic conflict. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:15-18; ASSUMED: transaction implementation]
| ORM/reflection field leakage | Information disclosure | Explicit adapters and bounded Pydantic sections; do not serialize `__dict__`/whole models. [VERIFIED: backend/app/services/mapping/scenario_draft_generator.py:63-73; .planning/phases/09-regulatory-context/09-CONTEXT.md:10,20]
| N+1 / unbounded candidate query | Denial of service | Batch by ids, explicit limits after ranking, query-count test, no cache layer. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:25,28]

## Sources

### Primary (HIGH confidence)

- `.planning/phases/09-regulatory-context/09-CONTEXT.md:5-58` — locked scope, trusted policy, adapter/resolver rules, temporal semantics, Context contract, authority/state, projection boundary, isolation, performance, API behavior, and acceptance examples. [VERIFIED]
- `backend/app/models/semantic.py:9-94` — current Concept/Binding/Relation identity/status/version fields and constraints. [VERIFIED]
- `backend/app/schemas/semantic.py:7-18,101-257` — current literal vocabularies and API response/request shapes. [VERIFIED]
- `backend/app/services/semantic/{binding_service,graph_service,resolver}.py` — current 12-type registry, status contamination, graph defaults, generic resolver discovery, and score order. [VERIFIED]
- `backend/alembic/versions/202608200015_regulatory_semantic_layer.py:1-130` and `backend/tests/test_semantic_migration.py:16-52` — current Alembic head, additive migration idiom, and SQLite lifecycle tests. [VERIFIED]
- `backend/app/models/entities.py:31-251,336-514`, `backend/app/models/lineage.py:114-165`, and `backend/app/models/deliverables.py:157-236` — reusable metadata, mapping, knowledge, lineage, evidence, historical, and version/snapshot sources. [VERIFIED]
- `backend/app/services/retrieval/hybrid_retriever.py:18-318` — existing scope, confidentiality, retrieval provenance, ranking, and RetrievalLog behavior. [VERIFIED]
- `.planning/PROJECT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/STATE.md`, `.planning/codebase/REGULATORY-SEMANTIC-ASSESSMENT.md`, and all Phase 8 planning/summary/check/research/verification files — project constraints, requirement traceability, existing architecture, baseline and Phase 8 delivery evidence. [VERIFIED]

### Secondary (MEDIUM confidence)

- Runtime probes on 2026-08-20 for Python, installed library versions, SQLite/psycopg, PostgreSQL client/server availability, Alembic heads, targeted tests, and repository state. [VERIFIED: command probes]
- `backend/app/services/mapping/{source_to_mart_generator,mart_to_ybt_generator,scenario_draft_generator}.py` — current generator query/data-source boundaries used to fence Phase 10. [VERIFIED]

### Tertiary (LOW confidence)

- No external web/documentation sources were used because `.planning/config.json` explicitly disables research and this phase is grounded in the local repository. Proposed module names and the numeric query threshold remain implementation choices; bootstrap fallback, concurrency strategy, binding scope, reporting-period boundary, and REST shape are resolved planning decisions above. [VERIFIED: .planning/config.json:7-13; ASSUMED]

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — installed versions and declared dependency ranges were probed locally. [VERIFIED: backend/requirements.txt:1-24; runtime probes]
- Architecture: HIGH for current boundaries and locked decisions; MEDIUM for proposed new module paths and temporal service implementation. [VERIFIED: source files and 09-CONTEXT.md; ASSUMED]
- Pitfalls: HIGH — contamination, generic resolver fields, edit-counter versioning, project scope, and baseline behavior are directly evidenced. [VERIFIED: source files and Phase 8 verification]
- Migration: MEDIUM — current Alembic idiom and SQLite lifecycle are verified, but `202608200016` is not yet implemented and no live PostgreSQL service is available. [VERIFIED: backend/alembic/versions/202608200015_regulatory_semantic_layer.py; environment probe; ASSUMED]

**Research date:** 2026-08-20 [VERIFIED: runtime date]
**Valid until:** 2026-09-19 for repository-local architecture; re-check installed versions and PostgreSQL qualification before execution if the environment changes. [ASSUMED: validity window]

## RESEARCH COMPLETE

**Phase:** 09 - regulatory-context
**Confidence:** MEDIUM

### Key Findings

- Current graph/resolver trusted reads admit rejected rows and use divergent local status rules; 09-01 must centralize `confirmed` trusted versus explicit candidate policy before ContextBuilder. [VERIFIED: backend/app/services/semantic/graph_service.py:15-23,69-82,130-140; backend/app/services/semantic/resolver.py:33-42; .planning/phases/09-regulatory-context/09-CONTEXT.md:8-9]
- The existing 12-type Binding registry is the correct boundary, but resolver needs explicit adapters for real regulatory, mapping, knowledge, and scenario fields rather than more `getattr`. [VERIFIED: backend/app/services/semantic/binding_service.py:24-37; backend/app/services/semantic/resolver.py:23-32; backend/app/models/entities.py:63-251,336-395,505-507]
- `SemanticConcept.version` is only an edit counter; `202608200016` must bootstrap exactly one canonical version per Concept, keep identity-level Binding/Relation, and make inclusive effective-date resolution plus confirmed immutability explicit. [VERIFIED: backend/app/api/semantic.py:98-120; .planning/phases/09-regulatory-context/09-CONTEXT.md:13-18]
- ContextBuilder should be a read-only, batched projection over existing Metadata/Mapping/Knowledge/Evidence/Lineage/HistoricalCaliber models, with separate authority/state/provenance, deterministic conflicts/questions, confidentiality propagation, and query-count tests. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:20-29]
- Four plans are recommended: standalone 09-01 hardening/migration, 09-02 contract, 09-03 builder, and 09-04 additive API/regression; no Phase 10 generator/frontend work belongs here. [VERIFIED: .planning/phases/09-regulatory-context/09-CONTEXT.md:7,27-29; ASSUMED: exact plan filenames]

### File Created

`.planning/phases/09-regulatory-context/09-RESEARCH.md`

### Confidence Assessment

| Area | Level | Reason |
|---|---|---|
| Standard Stack | HIGH | Existing requirements and installed runtime versions were directly inspected. [VERIFIED: backend/requirements.txt:1-24; runtime probes] |
| Architecture | MEDIUM/HIGH | Current ownership and locked decisions are directly evidenced; new module/file names and temporal bootstrap implementation are recommendations. [VERIFIED: source files and 09-CONTEXT.md; ASSUMED] |
| Pitfalls | HIGH | Status contamination, resolver ordering/reflection, version edit counter, migration lifecycle, scope/confidentiality, and baseline failures are directly reproducible or documented. [VERIFIED: source files, targeted tests, Phase 8 verification] |

### Open Questions (RESOLVED)

No design or architecture questions remain. Authority/state/source vocabulary, bootstrap effective date, additive endpoint shapes, identity-level Binding, reporting-period semantics, and the local/staging PostgreSQL qualification split are resolved decisions. The numeric query-count budget is an execution-time measurement against the canonical fixture, not an open design question. [VERIFIED: backend/app/services/semantic/context_authority.py; backend/app/schemas/regulatory_context.py; see resolved decisions above]

### Ready for Planning

Research complete. Planner can now create PLAN.md files. [VERIFIED: all requested domains and evidence sections are present]
