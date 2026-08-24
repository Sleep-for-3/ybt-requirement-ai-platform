---
phase: 10-generator-refactor
plan: 07
subsystem: api-generation-retirement
tags: [legacy-retirement, authorization, regulatory-context, compatibility, no-fallback]

requires:
  - phase: 10-generator-refactor/10-04
    provides: verification evidence identifying the competing legacy generator
provides:
  - authorized non-mutating HTTP 410 retirement facade for the legacy field generator
  - complete removal of the legacy RAG/SQL/template/database-probe constructor
  - preserved historical FieldMappingDraft read and review compatibility
affects: [10-08-phase-qualification, Phase-10-verification]

actuals:
  tokens: 7080
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns:
    - keep a deprecated route as an authorized diagnostic facade while removing its production constructor
    - verify retirement with zero-call, zero-mutation, compatibility, and static production-reference assertions

key-files:
  created:
    - backend/tests/test_legacy_mapping_retirement.py
  modified:
    - backend/app/api/target_fields.py
    - backend/app/services/auth/resource_guard.py
    - backend/app/services/llm/prompt_runtime.py
  deleted:
    - backend/app/services/mapping_generator.py

key-decisions:
  - "The legacy POST path remains parseable but returns a stable authorized HTTP 410 instead of falling back to any old or new generator."
  - "Both shared resource guard and endpoint authorization require technical.edit before retirement details are disclosed."
  - "Legacy persistence models and read/review APIs remain intact; only the competing constructor and its unused prompt key are removed."

patterns-established:
  - "Retirement facade: resolve resource, authorize exact scope, return bounded replacement guidance, perform zero shared-fact/model/persistence work."

requirements-completed: [GEN-01, GEN-02, GEN-04]

coverage:
  - id: D1
    description: "Authorized legacy generation returns stable HTTP 410 with zero generator call and zero legacy row mutation."
    requirement: "GEN-01, GEN-02"
    verification:
      - kind: integration
        ref: "tests/test_legacy_mapping_retirement.py#test_authorized_route_is_retired_without_generation_or_mutation"
        status: pass
    human_judgment: false
  - id: D2
    description: "Missing, foreign, and visible-but-unauthorized resources do not receive retirement details."
    requirement: "GEN-04"
    verification:
      - kind: integration
        ref: "tests/test_legacy_mapping_retirement.py#test_missing_and_foreign_fields_do_not_disclose_retirement_detail"
        status: pass
    human_judgment: false
  - id: D3
    description: "Historical FieldMappingDraft data remains readable and reviewable after retirement."
    requirement: "GEN-04"
    verification:
      - kind: integration
        ref: "tests/test_legacy_mapping_retirement.py#test_existing_draft_remains_readable_and_reviewable_after_retirement"
        status: pass
    human_judgment: false
  - id: D4
    description: "The obsolete module, import, symbol, and prompt runtime key no longer exist in production."
    requirement: "GEN-01, GEN-02"
    verification:
      - kind: unit
        ref: "tests/test_legacy_mapping_retirement.py#test_obsolete_composite_constructor_has_no_production_module_or_reference"
        status: pass
    human_judgment: false

duration: 9 min
completed: 2026-08-24
status: complete
---

# Phase 10 Plan 07: Legacy Mapping Generator Retirement Summary

**The competing field-level RAG/SQL/template generator is removed, while its old POST path now provides an authorized, stable, and completely non-mutating HTTP 410 contract.**

## Performance

- **Duration:** 9 min including Wave 5 regression gate
- **Started:** 2026-08-24T21:02:00+08:00
- **Completed:** 2026-08-24T21:11:00+08:00
- **Tasks:** 2
- **Files changed:** 5

## Accomplishments

- Retained request parsing and the old URL while replacing generation with a stable `legacy-mapping-generator-retired` response after resource authorization.
- Deleted `mapping_generator.py`, its production import, the `generate_mapping_draft` symbol, and the unused `legacy_field_mapping` prompt key.
- Proved no FieldAnalysisTask, FieldMappingDraft, or EvidenceReference mutation occurs and no legacy generator is invoked.
- Preserved existing draft retrieval and review behavior without schema or data deletion.

## Task Commits

1. **Task 1 RED: retirement, authorization, mutation, and compatibility regressions** - `5228879`
2. **Tasks 1-2 GREEN: retirement facade and obsolete constructor removal** - `c71e0d7`

## Files Created/Modified

- `backend/app/api/target_fields.py` - authorized HTTP 410 retirement facade.
- `backend/app/services/auth/resource_guard.py` - exact technical.edit guard mapping for the retired route.
- `backend/app/services/llm/prompt_runtime.py` - removed the unused legacy prompt registration.
- `backend/app/services/mapping_generator.py` - deleted competing shared-fact constructor.
- `backend/tests/test_legacy_mapping_retirement.py` - route, isolation, zero-mutation, compatibility, and static-reference regressions.

## Decisions Made

- Chose explicit retirement rather than migration because no target mapping identity is available on the field-only route and silently selecting one would violate governed scope.
- Kept historical models and schemas because they remain the compatibility contract for previously generated records.
- Required `technical.edit` consistently in the resource guard and endpoint before returning replacement guidance.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Aligned the shared resource guard with the route's technical.edit contract**

- **Found during:** unauthorized route regression.
- **Issue:** the generic POST guard required `project.manage` before endpoint-level `technical.edit`, obscuring the intended permission boundary.
- **Fix:** added a path-exact `technical.edit` mapping for `/fields/{id}/generate-mapping` only.
- **Files modified:** `backend/app/services/auth/resource_guard.py`.
- **Verification:** viewer receives 403 without retirement detail; legacy authorized caller receives 410.
- **Committed in:** `c71e0d7`.

**2. [Rule 2 - Missing Critical] Removed the orphaned legacy prompt registration**

- **Found during:** static production-reference regression.
- **Issue:** `legacy_field_mapping` remained registered after the constructor was deleted.
- **Fix:** removed the unused prompt label entry.
- **Files modified:** `backend/app/services/llm/prompt_runtime.py`.
- **Verification:** production reference scan and router import pass.
- **Committed in:** `c71e0d7`.

---

**Total deviations:** 2 auto-fixed (1 blocking authorization mismatch, 1 missing cleanup).
**Impact:** Both changes are required to make the retirement and its permission boundary complete; no new generator, schema, or product scope was added.

## Verification

- `python -m pytest -q tests/test_legacy_mapping_retirement.py -x` - PASS, `4 passed`.
- `python -m compileall -q app` - PASS.
- `python -c "from app.main import app; from app.api import target_fields"` - PASS.
- Wave 5 combined gate: `43 passed in 203.20s` across retirement, double-layer lifecycle, and Context adapter tests.

## Issues Encountered

None remaining.

## User Setup Required

None.

## Next Phase Readiness

- The competing legacy shared-fact constructor is gone, so Deliverable Source/Mart cutover can proceed against the sole governed generator paths.
- Historical drafts remain accessible; clients invoking generation must migrate to the replacement mapping-specific routes.

---
*Phase: 10-generator-refactor*
*Completed: 2026-08-24*
