---
phase: 11-semantic-catalog-ui
plan: 02
subsystem: ui
tags: [nextjs, react, semantic-catalog, url-state, accessibility, tdd]

requires:
  - phase: 11-semantic-catalog-ui
    plan: 01
    provides: authenticated server-authoritative catalog API, redacted DTOs, and the real project-aware /semantics tracer
provides:
  - URL-shareable catalog search, server filters, audit opt-in, pagination, and directory/table view state
  - race-safe project-scoped request orchestration with distinct loading, forbidden, retryable-error, and empty states
  - grouped domain directory and accessible comparison table with separate lifecycle and review indicators
affects: [11-03, 11-04, semantic-detail-ui, semantic-catalog-navigation]

actuals:
  tokens: 17874
  tasks: 3
  commits: 5

tech-stack:
  added: []
  patterns:
    - canonical URL query state with explicit search submission and immediate filter replacement
    - abort plus captured request-key comparison before committing asynchronous catalog responses
    - server-authoritative totals, facets, filters, pagination, and audit mode with presentation-only client view switching

key-files:
  created:
    - frontend/components/semantic-catalog/CatalogToolbar.tsx
    - frontend/components/semantic-catalog/GroupedSemanticDirectory.tsx
    - frontend/components/semantic-catalog/SemanticComparisonTable.tsx
    - frontend/components/semantic-catalog/SemanticStatus.tsx
    - frontend/lib/semantic-catalog-view-model.mjs
    - frontend/tests/semantic-catalog-view-model.test.mjs
  modified:
    - frontend/app/semantics/page.tsx
    - frontend/components/AppShell.tsx
    - frontend/lib/api.ts
    - frontend/lib/http-response.mjs
    - frontend/lib/types.ts

key-decisions:
  - "Keep the browser URL as the durable catalog state: search commits on submit, while filters, view, audit, and pagination update canonically."
  - "Include every server-affecting parameter in request identity, abort superseded work, and reject late responses before state commit."
  - "Preserve server totals and facets as authoritative; the client switches only presentation and never claims a filtered full dataset."
  - "Render lifecycle, pending review, and explicit server-confirmed audit mode as independent governance signals."
  - "Preserve protected-route 401 clearing and redirect behavior while carrying status on non-401 API errors."

patterns-established:
  - "Catalog URL seam: parse and serialize through one tested view-model before navigation or requests."
  - "Catalog response seam: idle, loading, forbidden, retryable error, empty, and populated are explicit render states."
  - "Governance display seam: lifecycle badges and review workflow labels are centralized and never collapsed into one state."

requirements-completed: [SUI-01]

coverage:
  - id: D1
    description: "Users can restore, search, filter, paginate, and switch views through canonical URL state backed by the authoritative catalog API."
    requirement: SUI-01
    verification:
      - kind: unit
        ref: "frontend/tests/semantic-catalog-view-model.test.mjs#URL state, explicit search, query, request-key, and response-state tests"
        status: pass
      - kind: other
        ref: "npm --prefix frontend run build"
        status: pass
    human_judgment: false
  - id: D2
    description: "Project changes cancel stale catalog work and distinct forbidden, retryable-error, empty, and populated states remain truthful."
    requirement: SUI-01
    verification:
      - kind: unit
        ref: "frontend/tests/semantic-catalog-view-model.test.mjs#project changes abort old work and response states"
        status: pass
      - kind: unit
        ref: "frontend/tests/http-response.test.mjs#status-bearing ApiError and protected 401 behavior"
        status: pass
    human_judgment: false
  - id: D3
    description: "The catalog renders a grouped domain directory and a horizontally scrollable 10-column comparison table with separate lifecycle, review, and audit indicators."
    requirement: SUI-01
    verification:
      - kind: unit
        ref: "frontend/tests/semantic-catalog-view-model.test.mjs#grouping, lifecycle partitions, confirmed facts, and redaction"
        status: pass
      - kind: other
        ref: "npm --prefix frontend run build"
        status: pass
    human_judgment: true
    rationale: "Final visual density, overflow, and focus behavior at the specified 320, 768, 1280, and 1440px viewports requires phase UI verification."

duration: 27min
completed: 2026-08-25
status: complete
---

# Phase 11 Plan 02: Semantic Catalog Browsing and Navigation Summary

**URL-backed real-data semantic catalog with authoritative server filtering, race-safe project requests, grouped directory and comparison views, and truthful governance states**

## Performance

- **Duration:** 27 min
- **Started:** 2026-08-25T04:59:17Z
- **Completed:** 2026-08-25T05:26:12Z
- **Tasks:** 3
- **Files modified:** 14 implementation/test files

## Accomplishments

- Expanded the real `/semantics` tracer into canonical bookmarkable state for explicit search, primary and advanced filters, audit opt-in, pagination, and directory/table presentation.
- Added complete request identity, `AbortSignal` transport, captured-key response acceptance, and status-bearing errors without changing the shared protected-401 session clearing and redirect flow.
- Rendered server-provided results as a stable 68px domain directory or accessible 56px comparison table, keeping lifecycle, pending review, confirmed asset counts, and audit-only history semantically separate.
- Added a Semantic Catalog navigation entry to the existing AppShell through an index-only two-line commit that excluded the user's pre-existing AppShell rebuild diff.

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Define catalog state, temporal, governance, and HTTP status seams** - `24e438a` (test)
2. **Task 1 GREEN: Implement catalog state and status-bearing error seams** - `340cdee` (feat)
3. **Task 2 RED: Define explicit search, authoritative query, race, and response-state behavior** - `9e84fb9` (test)
4. **Task 2 GREEN: Build URL-backed server catalog controls and request orchestration** - `6908d5f` (feat)
5. **Task 3: Render grouped directory, comparison table, and governance hierarchy** - `7eb7aaf` (feat)

## TDD Gate Compliance

- Task 1 RED (`24e438a`) failed as expected because the new catalog view-model module and status-bearing error export did not exist.
- Task 1 GREEN (`340cdee`) passed the focused state, temporal, lifecycle, grouping, redaction, request-key, and HTTP-status tests.
- Task 2 RED (`9e84fb9`) failed as expected because search-commit and request-orchestration exports did not exist.
- Task 2 GREEN (`6908d5f`) passed the focused query, cancellation, late-response, and explicit response-state tests.
- No separate refactor commit was needed.

## Files Created/Modified

- `frontend/app/semantics/page.tsx` - Canonical URL navigation, authoritative API orchestration, distinct response states, pagination, and complete catalog result rendering.
- `frontend/components/AppShell.tsx` - Two-line additive Semantic Catalog navigation entry only.
- `frontend/components/semantic-catalog/CatalogToolbar.tsx` - Explicit search form, primary/advanced filters, active chips, audit opt-in, and accessible view switch.
- `frontend/components/semantic-catalog/GroupedSemanticDirectory.tsx` - Stable domain grouping with blank domains last and governed summary rows.
- `frontend/components/semantic-catalog/SemanticComparisonTable.tsx` - Medium-density 10-column comparison view with deliberate horizontal scrolling and accessible full values.
- `frontend/components/semantic-catalog/SemanticStatus.tsx` - Central lifecycle, review workflow, and concept-type display vocabulary.
- `frontend/lib/semantic-catalog-view-model.mjs` - URL parsing/serialization, temporal parsing, partitions, formal-definition selection, grouping, redaction, query building, and request coordination.
- `frontend/lib/semantic-catalog-view-model.d.mts` - Typed contract for the catalog view-model seam.
- `frontend/lib/api.ts` - Abort-signal transport and expanded semantic catalog DTO exports.
- `frontend/lib/http-response.mjs` - Status-bearing `ApiError` with unchanged protected-401 behavior.
- `frontend/lib/http-response.d.mts` - Type declaration for status-bearing errors.
- `frontend/lib/types.ts` - Complete catalog item, lifecycle, review, related-asset, and facet types.
- `frontend/tests/semantic-catalog-view-model.test.mjs` - TDD coverage for URL state, temporal facts, governance partitions, redaction, query orchestration, and response states.
- `frontend/tests/http-response.test.mjs` - Regression coverage for status preservation and shared 401 normalization.

## Decisions Made

- The URL is the durable UI state, but search text remains a draft until form submission to avoid request-per-keystroke history churn.
- Project and server filter changes clear prior rows, abort superseded requests, and accept a response only when its full captured request key remains current.
- `view` is intentionally excluded from the API query because it changes presentation only; all result selection, totals, facets, and pagination remain server-owned.
- Audit rows display only when both the canonical audit query and the server response mode confirm audit context; audit rows are explicitly marked as non-current facts.
- Lifecycle badges and pending-review workflow text use different models and components so candidate state cannot imply governance approval.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed new hook dependency warnings from the catalog request effect**
- **Found during:** Task 2 GREEN
- **Issue:** The first production build identified newly introduced dependency warnings for the catalog request coordinator and parsed query string.
- **Fix:** Captured the coordinator reference and parsed the query inside the effect so the catalog route has a complete, stable dependency set.
- **Files modified:** `frontend/app/semantics/page.tsx`
- **Verification:** Production build and explicit lint pass without any warning from `/app/semantics`.
- **Committed in:** `6908d5f`

---

**Total deviations:** 1 auto-fixed bug.
**Impact on plan:** The fix made request orchestration deterministic and warning-free without changing scope or dependencies.

## Verification Results

- `npm --prefix frontend test` - **39 passed, 0 failed, 0 skipped**.
- `npm --prefix frontend test -- --test-name-pattern="semantic-catalog"` - **39 passed, 0 failed, 0 skipped**; the repository's Node runner executes the complete test glob while the semantic tests remain individually named.
- `npm --prefix frontend run build` - **passed**; Next.js compiled, typechecked, generated 41 static pages, and emitted `/semantics` at 12.5 kB / 109 kB first load.
- `npm --prefix frontend run lint` - **passed**; existing `react-hooks/exhaustive-deps` warnings remain only in unrelated routes, with none in Plan 11-02 files.

## AppShell WIP Preservation

- Before Plan 11-02, the user-owned AppShell worktree diff was recorded and the index was empty.
- Commit `6908d5f` contains exactly two AppShell additions and zero deletions: the `BookOpenCheck` import and `/semantics` navigation entry.
- After all implementation commits, `git diff --numstat -- frontend/components/AppShell.tsx` reports the user's pre-existing AppShell work as **56 additions / 32 deletions**, still unstaged.
- `git diff --cached -- frontend/components/AppShell.tsx` is empty; no pre-existing AppShell hunk was absorbed into a plan commit.

## Known Stubs

None. The catalog page is wired to the authenticated project API; input placeholders, empty `<option>` values, and nullable advanced filters are functional controls rather than mock data or deferred UI.

## Issues Encountered

- The repository retains pre-existing hook dependency warnings outside the allowed modification scope. They do not originate in Plan 11-02 files and did not fail lint, type checking, static generation, or route emission.
- AppShell already contained a large user-owned rebuild diff. The navigation addition was staged as a minimal index-only patch, verified as two additions, and committed without staging the working-tree WIP.

## User Setup Required

None - no packages, environment variables, external services, or mutation flows were added.

## Next Phase Readiness

- Plan 11-03 can build detail navigation on the tested canonical `returnTo` and temporal query seams.
- Plan 11-04 can add cross-surface navigation while retaining the AppShell and URL-state patterns established here.
- Required visual inspection at 320x720, 768x1024, 1280x800, and 1440x900 remains assigned to phase UI verification, not this autonomous code/build gate.

## Self-Check: PASSED

All 14 implementation/test files, this summary, and commits `24e438a`, `340cdee`, `9e84fb9`, `6908d5f`, and `7eb7aaf` were found. The AppShell plan hunk is committed separately while the user's pre-existing AppShell diff remains unstaged.

---
*Phase: 11-semantic-catalog-ui*
*Completed: 2026-08-25*
