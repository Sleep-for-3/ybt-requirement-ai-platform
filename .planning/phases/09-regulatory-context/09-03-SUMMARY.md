---
phase: 09-regulatory-context
plan: "03"
subsystem: backend-semantic
tags: [regulatory-context, sqlalchemy, lineage, retrieval, deterministic-ranking, tdd]
dependency-graph:
  requires:
    - phase: 09-regulatory-context
      provides: RegulatoryContext contract and registered source-authority policy from 09-02
  provides:
    - Authorized projection-only RegulatoryContextBuilder
    - Batched governed source collectors with real lineage predicates
    - Deterministic conflicts, open questions, candidate ranking, and bounded query behavior
  affects: [09-04-regulatory-context-api, 10-generator-refactor]
tech-stack:
  added: []
  patterns:
    - Projection-only builder over an already authorized Project
    - Registered source types resolved through authority_for_source
    - Explicit seven-tier candidate ranking before result caps
    - Batched collection with measured constant-query growth
key-files:
  created:
    - backend/app/services/semantic/context_builder.py
    - backend/app/services/semantic/context_collectors.py
    - backend/app/services/semantic/context_conflicts.py
    - backend/tests/test_regulatory_context_builder.py
  modified:
    - backend/app/services/semantic/__init__.py
    - backend/tests/test_semantic_layer.py
key-decisions:
  - RegulatoryContextBuilder accepts only a PermissionService-authorized Project and derives institution scope only from that object.
  - Raw lineage and persisted mapping/scenario lineage retain separate verification predicates based only on real model fields.
  - Candidate ranking uses seven explicit tiers and applies caps only after a stable full sort; the acceptance fixture budget is 21 SQL statements.
patterns-established:
  - Every emitted fact has a registered source_type and authority_for_source-derived authority.
  - Volatile retrieval metadata is normalized separately from deterministic domain content comparisons.
requirements-completed: []
status: complete
metrics:
  duration: 39m
  completed: 2026-08-23
actuals:
  tokens: 32749
  tasks: 3
  commits: 7
---

# Phase 9 Plan 03: Regulatory Context Builder Summary

An authorized, projection-only RegulatoryContextBuilder now aggregates governed semantic, mapping, lineage, knowledge, history, and retrieval evidence into deterministic contract output with a measured constant query budget.

## Performance

- **Duration:** 39 minutes
- **Started:** 2026-08-22T16:14:17Z
- **Completed:** 2026-08-22T16:53:16Z
- **Tasks:** 3
- **Files changed:** 6
- **Realized diff estimate:** 32,749 tokens (130,994 characters / 4)

## Accomplishments

- Added the required `RegulatoryContextBuilder(db).build(request, authorized_project=project)` seam, rejecting project mismatches before any collector runs and preserving projection-only transaction behavior.
- Aggregated the four mapping families, semantic evidence, raw and persisted lineage, project regulatory knowledge, retriever-visible knowledge, and history without crossing project or institution boundaries.
- Produced deterministic conflicts and open questions from the revised real lineage predicates, including missing, stale, historical-only, evidence, and authoritative-conflict cases.
- Locked candidate ordering to seven explicit tiers with stable type/id tie-breaking and caps applied only after full ranking.
- Measured identical 21-statement query counts for baseline and growth fixtures while returning 41 facts in the growth case.
- Repaired the date-sensitive semantic regression test by deriving `as_of` from the listed v1 `effective_from`; no production temporal semantics changed.

## Task Commits

Each task followed RED then GREEN and was committed atomically:

1. **Date-sensitive semantic test debt**
   - `0fca99c` — test(09-03): stabilize semantic version effective-date regression
2. **Task 1: Trace the acceptance target through one projection-only context build**
   - `aeadf95` — RED: test(09-03): add failing context builder tracer
   - `53f519f` — GREEN: feat(09-03): implement authorized context builder tracer
3. **Task 2: Add batched source-family collectors and deterministic conflict/open-question detection**
   - `757015c` — RED: test(09-03): add failing context aggregation cases
   - `614f056` — GREEN: feat(09-03): aggregate governed context sources
4. **Task 3: Lock candidate ranking, spec-less non-emission, confidentiality, and measured query performance**
   - `77e3707` — RED: test(09-03): add failing ranking and query budget cases
   - `9c2c223` — GREEN: feat(09-03): rank bounded context candidates

## Files Created/Modified

- `backend/app/services/semantic/context_builder.py` — Authorized builder orchestration, project guard, deterministic assembly, and projection-only behavior.
- `backend/app/services/semantic/context_collectors.py` — Batched collection across governed source families, real lineage predicates, retrieval linkage, and ranked candidates.
- `backend/app/services/semantic/context_conflicts.py` — Stable conflict and open-question derivation.
- `backend/app/services/semantic/__init__.py` — Lazy builder export that preserves the existing semantic package import graph.
- `backend/tests/test_regulatory_context_builder.py` — Fourteen integration and regression tests covering CTX-01 through CTX-04 builder behavior without marking the phase requirements complete.
- `backend/tests/test_semantic_layer.py` — Date-stable v1 effective-date regression fixture.

## Decisions Made

- The builder trusts only the caller-provided authorized Project. It never accepts institution identity from request input or performs a second, potentially divergent authorization lookup.
- Raw lineage is verified only when the edge is enabled, both nodes resolve, confidence is high, the script is enabled, and its version equals `current_version_no`.
- Mapping/scenario lineage is verified only from persisted `lineage_status == "verified"` plus its real timestamp; ScenarioBusiness emits no invented lineage claim.
- `RegulatoryKnowledgeItem` remains project-only. `KnowledgeUnit` visibility remains delegated to HybridRetriever and carries retrieval log, confidentiality, and source metadata into the returned facts.
- Candidate ordering is `(tier, source_type, source_id)` across confirmed binding/mapping, exact code/name, semantic evidence, metadata keyword, historical mapping, lineage neighborhood, and retrieval evidence tiers.

## Query Budget Evidence

| Fixture | SQL statements | Returned facts |
| --- | ---: | ---: |
| Baseline acceptance context | 21 | bounded acceptance result |
| Growth fixture | 21 | 41 |

Keyword-only knowledge retrieval performs zero `Session.get` calls; the separately qualified vector hydration probe performs one. No per-row refresh growth remains after retrieval logging commits.

## Verification

- `python -m pytest -q tests/test_regulatory_context_builder.py` — **14 passed**
- `python -m pytest -q tests/test_regulatory_context_contract.py tests/test_semantic_layer.py tests/test_regulatory_context_builder.py` — **41 passed in 29.97s**
- `python -m compileall -q app` — **passed**
- Query measurement probe — **BASELINE=21, GROWTH=21, FACTS=41**
- Base-to-HEAD scope audit — only the six permitted backend/test files changed; immutable contract and authority modules have no diff.
- Prohibition audit — no frontend, API route, migration, generator, cache, snapshot, context persistence, or new-table implementation was introduced.
- Persistence audit — builder/collectors do not call `add` or `commit`; only the existing HybridRetriever writes its expected RetrievalLog.

## Coverage Map

| Deliverable | Test evidence | Result |
| --- | --- | --- |
| Authorized, date-effective, project/institution-isolated builder | Acceptance tracer, mismatch-before-collector, projection-only, repeat-build, and two-project/two-institution tests | Passing |
| Governed collectors and deterministic gaps/conflicts | Mapping/lineage/history/knowledge aggregation, source authority, real-predicate, and missing/stale/conflict tests | Passing |
| Ranked candidates, confidentiality, spec-less non-emission, and bounded performance | Ranking/cap, spec-less metadata, query-count, retriever boundary, and volatile-normalization tests | Passing |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Preserved the semantic package import graph with a lazy builder export**

- **Found during:** Task 1 GREEN
- **Issue:** Eagerly importing the builder from `semantic.__init__` introduced a circular import through existing model/service modules.
- **Fix:** Exposed `RegulatoryContextBuilder` through module-level `__getattr__`, retaining the public import while deferring the dependency until requested.
- **Files modified:** `backend/app/services/semantic/__init__.py`
- **Commit:** `53f519f`

No architectural or scope deviations were made.

## Issues Encountered

- Context7 documentation lookup reached its quota and the documented `ctx7` CLI fallback was not installed. No dependency installation was attempted; implementation used the repository's pinned APIs, authoritative contract files, and plan references.

## TDD Gate Compliance

- Task 1 RED failed on the missing builder module; GREEN passed 4 tracer tests.
- Task 2 RED produced 5 expected aggregation failures with 1 passing guard; GREEN passed the 6 selected aggregation tests and all 10 builder tests then present.
- Task 3 RED produced 2 expected failures (missing ranked candidates and 24 statements over the 21-statement budget); GREEN passed all 5 selected tests and all 14 builder tests.
- RED commits precede their corresponding GREEN commits for every behavior-adding task.

## Known Stubs

None. The changed files contain no TODO, FIXME, placeholder, skipped test, or runtime spec-less fallback.

## Remaining 09-04 Boundary

Plan 09-03 intentionally stops at the builder/service boundary. Plan 09-04 remains responsible for the API wiring and phase-level completion checks. Phase 9 and CTX-01 through CTX-04 remain incomplete until that plan succeeds.

## Self-Check: PASSED

All four created files and all seven implementation/TDD commits were found. Verification, scope, immutability, persistence, query-budget, and prohibition claims were confirmed before state advancement.
