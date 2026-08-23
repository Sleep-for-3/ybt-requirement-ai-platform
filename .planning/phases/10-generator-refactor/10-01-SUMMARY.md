---
phase: 10-generator-refactor
plan: 01
subsystem: ai-generation
tags: [regulatory-context, pydantic, sqlalchemy, generator-adapters, provenance, tdd]

requires:
  - phase: 09-regulatory-context
    provides: canonical authorized RegulatoryContext projection, authority/state policy, conflicts, questions, provenance, and fixed-cost collectors
provides:
  - one authorized candidate-mode Context build as the sole production shared-fact seam for generators
  - four typed bounded zero-I/O task projections across three adapter families
  - deterministic readiness, question merge, confidence cap, and physical-output safety policies
  - project-scoped Mart and evidence/verified-lineage-connected CatalogColumn metadata projection
affects: [10-02 source-to-mart cutover, 10-03 mart-to-ybt cutover, 10-04 scenario cutover]

actuals:
  tokens: 28752
  tasks: 3
  commits: 6

tech-stack:
  added: []
  patterns:
    - build one candidate RegulatoryContext after Project authorization and before any pure adapter
    - serialize immutable per-family task and Project snapshots through explicit fields only
    - project only bounded typed facts with authority, state, provenance, and confidentiality
    - admit new physical identifiers only from exact Context allow-list tuples or unchanged current values

key-files:
  created:
    - backend/app/services/mapping/generator_context.py
    - backend/app/services/mapping/context_adapters.py
    - backend/app/services/mapping/generation_readiness.py
    - backend/tests/test_generator_context_adapters.py
  modified:
    - backend/app/services/semantic/context_collectors.py
    - backend/tests/test_regulatory_context_builder.py

key-decisions:
  - "Shared RegulatoryContext remains the only shared-fact seam: construction is exactly once in candidate mode and any builder/scope error propagates without a legacy fallback."
  - "Generation dates resolve from explicit as_of, otherwise an injected current business date; timestamps and text labels never become reporting dates."
  - "CatalogColumn metadata is emitted only for enabled same-project ids connected through in-scope Scenario technical evidence or already verified scoped lineage, with one fixed enrichment query."
  - "Question merge preserves existing human text byte-for-byte, then appends stable Context and model-only segments while confidence and physical fields are capped before mutation."

patterns-established:
  - "Generator snapshot boundary: explicit frozen Principal + immutable task/Project snapshot + one provenance-stamped Context projection."
  - "Physical safety boundary: exact normalized database/schema/table/column tuple from Context or the unchanged canonical task tuple."
  - "Question provenance markers: [CTX:<question_code>] for governed additions and [AI] for validated model-only additions."

requirements-completed: []

coverage:
  - id: D1
    description: "Authorized Source-to-Mart generation resolves date, builds one candidate Context, projects bounded facts, and evaluates task-aware readiness without a legacy fact path."
    requirement: GEN-01
    verification:
      - kind: integration
        ref: "backend/tests/test_generator_context_adapters.py#test_source_to_mart_tracer_builds_one_candidate_context_and_bounded_projection"
        status: pass
    human_judgment: false
  - id: D2
    description: "Mart-to-YBT consumes approved Source-to-Mart Context rule_text and never promotes a draft/final/AI fallback into the upstream chain."
    requirement: GEN-02
    verification:
      - kind: integration
        ref: "backend/tests/test_generator_context_adapters.py#test_all_four_task_projections_are_distinct_and_mart_uses_approved_context_rule_only"
        status: pass
    human_judgment: false
  - id: D3
    description: "Scenario business and technical projections remain task-distinct, preserve governance state, and enforce exact physical identifier evidence."
    requirement: GEN-03
    verification:
      - kind: integration
        ref: "backend/tests/test_generator_context_adapters.py#test_sparse_output_policy_caps_confidence_and_omits_unknown_physical_and_governance_fields"
        status: pass
    human_judgment: false
  - id: D4
    description: "Sparse evidence deterministically caps confidence, preserves human questions, appends provenance-marked additions, and never invents formal or physical state."
    requirement: GEN-04
    verification:
      - kind: integration
        ref: "backend/tests/test_generator_context_adapters.py#test_question_merge_preserves_human_bytes_and_is_stable_deduplicated_and_idempotent"
        status: pass
    human_judgment: false

duration: 45min
completed: 2026-08-23
status: complete
---

# Phase 10 Plan 1: Generator Context Foundation Summary

**One authorized candidate-mode RegulatoryContext seam now drives four deterministic generator projections with immutable identity/scope snapshots, bounded metadata, stable questions, confidence caps, and exact physical-source safety.**

## Performance

- **Duration:** 45 min
- **Started:** 2026-08-23T06:25:00Z
- **Completed:** 2026-08-23T07:10:00Z
- **Tasks:** 3
- **Delivery files modified:** 6

## Accomplishments

- Established the shared generator orchestration seam: validate the complete frozen `Principal`, compare immutable Project/task snapshots, resolve an auditable business date, build one `ContextMode.CANDIDATE` RegulatoryContext, and invoke only a pure typed adapter.
- Added frozen explicit snapshots and bounded projections for Source-to-Mart, Mart-to-YBT, Scenario business, and Scenario technical work without ORM dumps, whole-Context serialization, shared-fact side queries, or legacy fallback.
- Extended the existing Context `metadata` section with deterministic MartField/MartTable descriptors and a maximum of 50 enabled same-project CatalogColumn descriptors connected only by in-scope evidence or verified lineage.
- Proved that connected catalog enrichment costs one fixed query and remains constant while Mart, Catalog, evidence, and lineage row volume grows; adapters execute zero SQL.
- Added strict readiness, confidence normalization/capping, byte-preserving idempotent question merge, governance-field omission, exact physical tuple allow-listing, and content-free output trace summaries.

## Task Commits

Each task followed a RED/GREEN pair and was committed atomically:

1. **Task 1 RED: authorized generator Context tracer contracts** — `8da5784` (test)
2. **Task 1 GREEN: one-build Source-to-Mart seam** — `ce66f7a` (feat)
3. **Task 2 RED: Mart/Catalog enrichment and query contracts** — `801ff79` (test)
4. **Task 2 GREEN: bounded governed metadata enrichment** — `2129498` (feat)
5. **Task 3 RED: multi-adapter and output safety contracts** — `69e7f76` (test)
6. **Task 3 GREEN: all typed adapters and safety policies** — `d42f12b` (feat)

**Plan metadata:** committed separately after state and roadmap updates.

## Files Created/Modified

- `backend/app/services/mapping/generator_context.py` — frozen identity/snapshots, effective date resolution, one Context build, scope routing, stale diagnostics, and redacted trace envelope.
- `backend/app/services/mapping/context_adapters.py` — four bounded task projections, Mart upstream rule selection, physical coverage/allow-list, safe model-output filter, and redacted output trace.
- `backend/app/services/mapping/generation_readiness.py` — task-aware block/warning matrix, confidence cap, and stable byte-preserving question merge.
- `backend/app/services/semantic/context_collectors.py` — Mart descriptors and bounded evidence/verified-lineage-connected CatalogColumn metadata.
- `backend/tests/test_generator_context_adapters.py` — nine RED-first identity, date, build, adapter, readiness, question, confidentiality, physical, and trace contracts.
- `backend/tests/test_regulatory_context_builder.py` — Mart/Catalog isolation, exact metadata, fixed query delta, row-growth, and listener-cleanup regressions.

## Verification Evidence

| Scope | Result |
| --- | --- |
| Generator Context/adapters | 9 passed in 8.06s |
| RegulatoryContext builder + HTTP API | 60 passed in 44.71s |
| Task 2 Mart/Catalog/physical/query selection | 4 passed in 7.65s |
| `python -m compileall -q app` | PASS, exit 0 |
| Forbidden mapping-module imports/static seam review | PASS |

The unchanged pre-enrichment comparison budgets remain 21 builder statements and 22 HTTP statements. A connected CatalogColumn projection adds exactly one builder statement; the count stays fixed after Mart, Catalog, evidence, and verified-lineage growth.

## Decisions Made

- Kept `RegulatoryContextBuilder` as the sole shared-fact owner. Generator orchestration performs identity checks and one canonical build but never queries MappingEvidence, Metadata, Knowledge, or Lineage facts itself.
- Kept time semantics narrow: explicit `as_of` wins, otherwise the injected current business date is recorded as `current_business_date`; no ReportingPeriod store or timestamp inference was added.
- Used candidate mode so adapters can label draft/AI lifecycle state, while readiness and output filtering prevent those candidates from becoming authoritative facts or formal governance state.
- Selected Mart-to-YBT upstream rules only from approved Source-to-Mart `MappingContextValue.rule_text`, ordered by the existing authority policy and source id.
- Preserved human question text as the exact first segment, using normalized Unicode whitespace/case keys only for later duplicate prevention.
- Treated the complete current Scenario technical physical tuple as an allowed unchanged value; any new tuple must exactly match a Context-projected CatalogColumn tuple.

## Deviations from Plan

None - plan executed exactly as written.

## TDD Gate Compliance

- Task 1 RED `8da5784` failed on the absent generator adapter module, followed by GREEN `ce66f7a` with five tracer tests passing.
- Task 2 RED `801ff79` failed on absent physical coverage helpers, followed by GREEN `2129498` with four selected metadata/query tests passing.
- Task 3 RED `69e7f76` failed on absent Mart/Scenario adapters, followed by GREEN `d42f12b` with all nine adapter tests passing.

## Issues Encountered

None beyond the three expected RED failures. No authentication, dependency, service, or checkpoint gate was encountered.

## Authentication Gates

None.

## Known Stubs

None. Stub-pattern matches were limited to intentional local accumulators, optional values, and empty policy results; no placeholder flows to a UI or prevents the plan goal.

## User Setup Required

None.

## Remaining Risks / Next Phase Readiness

- Plans 10-02 through 10-04 must still cut the existing production generators over to this seam and implement the fresh short Project-to-task re-lock/revalidation immediately before each atomic draft mutation.
- The foundation intentionally does not change existing generator endpoints or persistence behavior yet, and it does not implement SQL Generator, Semantic Impact, DataQualityExpectation, frontend work, or a Phase 9 redesign.
- GEN-01 through GEN-04 remain open until all four Phase 10 plans and phase verification prove end-to-end governed writes.

## Self-Check: PASSED

- All six delivery files and this summary exist.
- Commits `8da5784`, `ce66f7a`, `801ff79`, `2129498`, `69e7f76`, and `d42f12b` are present in history.
- All task commits contain no tracked file deletion, and no frontend or unrelated untracked material is included.

---
*Phase: 10-generator-refactor*
*Completed: 2026-08-23*
