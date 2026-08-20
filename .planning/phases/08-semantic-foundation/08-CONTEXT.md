# Phase 8 Context — Semantic Foundation

<decisions>

## Locked Decisions

- **D-01 Scope:** SemanticConcept, Binding and Relation are project-scoped and institution-aware. `project_id` is non-null; `institution_id` is copied from the owning Project and may be null only for legacy projects without an institution.
- **D-02 Identity:** Concept uniqueness is `(project_id, concept_type, concept_code)`. Codes are trimmed and normalized consistently by the service; names are not globally unique.
- **D-03 Types:** Initial concept types are `business_term`, `metric`, `dimension`, `code_set`, `business_rule`, `regulatory_rule`.
- **D-04 Governance:** Initial statuses are `draft`, `ai_suggested`, `confirmed`, `rejected`, `deprecated`. AI-created records cannot start confirmed. Confirm/reject/deprecate actions are explicit, permission checked and audited.
- **D-05 Reuse:** No existing Target/Source/Mart, Scenario, Mapping, Knowledge, Lineage, Governance or vector-index models are renamed, moved or duplicated.
- **D-06 Binding:** Binding uses an allow-listed `entity_type` and integer `entity_id`; BindingService validates the target exists and belongs to the same project before persistence.
- **D-07 Relations:** Relation rows are project-local directed adjacency edges; self-relations and duplicate triples are rejected.
- **D-08 Graph:** Traversal is bounded BFS with cycle prevention, deterministic ordering, depth at most 5 and node cap; no graph database or new infrastructure.
- **D-09 Compatibility:** Semantic API is additive. Existing routes, generator behavior and frontend contracts do not change in this phase.
- **D-10 Database:** Alembic revision follows `202607300014`, supports PostgreSQL and SQLite, preserves all existing data and provides downgrade.
- **D-11 Resolver:** Deterministic resolution orders exact code, exact name, alias, metadata comment and confirmed historical binding before keyword/embedding; LLM inference is not called in Phase 8.
- **D-12 Phase fence:** ContextBuilder, generator migration, frontend, dashboard metrics, DataQualityExpectation and semantic impact are later phases.

## Agent Discretion

- Exact semantic API path naming, provided project scope remains explicit and router conventions match current FastAPI code.
- Whether aliases use a small JSON list attribute on SemanticConcept; aliases are attributes, not relationship storage.
- Internal helper/module decomposition inside `backend/app/services/semantic/`.

</decisions>

## Acceptance Examples

1. Create `客户`, `同业客户`, `客户统一编号`, `客户类型` in one project.
2. Add `同业客户 is_a 客户`, `同业客户 identified_by 客户统一编号`, and `同业客户 classified_by 客户类型`.
3. Bind `客户统一编号` to one TargetField, MartField, SourceField and KnowledgeUnit in that project.
4. Query neighbors, upstream/downstream, entity semantics and a bounded path.
5. Attempt cross-project binding, duplicate concept/relation and AI-confirmed creation; each is rejected without partial writes.

