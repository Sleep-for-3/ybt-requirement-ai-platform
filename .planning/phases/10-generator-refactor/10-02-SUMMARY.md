---
phase: 10-generator-refactor
plan: 02
subsystem: ai-generation
tags: [regulatory-context, source-to-mart, mart-to-ybt, authorization, optimistic-concurrency, tdd]

requires:
  - phase: 10-generator-refactor/10-01
    provides: frozen Principal and task/Project snapshots, one-build Context seam, typed adapters, readiness, question merge, confidence caps, and redacted traces
  - phase: 09-regulatory-context
    provides: authorized temporal RegulatoryContext, authority/state lifecycle, provenance, conflicts, questions, and fixed-cost collectors
provides:
  - production Source-to-Mart generation driven only by one authorized candidate-mode RegulatoryContext projection
  - production Mart-to-YBT generation with approved upstream Source-to-Mart rule_text frozen inside that same Context projection
  - no-long-lock optimistic writes with fresh actor validation, PermissionService authorization, fixed Project-to-task locks, and complete local snapshot comparison
  - additive optional as_of on unchanged generate-draft routes with bounded failures, redacted audits, and adopt-only final-content governance
affects: [10-03 scenario generator cutover, 10-04 generator verification]

actuals:
  tokens: 18102
  tasks: 3
  commits: 6

tech-stack:
  added: []
  patterns:
    - build and freeze one Context projection before model execution; never re-query shared facts in a generator
    - commit attempt-only model records before expiring ORM state and opening a fresh short write transaction
    - revalidate Principal and PermissionService before fixed-order Project-to-task locks and canonical snapshot comparison
    - persist only redacted Context/output trace fields in generation audits

key-files:
  created: []
  modified:
    - backend/app/services/mapping/source_to_mart_generator.py
    - backend/app/services/mapping/mart_to_ybt_generator.py
    - backend/app/api/mapping_rules.py
    - backend/tests/test_double_layer_mapping.py

key-decisions:
  - "RegulatoryContextBuilder remains the only production shared-fact authority: both double-layer generators consume one immutable projection and contain no ORM, evidence, candidate, retrieval, or peer-mapping fallback."
  - "Generation holds no task or Project lock during Context/model work; model attempts commit separately, then a fresh transaction validates the active actor, re-runs technical.edit authorization, locks Project then task, and compares the complete local snapshot."
  - "Mart-to-YBT treats approved upstream rules as point-in-time Context facts, not local stale-snapshot fields; upstream changes during a model call affect only a later regeneration."
  - "Model output may update only task-local draft fields after readiness, confidence, and question policy; final_content and formal mapping status remain human-governed through explicit adoption/review routes."

patterns-established:
  - "Double-layer optimistic write boundary: attempt commit -> expire_all -> begin -> actor -> PermissionService -> Project FOR UPDATE -> task FOR UPDATE -> snapshot compare -> apply/audit."
  - "Stable generation errors: generation-blocked, stale-task, generation-actor-invalid, and bounded generation-context-failed without reflecting raw Context content."
  - "Frozen upstream rule chain: approved Source-to-Mart summaries are selected, ordered, and provenance-stamped by the Mart Context adapter exactly once per attempt."

requirements-completed: [GEN-01, GEN-02, GEN-04]

coverage:
  - id: D1
    description: "The unchanged Source-to-Mart generate-draft route passes exact Principal, authorized Project, and optional as_of into one Context-only generation attempt while preserving its prompt key, output schema, renderer, and response model."
    requirement: GEN-01
    verification:
      - kind: integration
        ref: "backend/tests/test_double_layer_mapping.py#test_source_to_mart_service_uses_one_context_and_governed_output_policy"
        status: pass
      - kind: api
        ref: "backend/tests/test_double_layer_mapping.py#test_source_to_mart_route_passes_exact_authorized_boundary"
        status: pass
    human_judgment: false
  - id: D2
    description: "Mart-to-YBT uses only approved Context rule_text for its deterministic upstream summary and never performs a peer mapping, evidence, retrieval, or metadata fallback query."
    requirement: GEN-02
    verification:
      - kind: integration
        ref: "backend/tests/test_double_layer_mapping.py#test_mart_to_ybt_service_uses_frozen_context_upstream_and_output_policy"
        status: pass
      - kind: integration
        ref: "backend/tests/test_generator_context_adapters.py#test_all_four_task_projections_are_distinct_and_mart_uses_approved_context_rule_only"
        status: pass
    human_judgment: false
  - id: D3
    description: "Concurrent task/Project edits, disabled users, and changed permissions fail before draft mutation after fresh reauthorization and fixed-order locking, while human final/status/question bytes remain intact."
    requirement: GEN-04
    verification:
      - kind: integration
        ref: "backend/tests/test_double_layer_mapping.py#test_source_to_mart_rejects_every_local_snapshot_category"
        status: pass
      - kind: security
        ref: "backend/tests/test_double_layer_mapping.py#test_source_to_mart_rechecks_permission_after_model_without_draft"
        status: pass
    human_judgment: false
  - id: D4
    description: "Sparse Context remains question-bearing and low-capped, blocks and interruptions write no draft, and successful/stale audits contain only bounded trace metadata rather than raw prompt, evidence, model, or human content."
    requirement: GEN-04
    verification:
      - kind: integration
        ref: "backend/tests/test_double_layer_mapping.py#test_generation_audit_is_redacted_and_query_delta_is_row_count_invariant"
        status: pass
      - kind: security
        ref: "backend/tests/test_double_layer_mapping.py#test_double_layer_generation_failures_never_fallback_or_partially_write"
        status: pass
    human_judgment: false

duration: 57min
completed: 2026-08-23
status: complete
---

# Phase 10 Plan 2: Double-Layer Generator Context Cutover Summary

**Source-to-Mart and Mart-to-YBT now generate governed drafts from one temporal RegulatoryContext projection, with frozen identity and upstream provenance, no shared-fact fallback, and fresh optimistic Project-to-task writes that preserve every human-governed field.**

## Performance

- **Duration:** 57 min
- **Started:** 2026-08-23T07:22:33Z
- **Completed:** 2026-08-23T08:19:21Z
- **Tasks:** 3
- **Delivery files modified:** 4

## Accomplishments

- Replaced Source-to-Mart's direct Mart/source-candidate/evidence/HybridRetriever reads with one authorized `SourceToMartContextAdapter` projection while retaining `source_to_mart_mapping`, `SourceToMartOutput`, raw-SQL refusal, task renderer, route, response schema, and explicit adoption flow.
- Replaced Mart-to-YBT's direct target/Mart/evidence/retrieval and Source-to-Mart summary queries with one `MartToYbtContextAdapter` projection whose approved upstream rule chain stays immutable for the entire model attempt.
- Added optional `as_of` to both unchanged generate-draft routes and passed the exact frozen `CurrentPrincipal` plus the initially `technical.edit`-authorized Project into each service.
- Implemented the same optimistic protocol for both families: no lock across Context/model work, separate attempt persistence, stale ORM expiration, fresh active-User validation and `PermissionService` check, fixed Project-to-task locks, complete local snapshot comparison, then one atomic apply and redacted audit.
- Proved that sparse mapping gaps remain non-blocking but low-capped and question-bearing; authoritative conflicts, Context failures, model interruptions, concurrent edits, and permission changes cannot write a draft or success audit.
- Added measured generator query-delta invariance after row growth and static proof that production modules contain one Context build, fixed authorization/lock order, and no former fallback imports or helpers.

## Task Commits

Each task followed a RED/GREEN pair and was committed atomically:

1. **Task 1 RED: Source-to-Mart Context cutover contracts** — `55847b7` (test)
2. **Task 1 GREEN: authorized Source-to-Mart production cutover** — `1bb0aae` (feat)
3. **Task 2 RED: Mart-to-YBT Context/upstream contracts** — `475d27b` (test)
4. **Task 2 GREEN: frozen approved-upstream production cutover** — `ff68069` (feat)
5. **Task 3 RED: concurrency, failure, privacy, and query contracts** — `2e60e3a` (test)
6. **Task 3 GREEN: bounded failures and complete safety regressions** — `1de2b81` (fix)

**Plan metadata:** committed separately after state and roadmap updates.

## Files Created/Modified

- `backend/app/services/mapping/source_to_mart_generator.py` — one Context build, Source-specific runtime/output policy, attempt persistence, fresh authorization/locking, stale audit, and task-local atomic apply.
- `backend/app/services/mapping/mart_to_ybt_generator.py` — one frozen Context/upstream projection, Mart-specific runtime/output policy, and the matching optimistic write protocol without shared-peer queries.
- `backend/app/api/mapping_rules.py` — exact Principal/authorized Project handoff, additive optional `as_of`, and stable bounded actor/readiness/stale/Context failures on unchanged routes.
- `backend/tests/test_double_layer_mapping.py` — route compatibility, sparse readiness, no-fallback, complete snapshot concurrency, permission revocation, interruption, audit privacy, fixed query delta, frozen upstream, and lock-order regressions.

## Verification Evidence

| Scope | Result |
| --- | --- |
| Double-layer generators + Context adapters | 24 passed in 164.66s |
| RegulatoryContext builder/API + LLM runtime | 82 passed in 90.43s |
| Mart approved-upstream adapter selection | 1 passed in 5.94s |
| `python -m compileall -q app` | PASS, exit 0 |
| Production fallback/stub/static lock-order review | PASS |

The measured production generator delta stayed fixed after adding 40 unrelated same-project mapping rows. The test excludes one runtime/settings cold-start call, then compares the unchanged pre-growth baseline with the post-growth call under identical Session preparation.

## Decisions Made

- Kept `RegulatoryContextBuilder` and its typed adapters as the exclusive shared-fact path. The generators may read only their own task row and Project at the optimistic write boundary; they do not query Metadata, Knowledge, Evidence, History, Lineage, Semantic, candidate, or peer mapping facts.
- Persisted the model attempt before the fresh write transaction so a stale/unauthorized result retains attempt traceability without retaining a task lock or creating a draft/success audit.
- Required active-User validation before fresh `PermissionService(...).require_project_permission(..., "technical.edit")`, followed by fixed Project then task locks. A falsey non-legacy identity never becomes legacy authority.
- Compared every serialized local Project/task field, including final content, status, questions, draft, scope, governance, lineage, and timestamps. Any difference records only changed field paths and rejects the output.
- Excluded Mart upstream shared facts from the local stale snapshot. Their single provenance-stamped Context projection is the attempt's point-in-time input; a later shared change is intentionally visible only to a later regeneration.
- Preserved AI-draft versus human-final governance: successful generation never changes `final_content` or formal review status; only the existing adopt/review routes may do so.

## Deviations from Plan

None - plan executed exactly as written.

## TDD Gate Compliance

- Task 1 RED `55847b7` failed because the Source route lacked the frozen Principal/authorized Project parameters; GREEN `1bb0aae` passed all six double-layer tests at the tracer gate, which the user approved before expansion.
- Task 2 RED `475d27b` failed because the Mart route lacked the same authorized boundary; GREEN `ff68069` passed the three Mart-selected tests and approved-upstream adapter regression.
- Task 3 RED `2e60e3a` failed because raw Context `ValueError` details escaped the route; GREEN `1de2b81` bounded that response and passed all 24 generator/adapter tests.

## Issues Encountered

- The first query-growth assertion measured one extra cold-start SELECT (`16` versus the steady `15/14` shape). The test was corrected to perform a non-comparison warm-up and reset the Session identically before the pre-growth and post-growth measurements; the fixed-delta regression then passed.

## Authentication Gates

None. The tracer human-verification checkpoint was approved after its production slice and six tests passed.

## Known Stubs

None. Production scans found no TODO/FIXME/placeholder path, empty UI data source, skipped test, or legacy fallback branch.

## User Setup Required

None.

## Remaining Risks / Next Phase Readiness

- SQLite proves overlapping transactions, snapshot invalidation, atomic outcomes, and no long-held generator lock. PostgreSQL `FOR UPDATE` ordering is statically verified as Project then task; real PostgreSQL isolation remains a staging qualification rather than a local claim.
- Scenario business and technical generators remain unchanged and are owned by Plan 10-03. This plan intentionally did not modify their HybridRetriever paths or physical-field behavior.
- Existing unrelated frontend working-tree changes and untracked learning/demo assets remain untouched and uncommitted.

## Self-Check: PASSED

- All four delivery files and this summary exist on disk.
- Commits `55847b7`, `1bb0aae`, `475d27b`, `ff68069`, `2e60e3a`, and `1de2b81` are present in history.
- Frontmatter includes `status: complete`, exact requirements `[GEN-01, GEN-02, GEN-04]`, and realized diff-scale actuals.
- No task commit deleted a tracked file or absorbed unrelated frontend/untracked material.

---
*Phase: 10-generator-refactor*
*Completed: 2026-08-23*
