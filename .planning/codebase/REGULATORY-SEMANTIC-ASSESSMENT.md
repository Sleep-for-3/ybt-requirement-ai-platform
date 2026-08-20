# Regulatory Semantic Layer — Codebase Assessment

**Date:** 2026-08-20
**Baseline:** `21715fd114475cd879ac7896f26d12a6dfe85e4d`
**Method:** GSD forensic audit plus direct inspection of SQLAlchemy models, Alembic migrations, FastAPI routers, services, generators, frontend routes and tests.

## Existing / Partial / Missing / Duplication Risk

| Capability | Finding | Evidence | V2 treatment |
|------------|---------|----------|--------------|
| Metadata assets | Existing | `entities.py` contains BusinessSystem, Source/Mart/Target tables and fields; catalog/profiling services already exist | Reuse as binding targets |
| Scenario and mappings | Existing | ScenarioBusinessMapping, ScenarioTechnicalLineage, SourceToMartMapping, MartToYbtMapping store draft/final/status/rules | Bind, do not migrate or replace |
| Knowledge and evidence | Existing | KnowledgeUnit, KnowledgeEntityLink, MappingEvidenceReference, HybridRetriever | Reuse as evidence and context inputs |
| Vector governance | Existing but different responsibility | `202607300014_formal_semantic_index.py` and EmbeddingIndexVersion manage provider/model/dimension/collection/corpus hash | Keep unchanged; never rename as business semantics |
| Business semantic objects | Missing | No versioned first-class business term/metric/rule object exists | Add SemanticConcept |
| Concept-to-entity relationship | Partial | KnowledgeEntityLink connects only KnowledgeUnit to loose entity references | Add governed SemanticBinding; retain KnowledgeEntityLink |
| Concept ontology | Missing | No concept-to-concept adjacency model | Add SemanticRelation |
| Unified context | Missing | Each generator independently queries models, evidence and HybridRetriever | Add RegulatoryContextBuilder in Phase 9 |
| Technical lineage | Existing | `models/lineage.py` and lineage services already implement nodes, edges, resolution, diff and impact | Connect through bindings, never duplicate |
| Governance/review/audit | Existing | PermissionService, ReviewTask/Decision, workflow service and AuditLog | Extend target types and audit actions |
| Deliverables | Existing/partial | DeliverableFieldItem and package version snapshots already support structured projections | Evolve snapshot composer; keep renderer services |
| Quality rules | Partial | quality_check_rule and validation_rule are text fields | Add DataQualityExpectation only after semantic stability |

## Architecture Questions

### 1. Which current models can directly become SemanticBinding targets?

The first supported allow-list is: `TargetTable`, `TargetField`, `MartTable`, `MartField`, `SourceTable`, `SourceField`, `ProductScenario`, `KnowledgeUnit`, `SourceToMartMapping`, `MartToYbtMapping`, `ScenarioBusinessMapping`, and `ScenarioTechnicalLineage`. Every one has `project_id` directly. The service must map each `entity_type` to the SQLAlchemy class, load the row, and reject a project mismatch before insert. `BusinessSystem`, `RegulatoryKnowledgeItem`, `LineageNode`, and `LineageEdge` are valid later extensions, but are not needed for the first acceptance slice.

Evidence: `backend/app/models/entities.py:50`, `:63`, `:89`, `:105`, `:124`, `:140`, `:160`, `:177`, `:193`, `:219`, `:335`, `:367`, `:504`; `backend/app/models/lineage.py`.

### 2. Which existing fields already carry part of the semantic responsibility?

`TargetField.field_definition`, regulatory original/refined/description, EAST/internal definitions and report names hold semantic text. Source/Mart `field_name`, `field_comment`, `description` and physical names carry terminology. Scenario mappings and both mapping layers hold business rules, filters, joins, code/null rules, final content, confidence and questions. RegulatoryKnowledgeItem and KnowledgeUnit carry regulation/historical meaning. These remain source facts and display content; the new concept layer references them instead of copying them.

### 3. Which current models have overlapping meaning and should be bound instead of migrated?

Target/Source/Mart fields may describe the same “客户统一编号” with different technical names; scenario business versus technical lineage describe the same field in different scopes; Source→Mart and Mart→YBT split one end-to-end mapping; RegulatoryKnowledgeItem/KnowledgeUnit may describe the same rule; KnowledgeEntityLink may already connect a unit to a field. None should be collapsed. A SemanticConcept supplies identity, while bindings keep each model's existing lifecycle and API intact.

### 4. What is the minimum stable RegulatoryContextBuilder schema?

Phase 9 should define: `scope`, `target`, `scenario`, `semantic_concepts`, `semantic_bindings`, `semantic_relations`, `regulatory_rules`, `mart_candidates`, `source_candidates`, `confirmed_mappings`, `technical_lineage`, `knowledge_evidence`, `historical_calibers`, `quality_rules`, `conflicts`, `open_questions`, and `build_metadata`. Every fact item needs `authority`, `state`, `source_type`, `source_id`, optional `evidence_ids`, and `observed_at/version`. It must return references plus compact prompt-ready summaries, not copies of whole ORM rows.

### 5. Which Mapping Generator DB queries should migrate to ContextBuilder?

Shared target/mart/source entity loading, scenario loading, confirmed mapping summaries, semantic bindings/relations, KnowledgeUnit retrieval, evidence normalization, historical caliber lookup, verified lineage and open-question aggregation belong in ContextBuilder. Current duplicated `HybridRetriever.search(...)`, target/mart table loading and cross-layer mapping summaries in `source_to_mart_generator.py`, `mart_to_ybt_generator.py`, and `scenario_draft_generator.py` are the main migration candidates.

### 6. Which queries are task-specific and should remain in generators?

Selecting the mapping row being mutated, loading its task-specific editable fields, formatting the exact SourceToMartOutput/MartToYbtOutput instruction, applying structured output, raw-SQL rejection, and writing draft/audit logs remain generator responsibilities. Source→Mart's capped source candidate presentation and Mart→YBT's specific upstream summary can use Context data but their ranking/formatting is task-adapter logic.

### 7. Should SemanticConcept be project-, institution-, or global-scoped?

First release is project-scoped with non-null `project_id` and denormalized nullable `institution_id` copied from Project for isolation/indexing. Unique identity is `(project_id, concept_type, concept_code)`. Institution/global publishing is deferred because existing KnowledgeUnit, mappings and lineage are project-scoped, and shared edits would require version publication, ownership and conflict governance not currently present.

### 8. How does Knowledge scope align with Semantic scope?

KnowledgeDocument/Unit currently use project_id plus `knowledge_scope` and `institution_name` strings. Semantic bindings always require the KnowledgeUnit's project to equal the concept project. Institution alignment comes from the owning Project, not the free-text institution_name. An institution-scoped knowledge document may be ingested into multiple projects later, producing project-local bindings; Phase 8 does not reinterpret or migrate existing knowledge scope.

### 9. How can limited graph traversal remain efficient without a graph DB?

Use indexed adjacency rows on `(project_id, source_concept_id, relation_type, status)` and `(project_id, target_concept_id, relation_type, status)`. GraphService performs breadth-first traversal with a hard `max_depth <= 5`, visited-set cycle prevention, batched `IN (...)` frontier queries and deterministic order. Path lookup stops at a configurable node cap. PostgreSQL recursive CTE can be benchmarked later without changing the model/API.

### 10. How should LineageNode connect to SemanticConcept without copying lineage?

LineageNode already points to source/mart/target catalog entities. Bind concepts to those canonical entities; semantic impact follows LineageNode/Edge to the referenced entity and then resolves SemanticBinding. A later optional `lineage_node` binding type can cover unresolved/derived nodes, but no second node/edge store is created.

### 11. How can Deliverables become a Structured Requirement renderer?

DeliverablePackage, DeliverableFieldItem, DeliverableEvidenceItem, PendingQuestion and DeliverablePackageVersion.content_snapshot_json already provide a snapshot boundary. Phase 12 should compose a versioned StructuredRequirementSnapshot from semantic references, mappings, evidence, lineage, questions, quality and governance, then feed existing workbook/document renderers. Rendered bytes or Markdown never write back as authoritative facts.

### 12. Which frontend routes can be reused and which are new?

Reuse `/workspace`, field/scenario detail pages, `/lineage`, `/impact-analyses`, `/deliverables`, `/knowledge`, `/projects`, `/datasources`, `/catalog`, `/mart`, `/target-tables`, `/review-tasks` and current AppShell/tokens. Add `/semantics` and `/semantics/[id]`; later reshape `/workspace` tabs and dashboard without deleting legacy routes.

### 13. Which APIs must remain compatible with the old frontend?

All existing project, target field/table, scenario mapping, Source→Mart, Mart→YBT, batch generation/job, evidence, questions, deliverable/export, knowledge and lineage endpoints. Generator refactoring must preserve response schemas and draft/final semantics. New semantic APIs are additive under project-aware paths; `main.py` adds a router without moving existing registrations.

### 14. Which current tests are most regression-sensitive?

`test_double_layer_mapping.py`, `test_scenario_traceability.py`, `test_knowledge_rag.py`, `test_hybrid_retriever.py`, `test_semantic_retrieval_security.py`, `test_embedding_index_version.py`, `test_sql_lineage.py`, `test_governance.py`, `test_deliverables.py`, `test_productization.py`, migration tests and frontend workspace view-model tests. The highest risk is model import/migration breakage, project-scope leaks, generator output drift and accidental confusion with embedding index semantics.

### 15. How should trustworthy Semantic/Mapping/Lineage Coverage be defined?

- **Eligible population:** active TargetFields in the selected project/target table, excluding explicitly disabled/out-of-scope rows when such status exists.
- **Semantic coverage:** eligible fields with at least one `confirmed` binding to a non-deprecated concept; AI suggestions do not count.
- **Mapping coverage:** eligible fields with approved/confirmed Mart→YBT plus a connected approved/confirmed Source→Mart path; partial layers are reported separately.
- **Lineage coverage:** eligible fields whose bound/linked target node has a verified path to at least one mart/source node and whose lineage status is not stale/unresolved.
- Every API returns numerator, denominator, percentage-or-null, eligibility rules, as-of timestamp and excluded counts. Empty denominator yields `null`, not 0% or 100%.

## Phase 8 Scope Fence

Phase 8 adds only the semantic models, migration, schemas, CRUD/query/status APIs, binding validation, deterministic resolver foundation, bounded graph service, governance/audit integration and tests. It does not change generators, prompt construction, ContextBuilder, frontend, coverage dashboard, quality model or impact analyzer.

## Validation Baseline

- Alembic heads: `202607300014 (head)`.
- Frontend tests: 26/26 passed.
- Frontend TypeScript: passed.
- Backend baseline: 247 passed, 2 Windows-only productization tests failed. Failures are environmental/launcher behavior (`Get-Acl` returned `Protected=null`; `项目启停.ps1` did not exit within the test timeout) and occur before Phase 8 code changes. Post-change semantic and full-suite results must be compared against this exact baseline.
