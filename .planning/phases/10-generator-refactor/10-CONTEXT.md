# Phase 10: Generator Refactor - Context

**Gathered:** 2026-08-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 10 migrates the existing Source-to-Mart, Mart-to-YBT, scenario-business, and scenario-technical draft generators to consume the verified Phase 9 `RegulatoryContext` as their sole shared-fact input. Existing generation APIs, task-specific instructions, structured outputs, AI-draft persistence, explicit adoption, governance, audit, and human `final_content` boundaries remain compatible. This phase does not redesign the Phase 9 contract, build frontend experiences, introduce a new reporting-period system, generate SQL, implement semantic impact, or add new fact stores.

</domain>

<decisions>
## Implementation Decisions

### Context Cutover and Failure Boundary

- **D-01 — Sole shared-fact entry:** After Phase 10, `RegulatoryContextBuilder` is the only production entry point for shared Metadata, Knowledge, Evidence, Historical, Lineage, Semantic, and cross-layer Mapping facts used by generators. A generator must not fill Context gaps by issuing its former ORM, `HybridRetriever`, or evidence queries.
- **D-02 — Fail closed on construction failure:** Authorization failure, ContextBuilder exception, invalid scope, or failed Context construction makes the generation request fail with a diagnosable error. Production code must not fall back to the legacy context-building path.
- **D-03 — Incomplete Context is business state:** A successfully built Context with missing facts is not a construction failure. The generator evaluates its typed gaps, conflicts, available facts, and readiness policy to decide whether a conservative draft is allowed.
- **D-04 — Task-local reads remain allowed:** Generators may directly load the mapping or scenario-lineage row currently being operated on and perform task-specific editability/status checks, output application, audit, commit, and refresh. These reads do not authorize reconstructing shared business context outside ContextBuilder.
- **D-05 — Shadow comparison only:** Legacy-vs-Context comparison may exist in tests or a non-authoritative shadow harness during migration. It must never become a production fallback or contribute competing facts to a generated draft.

### Effective Generation Date

- **D-06 — Backward-compatible `as_of`:** Generator services support an optional `as_of`; existing mapping-id-only API calls remain valid. Any API extension is additive and optional.
- **D-07 — Resolution priority:** Resolve the effective business date in this order: explicit `as_of`; an existing task/project regulatory reporting or effective date; an existing project default reporting date if the current model provides one; current business date only as the final fallback.
- **D-08 — Reuse existing time concepts:** Research and planning must first inspect existing project/task/reporting models. Phase 10 must not create a new `ReportingPeriod` persistence system merely to supply generator dates.
- **D-09 — Trace the resolved date:** The final `resolved_as_of` must appear in Context build metadata and generation audit/trace evidence so a later reviewer can explain which temporal semantic version governed the draft.

### Task-Specific Context Projection

- **D-10 — Three adapter families:** Use distinct Source-to-Mart, Mart-to-YBT, and Scenario Context adapters, or equivalent names matching the repository style. Scenario business and technical projections may share scenario infrastructure while retaining their different instructions and outputs.
- **D-11 — Typed deterministic projection:** Each adapter selects only task-relevant Context facts, sorts by authority, retains compact provenance references, compresses long text, includes applicable conflicts/open questions, and enforces deterministic prompt/token bounds.
- **D-12 — No full Context dump:** The complete `RegulatoryContext` remains available for audit and debugging but is not serialized wholesale into the model prompt.
- **D-13 — Preserve task differences:** Existing task-specific prompt runtime keys, instructions, `SourceToMartOutput`, `MartToYbtOutput`, `ScenarioBusinessOutput`, and `ScenarioTechnicalOutput` remain distinct. Phase 10 must not introduce a universal Generator or universal Prompt Adapter.

### Generation Readiness and Blocking

- **D-14 — Deterministic task-aware policy:** Adapters or a closely related generator policy produce a typed readiness result equivalent to `can_generate`, `confidence_cap`, `blocking_reasons`, and `warnings`. This is an internal Phase 10 projection/policy and must not require redesigning the verified Phase 9 `RegulatoryContext` contract.
- **D-15 — Non-blocking gaps:** Missing evidence, insufficient retrieved knowledge, some missing lineage, non-core unknown fields, and the mapping gap that the current generator exists to fill normally allow a conservative draft. They must create or preserve explicit open questions, cap confidence, use “待确认” where needed, and never authorize invented facts.
- **D-16 — Mapping-gap exception:** `MISSING_SOURCE_MAPPING` is not inherently blocking for Source-to-Mart generation, and `MISSING_MART_TO_YBT_MAPPING` is not inherently blocking for Mart-to-YBT generation. The readiness policy evaluates gaps relative to the current task.
- **D-17 — Blocking conditions:** Do not ask the model to adjudicate an unresolved conflict between high-authority confirmed/formal/approved facts when it affects the task's core field or rule. Missing/cross-project target identity, inability to resolve the task target, Context construction failure, and governance prohibition are also blocking. The caller receives diagnosable blocking reasons and no new usable AI draft is persisted.
- **D-18 — Governance remains final:** Generators only produce AI drafts. Existing human final content is never overwritten by generation; promotion remains the explicit adoption/review/governance workflow.
- **D-19 — Question preservation:** Context-derived deterministic questions are authoritative generation constraints. Generator output may add task-specific questions, but it must not erase existing human questions or Context questions; planning should use stable merge/dedup behavior and preserve source traceability as far as existing storage permits.

### Compatibility and Verification

- **D-20 — Existing API contract:** Existing `generate-draft` and `adopt-ai-draft` routes and response schemas remain compatible. Optional date input and diagnostic detail are additive only.
- **D-21 — Migration scope:** Phase 10 removes duplicated shared-context construction from the three generator modules, including natural-order source candidate lookup, independent knowledge retrieval, evidence normalization, historical lookup, and cross-layer summaries where Context already supplies them.
- **D-22 — Regression focus:** Tests must prove no legacy shared-fact fallback, correct temporal version selection, task-aware readiness, deterministic prompt projection, project/institution isolation, confidentiality, provenance/audit traceability, final-content preservation, and unchanged structured-output/API behavior.

### the agent's Discretion

- Exact adapter, projection, readiness, and date-resolver class/module names within the existing mapping-service style.
- Exact prompt character/token budgets and truncation markers, provided ordering, provenance retention, and truncation are deterministic and tested.
- Exact additive API shape for optional `as_of` and exact HTTP status/error schema for blocked generation, provided old calls remain valid, blocking is diagnosable, and no draft is mutated.
- Which existing reporting/effective-date field supplies each fallback tier after code research; absence of such a field must fall through rather than create new persistence.
- Exact audit payload field names for context schema version, context build time, `resolved_as_of`, fact/conflict/question counts, retrieval log ids, and readiness.
- Migration wave order among Source-to-Mart, Mart-to-YBT, and Scenario generators, provided all four task outputs are covered before Phase 10 verification.
- Shape of a test-only shadow comparison harness, if one is useful; it cannot influence production generation.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone and Phase Contracts

- `.planning/PROJECT.md` — Core value, compatibility, governance, evidence, isolation, and phase-scope constraints.
- `.planning/REQUIREMENTS.md` — GEN-01 through GEN-04 acceptance requirements.
- `.planning/ROADMAP.md` — Phase 10 goal and success criteria; later-phase boundaries.
- `.planning/STATE.md` — Current verified Phase 9 decisions, blockers, and Phase 10 planning position.
- `.planning/codebase/REGULATORY-SEMANTIC-ASSESSMENT.md` — Generator migration candidates, task-specific responsibilities, compatibility-sensitive tests, and architecture evidence.

### Locked Phase 9 Foundation

- `.planning/phases/09-regulatory-context/09-CONTEXT.md` — Locked Context, authority, state, temporal, candidate, conflict, and projection decisions.
- `.planning/phases/09-regulatory-context/09-VERIFICATION.md` — Verified behavior, query budgets, API isolation, temporal policy, and known release constraints.
- `.planning/phases/09-regulatory-context/09-SECURITY.md` — Closed threat register that Phase 10 integrations must preserve.
- `.planning/phases/09-regulatory-context/09-04-SUMMARY.md` — Canonical Context API and final regression/performance evidence.

### Runtime Contracts and Integration Points

- `backend/app/schemas/regulatory_context.py` — The verified Context request/response contract; do not redesign it for generator convenience.
- `backend/app/services/semantic/context_builder.py` — Sole shared-fact orchestration entry point.
- `backend/app/services/semantic/context_authority.py` — Machine-defined authority ordering and independent fact-state policy.
- `backend/app/services/semantic/status_policy.py` — Trusted/candidate/audit-only semantic visibility.
- `backend/app/services/semantic/context_conflicts.py` — Deterministic conflict and open-question codes consumed by readiness.
- `backend/app/services/mapping/source_to_mart_generator.py` — Existing Source-to-Mart task instructions, output application, and duplicated shared queries to migrate.
- `backend/app/services/mapping/mart_to_ybt_generator.py` — Existing Mart-to-YBT task instructions, upstream summary, output application, and duplicated shared queries to migrate.
- `backend/app/services/mapping/scenario_draft_generator.py` — Existing scenario business/technical generation, physical-field safeguards, audit, and duplicated retrieval.
- `backend/app/services/llm/structured_outputs.py` — Existing task-specific structured output schemas that remain stable.
- `backend/app/services/llm/prompt_runtime.py` — Existing confidentiality-aware prompt/runtime execution boundary.
- `backend/app/api/mapping_rules.py` — Existing mapping generate/adopt routes and response compatibility.
- `backend/app/api/scenario_mappings.py` — Existing scenario generate/adopt/governance routes and editability checks.

### Regression Contracts

- `backend/tests/test_double_layer_mapping.py` — Double-layer generation, manual-final preservation, explicit adoption, evidence, and response behavior.
- `backend/tests/test_scenario_traceability.py` — Scenario generation, adoption, knowledge, physical-source safety, and traceability behavior.
- `backend/tests/test_regulatory_context_builder.py` — Context aggregation, temporal, isolation, readiness inputs, ordering, and 21-query service budget.
- `backend/tests/test_regulatory_context_api.py` — Canonical API, isolation, bounded output, and 22-query HTTP budget.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `RegulatoryContextBuilder.build(request, authorized_project=...)`: already returns the governed, typed, project/institution-isolated projection needed by all generators.
- `RegulatoryContextRequest`: already supports target table/field, scenario, mart field, semantic concept, `as_of`, reporting label, mode, and candidate limits.
- `ContextFact`, authority policy, conflicts, and open questions: provide stable sorting, provenance, lifecycle, and gap signals for task adapters.
- Existing `SourceToMartOutput`, `MartToYbtOutput`, `ScenarioBusinessOutput`, and `ScenarioTechnicalOutput`: keep task outputs and validation separate.
- Existing `prepare_model_input` / `execute_runtime_chat`: retain confidentiality enforcement, runtime selection, structured output validation, and retrieval-log linkage.
- Existing adopt/review/governance routes: preserve the separation between generated draft and human final fact.

### Established Patterns

- Current generators load their task row, construct a task prompt, call the configured runtime with a task-specific Pydantic output, apply only returned draft fields, commit, and refresh.
- `final_content` survives draft generation; `ai_generated_content` changes only through generation and becomes final only through explicit adoption/review.
- Phase 9 Context facts are bounded, deterministically sorted, authority-ranked, provenance-carrying projections; retrieved evidence never becomes confirmed truth.
- ContextBuilder requires a permission-qualified Project and derives institution scope from it; Phase 10 must preserve that handoff rather than invent a second authorization interpretation.

### Integration Points

- Replace `_source_candidates`, `_source_to_mart_summary`, direct `MappingEvidenceReference` normalization, and direct `HybridRetriever.search` prompt construction with task adapters over one Context build.
- Preserve mapping/scenario row selection and editability checks before applying generated output.
- Feed adapter projections into the existing prompt-runtime boundary, not into a new LLM subsystem.
- Extend generation audit metadata with Context version/date/provenance/readiness without changing authoritative mapping status semantics.
- Add focused generator integration tests alongside existing double-layer and scenario traceability suites, then run Phase 9 Context regressions to prevent contract drift.

</code_context>

<specifics>
## Specific Ideas

- Intended flow: `RegulatoryContext -> task-specific adapter -> typed deterministic prompt projection -> task-specific instruction -> structured output`.
- Intended ownership: ContextBuilder supplies shared governed facts; adapters select task facts; generators execute tasks; the LLM suggests drafts; governance determines formal truth.
- Readiness shape may be equivalent to `can_generate`, `confidence_cap`, `blocking_reasons`, and `warnings` without adding fields to the Phase 9 public Context schema.
- Canonical blocking example: a formal rule requires institutional-customer data from ECIF while an approved/confirmed current rule requires CRM, both govern the same core task fact, and authority/effective date cannot resolve the contradiction. That goes to a human; the local 27B must not guess.

</specifics>

<deferred>
## Deferred Ideas

- Frontend presentation and semantic catalog/workspace changes remain Phase 11+.
- Full SQL Generator remains a future requirement outside Phase 10.
- Semantic Impact propagation remains Phase 15.
- A new persistent ReportingPeriod system is not introduced in Phase 10; revisit only through a separately scoped requirement if existing date models prove insufficient.

</deferred>

---

*Phase: 10-Generator Refactor*
*Context gathered: 2026-08-23*
