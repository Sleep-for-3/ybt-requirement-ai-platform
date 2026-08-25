---
phase: 11-semantic-catalog-ui
plan: 01
subsystem: api
tags: [fastapi, sqlalchemy, pydantic, nextjs, semantic-catalog, rbac]

requires:
  - phase: 08-semantic-foundation
    provides: canonical semantic concepts, versions, bindings, and lifecycle policy
  - phase: 09-semantic-operations
    provides: effective-version resolver and governed review workflows
provides:
  - project-scoped semantic catalog GET API with authoritative filtering, facets, and pagination
  - permission-redacted related-asset references and explicit audit-mode authorization
  - typed frontend catalog contract and real project-aware /semantics route
affects: [11-02, 11-03, semantic-catalog-ui, semantic-detail-ui]

actuals:
  tokens: 14025
  tasks: 2
  commits: 3

tech-stack:
  added: []
  patterns:
    - projection-only read service over canonical semantic tables
    - discriminated readable/restricted asset references shaped before serialization
    - one filtered population drives totals, facets, ordering, and page selection

key-files:
  created:
    - backend/app/schemas/semantic_catalog.py
    - backend/app/services/semantic/catalog_query_service.py
    - backend/app/api/semantic_catalog.py
    - backend/tests/test_semantic_catalog_api.py
    - frontend/app/semantics/page.tsx
  modified:
    - backend/app/main.py
    - frontend/lib/types.ts

key-decisions:
  - "Resolve canonical confirmed versions once for the project-scoped population, then derive search, filters, facets, and pagination from that same population."
  - "Require audit.read before audit DTO construction and replace unreadable binding targets with a type-only restricted union before serialization."
  - "Keep lifecycle status, review workflow state, and open-question counts as separate catalog fields."

patterns-established:
  - "Catalog projection: canonical semantic tables remain authoritative; the query service owns only a read model."
  - "Permission projection: return readable references only for permitted asset classes and never serialize identifiers for restricted targets."

requirements-completed: [SUI-01]

coverage:
  - id: D1
    description: "Authenticated project-scoped catalog API returns temporally effective summaries, server filters, facets, stable pagination, workflow aggregates, and safe restricted references."
    requirement: SUI-01
    verification:
      - kind: integration
        ref: "python -m pytest backend/tests/test_semantic_catalog_api.py backend/tests/test_semantic_layer.py -q -x"
        status: pass
    human_judgment: false
  - id: D2
    description: "The real /semantics route uses shared project context and typed API data to render catalog states and a governed directory row."
    requirement: SUI-01
    verification:
      - kind: other
        ref: "npm --prefix frontend run build"
        status: pass
      - kind: manual_procedural
        ref: "Task 1 tracer feedback checkpoint"
        status: pass
    human_judgment: false

duration: 16min
completed: 2026-08-25
status: complete
---

# Phase 11 Plan 01: Semantic Catalog Tracer and Read Contract Summary

**Canonical effective-version catalog projection with permission-redacted assets, server-authoritative filters and facets, and a real project-aware `/semantics` route**

## Performance

- **Duration:** 16 min
- **Started:** 2026-08-25T04:38:39Z
- **Completed:** 2026-08-25T04:54:14Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- Added an authenticated `GET /api/projects/{project_id}/semantic-catalog` route backed only by canonical semantic concepts, confirmed effective versions, bindings, relations, review tasks, and pending questions.
- Implemented server-side name/code/alias/definition search, advanced filters, trusted/candidate/audit partitions, stable null-domain-last pagination, facets, and set-based aggregate loading.
- Enforced `project.view` and `audit.read`, exact project/institution scoping, and type-only restricted related-asset references that do not serialize protected identifiers or display data.
- Added a typed frontend seam and a real `/semantics` route covering project selection, loading, success, empty, forbidden, and operational-error states.

## Task Commits

Each task was committed atomically:

1. **Task 1: Trace one governed catalog row end to end** - `bee3016` (feat)
2. **Task 2 RED: Add failing semantic catalog contract tests** - `7a90bfb` (test)
3. **Task 2 GREEN: Complete server-side catalog population and permission projection** - `182db48` (feat)

## TDD Gate Compliance

- RED gate: `7a90bfb`; the new suite failed on missing alias search (`1 failed, 1 passed`).
- GREEN gate: `182db48`; focused and compatibility suites passed (`24 passed`).
- No separate refactor commit was needed.

## Files Created/Modified

- `backend/app/schemas/semantic_catalog.py` - Strict page, facet, effective-version, workflow-summary, and discriminated asset-reference DTOs.
- `backend/app/services/semantic/catalog_query_service.py` - Canonical project/institution-scoped read projection and set-based filters/aggregates.
- `backend/app/api/semantic_catalog.py` - Authenticated route, validated query contract, audit gate, and permission projection input.
- `backend/app/main.py` - Registers the catalog router under the secured `/api` prefix.
- `backend/tests/test_semantic_catalog_api.py` - Focused tracer and authoritative catalog contract coverage.
- `frontend/lib/types.ts` - Shared typed semantic catalog response seam.
- `frontend/app/semantics/page.tsx` - Real project-aware catalog route using the shared authenticated API helper.

## Decisions Made

- Effective confirmed versions are resolved in one batch and are the only source for historical definition/domain/owner summaries.
- The full filtered population is computed before pagination so totals and facets cannot drift from page results.
- Audit history is opt-in and permission-gated; rejected/deprecated rows never contaminate trusted or candidate counts.
- Binding target permissions are evaluated before target lookup/serialization, keeping restricted references type-only.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test Bug] Replaced an ambiguous raw-number leak assertion**
- **Found during:** Task 2 GREEN
- **Issue:** The restricted-reference test asserted that the string form of target ID `1` was absent from the entire response, but unrelated public IDs, counts, dates, and version numbers legitimately contain `1`.
- **Fix:** Asserted directly that the restricted reference contains no `entity_id`, while retaining the exact type-only DTO equality and protected display-name absence checks.
- **Files modified:** `backend/tests/test_semantic_catalog_api.py`
- **Verification:** Focused and compatibility suites passed with the corrected security assertion.
- **Committed in:** `182db48`

**2. [Rule 3 - Blocking] Supplied the repository's backend import root for pytest**
- **Found during:** Task 1 and plan verification
- **Issue:** Running the plan's pytest commands from the repository root without `PYTHONPATH` fails during collection with `ModuleNotFoundError: app`.
- **Fix:** Ran the exact test targets with `PYTHONPATH` set to the existing `backend` directory; no package, test, or project configuration was changed.
- **Files modified:** None
- **Verification:** Focused suite passed (`6 passed`); combined catalog and semantic-layer suite passed (`24 passed`).
- **Committed in:** Not applicable (environment-only adjustment)

---

**Total deviations:** 2 auto-fixed (1 test bug, 1 blocking environment issue)
**Impact on plan:** Both corrections were required to verify the intended contract and introduced no product scope or dependency changes.

## Verification Results

- `PYTHONPATH=backend python -m pytest backend/tests/test_semantic_catalog_api.py -q -x` — **6 passed in 6.25s**.
- `PYTHONPATH=backend python -m pytest backend/tests/test_semantic_catalog_api.py backend/tests/test_semantic_layer.py -q -x` — **24 passed in 26.46s**.
- `npm --prefix frontend test` — **26 passed, 0 failed, 0 skipped**.
- `npm --prefix frontend run build` — **passed**; Next.js compiled, typechecked, generated 41 static pages, and emitted `/semantics` at 6.25 kB / 102 kB first load.
- Build reported existing `react-hooks/exhaustive-deps` warnings in unrelated pages; no warning originated in Plan 11-01 files.

## Known Stubs

None. The catalog page is wired to the authenticated API and does not use mock or duplicate fact data.

## Issues Encountered

- The frontend build retained pre-existing hook dependency warnings outside the allowed modification scope. They did not fail compilation, type checking, static generation, or route emission.

## User Setup Required

None - no package or external service configuration was added.

## Next Phase Readiness

- Plans 11-02 and 11-03 can expand presentation and detail interactions on the typed catalog page contract.
- The additive query begins with existing indexes as required; production-scale query-plan measurement remains a later operational concern, not a blocker for this plan.

## Self-Check: PASSED

All seven implementation files, the plan summary, and commits `bee3016`, `7a90bfb`, and `182db48` were found.

---
*Phase: 11-semantic-catalog-ui*
*Completed: 2026-08-25*
