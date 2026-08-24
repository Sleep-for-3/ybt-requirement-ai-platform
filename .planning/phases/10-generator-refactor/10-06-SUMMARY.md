---
phase: 10-generator-refactor
plan: 06
subsystem: deliverable-generation
tags: [regulatory-context, deliverables, authorization, queue, optimistic-write, no-fallback]

requires:
  - phase: 10-generator-refactor/10-05
    provides: draft-only double-layer lifecycle enforcement at pre-model and post-lock boundaries
  - phase: 10-generator-refactor/10-03
    provides: frozen queued Principal recovery and governed Scenario generation runner pattern
provides:
  - governed direct Source/Mart compile compatibility facades
  - governed queued Source/Mart item execution with technical.edit reauthorization
  - bounded completed/blocked/failed BackgroundJobItem outcomes
  - removal of both legacy Deliverable compiler constructors
affects: [10-08-phase-qualification, Phase-10-verification, Deliverable-generation]

actuals:
  tokens: 9318
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns:
    - direct compatibility routes delegate to the same governed generator used by mapping APIs
    - queued task runner reauthorizes per item and passes the checked Project into the generator
    - bounded job diagnostics never persist Context, prompt, evidence body, or exception text

key-files:
  created: []
  modified:
    - backend/app/api/deliverables.py
    - backend/tests/test_deliverables.py
    - backend/tests/test_scenario_traceability.py
  deleted:
    - backend/app/services/deliverables/source_to_mart_compiler.py
    - backend/app/services/deliverables/mart_to_ybt_compiler.py

key-decisions:
  - "Deliverable direct compile retains its route and four response keys but delegates exclusively to the governed Source/Mart generator with optional as_of."
  - "deliverable.generate grants package authority only; every Source/Mart item separately requires technical.edit and passes that check's exact Project."
  - "Source/Mart queue items use the same internal runner as Scenario items, while their generator, task rows, projections, and output contracts remain distinct."
  - "Approved, final-content, or existing-draft rows remain deterministic skips; permission, readiness, lifecycle, and stale failures remain bounded blocks."

patterns-established:
  - "Deliverable task execution: recover active non-legacy actor -> authorize exact task permission -> governed generator -> per-item commit."

requirements-completed: [GEN-01, GEN-02, GEN-04]

coverage:
  - id: D1
    description: "Direct Source/Mart compile routes preserve response keys and optional as_of while using exact Principal, technical.edit Project, and governed generators."
    requirement: "GEN-01, GEN-02"
    verification:
      - kind: integration
        ref: "tests/test_deliverables.py#test_direct_source_and_mart_compile_use_governed_generators_and_keep_response_keys"
        status: pass
    human_judgment: false
  - id: D2
    description: "deliverable.generate-only actors cannot invoke or mutate technical mappings."
    requirement: "GEN-01, GEN-02"
    verification:
      - kind: integration
        ref: "tests/test_deliverables.py#test_direct_compile_requires_technical_edit_before_generator"
        status: pass
    human_judgment: false
  - id: D3
    description: "Queued real Source/Mart rows use recovered non-legacy Principal, checked Project, optional date, and per-item completed records."
    requirement: "GEN-01, GEN-02"
    verification:
      - kind: integration
        ref: "tests/test_scenario_traceability.py#test_deliverable_queued_handler_passes_scoped_context_and_counts_blocks"
        status: pass
    human_judgment: false
  - id: D4
    description: "Post-package technical permission revocation blocks Source/Mart items without invoking generators or mutating drafts."
    requirement: "GEN-04"
    verification:
      - kind: integration
        ref: "tests/test_scenario_traceability.py#test_deliverable_source_and_mart_items_block_when_technical_permission_is_revoked"
        status: pass
    human_judgment: false
  - id: D5
    description: "Legacy compiler modules and production call references are absent."
    requirement: "GEN-01, GEN-02"
    verification:
      - kind: unit
        ref: "tests/test_deliverables.py#test_legacy_deliverable_compilers_are_removed_from_production"
        status: pass
    human_judgment: false

duration: 16 min
completed: 2026-08-24
status: complete
---

# Phase 10 Plan 06: Deliverable Governed Generator Cutover Summary

**Deliverable direct and queued Source/Mart generation now reuse the sole governed Context generator contract, with per-item technical authorization and no legacy compiler fallback.**

## Performance

- **Duration:** 16 min including Wave 6 regression gates
- **Started:** 2026-08-24T21:15:00+08:00
- **Completed:** 2026-08-24T21:31:00+08:00
- **Tasks:** 2
- **Files changed:** 5

## Accomplishments

- Converted both direct compile APIs into async compatibility facades over the existing governed Source/Mart generators while preserving `mapping_id`, `draft`, `claim_type`, and `open_questions`.
- Added optional `as_of` to direct compile without breaking calls that omit it; the resolved date remains recorded by generator Context/audit trace.
- Routed real Source/Mart queue rows through the existing per-item runner with active-user recovery, fresh `technical.edit`, exact checked Project, bounded outcomes, and item commits.
- Removed both peer-ORM legacy compiler files and all production imports/calls.
- Proved permission revocation after package authorization blocks both mapping families before generator work and mutation.

## Task Commits

1. **Tasks 1-2 RED: direct and queued governed cutover regressions** - `a03f63a`
2. **Tasks 1-2 GREEN: direct facades, queued runner cutover, and compiler removal** - `283b763`

## Files Created/Modified

- `backend/app/api/deliverables.py` - direct compatibility facades and governed queued Source/Mart orchestration.
- `backend/tests/test_deliverables.py` - direct HTTP/function authorization, date, response, and static isolation tests.
- `backend/tests/test_scenario_traceability.py` - real queued Source/Mart dispatch and permission-revocation tests.
- `backend/app/services/deliverables/source_to_mart_compiler.py` - deleted legacy peer ORM constructor.
- `backend/app/services/deliverables/mart_to_ybt_compiler.py` - deleted legacy peer ORM constructor.

## Decisions Made

- Reused one internal task runner for authorization/error isolation but retained four separate generator services and outputs.
- Kept package-level `deliverable.generate` separate from mapping-level `technical.edit`; neither permission implies the other.
- Preserved compatibility response shape with a compact projection from the governed mapping result, never raw Context or prompt material.
- Continued to treat mapping absence as a normal generation starting point; only deterministic readiness/governance/authorization/stale conditions block.

## Deviations from Plan

None - plan executed within scope. Tests were tightened during GREEN to avoid retaining expired ORM instances and to distinguish audit action names from removed compiler call symbols.

## Verification

- Focused direct compile/static tests: `3 passed`.
- Focused queued governed mapping tests: `2 passed`.
- Full `tests/test_deliverables.py tests/test_scenario_traceability.py`: PASS, `36 passed in 241.21s`.
- Adjacent `tests/test_double_layer_mapping.py tests/test_generator_context_adapters.py`: PASS, `39 passed in 199.83s`.
- `python -m compileall -q app`: PASS.

## Issues Encountered

- SQLAlchemy expires ORM state after the compatibility audit commit; tests therefore capture the authorized Project identity at generator invocation rather than reading a detached object afterward.
- Live PostgreSQL was unavailable and no production-driver concurrency claim is made.

## User Setup Required

None.

## Next Phase Readiness

- All known Phase 10 implementation gaps are closed; ready for 10-08 focused, adjacent, full-backend, and phase verification qualification.
- PostgreSQL row-lock/concurrent-commit validation remains an explicit staging gate.

---
*Phase: 10-generator-refactor*
*Completed: 2026-08-24*
