# Phase 9 Context — Regulatory Context

<decisions>

## Locked Decisions

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

## Agent Discretion

- Exact module split under `backend/app/services/semantic/`, provided builder orchestration, collectors, policy, conflict detection and question generation remain separable and no God Service is created.
- Exact REST shapes for additive SemanticConceptVersion and RegulatoryContext endpoints, provided project scope and backward compatibility remain explicit.
- Whether an optional `semantic_concept_version_id` is added to Binding in Phase 9. Default is identity-only; add it only if current data or a concrete test proves version-specific binding is necessary.
- Exact enum member names for authority/state, provided their ranking and separation satisfy D-16 and serialization remains stable.

</decisions>

## Acceptance Examples

1. A rejected concept, binding or relation never appears in trusted entity semantics, resolver candidates, graph traversal/path or RegulatoryContext.
2. Explicit candidate mode may include `draft` and `ai_suggested`; it still excludes `rejected` and `deprecated`.
3. One Concept has confirmed v1 for 2026 and confirmed v2 from 2027. Resolution on `2026-06-30` returns v1 and on `2027-03-31` returns v2.
4. Confirming an overlapping version or patching a confirmed version is rejected without partial writes.
5. TargetField, SourceField, MartField, Mapping, KnowledgeUnit and Scenario descriptors expose their real domain text through explicit adapters.
6. Building context for `2.3 同业客户表 / 客户统一编号` returns project-isolated, date-effective facts with authority, state, provenance, conflicts, open questions and build metadata.
7. Missing confirmed source mapping creates `MISSING_SOURCE_MAPPING`; conflicting current semantic and historical caliber facts create a structured conflict instead of an inferred winner.

## Forensic Findings Entering Planning

- `SemanticGraphService.entity_concepts()` and `_adjacent()` currently use `status != "deprecated"`, so rejected rows contaminate trusted results.
- `SemanticGraphService.traverse()` defaults to confirmed plus draft/ai_suggested, which is unsafe for default business-fact queries.
- `SemanticResolver.resolve()` filters only deprecated concepts and therefore can recommend rejected concepts.
- `SemanticResolver` currently discovers entity text through a generic `getattr` sequence and misses many Mapping/Knowledge/Scenario fields.
- `SemanticConcept.version` is an edit counter. The Concept identity unique constraint prevents multiple rows with the same code and cannot represent effective-dated meaning.

