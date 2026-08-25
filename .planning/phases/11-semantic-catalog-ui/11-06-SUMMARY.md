---
phase: 11-semantic-catalog-ui
plan: 06
subsystem: ui
tags: [nextjs, react, semantic-catalog, request-identity, url-state, pagination, accessibility, tdd]

requires:
  - phase: 11-semantic-catalog-ui
    plan: 05
    provides: institution-isolated catalog population, truthful server facets, and canonical formal versions
provides:
  - request-keyed production catalog state that rejects stale success and error completions across project, query, and retry attempts
  - canonical audit/status URL and API tuples with a localized uncategorized presentation
  - bounded first/previous/next/last pagination and one exhaustive permission-safe semantic entity label source
affects: [11-07, 11-08, 11-09, semantic-catalog-ui, semantic-detail-ui]

actuals:
  tokens: 8785
  tasks: 3
  commits: 7

tech-stack:
  added: []
  patterns:
    - immutable project-plus-canonical-query request identity with attempt-scoped completion authority
    - one canonical audit/status transition shared by URL serialization and API construction
    - type-only restricted-reference labels from one exhaustive production table

key-files:
  created:
    - frontend/lib/semantic-catalog-controller.mjs
    - frontend/lib/semantic-catalog-controller.d.mts
    - frontend/lib/semantic-entity-types.mjs
    - frontend/lib/semantic-entity-types.d.mts
  modified:
    - frontend/app/semantics/page.tsx
    - frontend/components/semantic-catalog/CatalogToolbar.tsx
    - frontend/lib/semantic-catalog-view-model.mjs
    - frontend/lib/semantic-catalog-view-model.d.mts
    - frontend/lib/semantic-catalog-dom-contract.mjs
    - frontend/tests/semantic-catalog-view-model.test.mjs

key-decisions:
  - "Authorize every catalog completion with both the immutable project/query request key and retry attempt; mismatched render state synchronously becomes loading before effects run."
  - "Canonical audit bookmarks default to rejected when no audit-valid status exists, while explicitly leaving audit removes an incompatible audit-only status."
  - "Keep __uncategorized__ stable on the wire and translate it only at the presentation seam."
  - "Build restricted labels from entity_type alone through one shared table; readable unknown future types fall back to 数据资产."

patterns-established:
  - "Catalog authority seam: begin/resolve/reject/retry/scope-change events never mutate state and stale completions return the current state unchanged."
  - "Pagination seam: server page, page_size, and total produce bounded action targets before route navigation preserves the canonical query."
  - "Entity-label seam: catalog and detail DOM consumers import semantic-entity-types instead of owning local maps."

requirements-completed: [SUI-01]

coverage:
  - id: D1
    description: "The real /semantics route uses request-keyed production state, synchronously hides prior-project rows, and exposes bounded first/last pagination."
    requirement: SUI-01
    verification:
      - kind: integration
        ref: "frontend/tests/semantic-catalog-view-model.test.mjs#catalog request key, stale catalog, and catalog pagination tests"
        status: pass
      - kind: other
        ref: "npm --prefix frontend run build"
        status: pass
    human_judgment: false
  - id: D2
    description: "Audit/status state is API-valid from URL through request construction, and the uncategorized sentinel is presented as 未分类 without changing its wire value."
    requirement: SUI-01
    verification:
      - kind: unit
        ref: "frontend/tests/semantic-catalog-view-model.test.mjs#catalog audit/status and uncategorized tests"
        status: pass
    human_judgment: false
  - id: D3
    description: "Every API entity type and semantic-concept chain root resolves through one permission-safe label source used by catalog and detail references."
    requirement: SUI-01
    verification:
      - kind: unit
        ref: "frontend/tests/semantic-catalog-view-model.test.mjs#entity label and restricted reference tests"
        status: pass
    human_judgment: false

duration: 17min
completed: 2026-08-25
status: complete
---

# Phase 11 Plan 06: Truthful Catalog State and Controls Summary

**The production semantic catalog now binds every visible state to its active project/query attempt, generates only API-valid filters, reaches first and last server pages, and shares one exhaustive restricted-entity label contract.**

## Performance

- **Duration:** 17 min
- **Started:** 2026-08-25T09:47:51Z
- **Completed:** 2026-08-25T10:03:51Z
- **Tasks:** 3
- **Implementation/test files modified:** 10

## Accomplishments

- Added a pure production catalog reducer/controller and wired the real `/semantics` route around the existing `apiGet` effect with `AbortSignal` forwarding, immutable request identity, attempt-scoped retries, stale success/error rejection, and synchronous prior-scope hiding.
- Added server-authoritative first/previous/next/last pagination with bounded targets and disabled boundary actions while preserving the complete canonical catalog query.
- Canonicalized audit and lifecycle status together so bookmarks, toolbar transitions, serialized URLs, and API queries cannot produce an invalid filter tuple.
- Preserved `__uncategorized__` as the backend wire value while displaying and announcing `未分类` in catalog controls and active-filter chips.
- Extracted all twelve API binding entity types plus the semantic-concept chain root into one production label table consumed by catalog and detail restricted-reference paths.

## Task Commits

1. **Task 1 RED:** `d8a6a24` — expose out-of-order project completion, stale state, retry identity, and pagination boundary gaps.
2. **Task 1 GREEN:** `a65e598` — wire the production route to request-authoritative state and four-way pagination.
3. **Task 2 RED:** `e0c3d99` — expose invalid audit/status pairs and raw uncategorized presentation.
4. **Task 2 GREEN:** `ce1e1c1` — canonicalize audit filters and localize the sentinel presentation.
5. **Task 3 RED:** `6935bc6` — require one exhaustive entity-label source and type-only restricted labels.
6. **Task 3 GREEN:** `577d5da` — centralize catalog/detail semantic entity labels.
7. **Task 3 lint fix:** `a751d4b` — use valid declaration syntax for the runtime label constant type.

## TDD Gate Compliance

- Task 1 RED failed because the planned production controller module did not exist; GREEN added the controller, declarations, route wiring, and bounded pagination, after which all four new cases passed.
- Task 2 RED produced three behavioral failures for missing audit defaulting, incompatible audit exit, and missing localized sentinel labeling; GREEN passed all three.
- Task 3 RED produced two explicit assertions that the shared production label module was absent; GREEN passed exhaustive shared-label and type-only restricted-reference coverage.
- Every RED commit precedes its matching production commit. The final declaration-only fix followed a lint-discovered syntax defect and did not change runtime behavior.

## Files Created/Modified

- `frontend/app/semantics/page.tsx` — Production reducer consumption, request authorization, retry attempts, and four-way pagination.
- `frontend/components/semantic-catalog/CatalogToolbar.tsx` — Human-readable uncategorized option and chip labels.
- `frontend/lib/semantic-catalog-controller.mjs` / `.d.mts` — Pure request state machine and bounded pagination model.
- `frontend/lib/semantic-catalog-view-model.mjs` / `.d.mts` — Canonical audit/status transition and presentation-only domain label helper.
- `frontend/lib/semantic-entity-types.mjs` / `.d.mts` — Exhaustive shared entity-label table and type-only restricted label API.
- `frontend/lib/semantic-catalog-dom-contract.mjs` — Removed the duplicate label table and delegated restricted labels to the shared module.
- `frontend/tests/semantic-catalog-view-model.test.mjs` — Controlled A-to-B ordering, stale completion, retry, pagination, audit/status, sentinel, and entity-label regressions.

## Decisions Made

- A response is render-authorized only when both `requestKey` and `attempt` match the currently loading state; completion order and abort timing cannot grant authority.
- Render authorization is synchronous: if React still holds the previous project's success state while the project/query key changes, the visible projection is loading with no page payload before the effect runs.
- `audit=1` with no audit-valid status canonicalizes to `status=rejected`; leaving audit explicitly clears rejected/deprecated rather than silently re-entering audit.
- The wire sentinel is never translated in request state. Localization happens only through `catalogDomainLabel` in rendered controls.
- Restricted label construction accepts only `entity_type`; no identifier, display name, Code, href, or protected metadata is needed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Removed the undeclared duplicate DOM entity-label table**
- **Found during:** Task 3
- **Issue:** `semantic-catalog-dom-contract.mjs` was a required `read_first` consumer and owned a second incomplete label map, but the task file list omitted it. Leaving it untouched would violate the single-source acceptance criterion and keep four mapping/lineage restricted labels degraded.
- **Fix:** Replaced the local map with one import from `semantic-entity-types.mjs`.
- **Files modified:** `frontend/lib/semantic-catalog-dom-contract.mjs`
- **Verification:** Exhaustive entity-label test passed through both view-model and DOM restricted-reference consumers.
- **Committed in:** `577d5da`

**2. [Rule 1 - Bug] Corrected the declaration syntax for the shared runtime constant**
- **Found during:** Plan-level frontend lint
- **Issue:** The new `.d.mts` used `export const` without `declare`, which Next lint parsed as a missing initializer.
- **Fix:** Changed it to `export declare const` without altering runtime behavior.
- **Files modified:** `frontend/lib/semantic-entity-types.d.mts`
- **Verification:** `npm --prefix frontend run lint` exited 0; focused and complete tests remained green.
- **Committed in:** `a751d4b`

---

**Total deviations:** 2 auto-fixed (1 missing critical, 1 bug).  
**Impact on plan:** Both changes were necessary to satisfy the declared single-source contract and frontend verification; no package, backend, route, schema, or unrelated application scope was added.

## Automated Test Results

- Focused 11-06 controller/filter/label gate — **20 passed**.
- Complete frontend Node suite — **60 passed**.
- Frontend production build — **passed**; `/semantics` and `/semantics/[id]` were emitted.
- Frontend lint — **passed** with only the repository's pre-existing unrelated Hook dependency warnings.

## Security and Threat Coverage

- T-11-06-01 closed by synchronous render authorization plus reducer guards on every success and error completion.
- T-11-06-02 closed by one audit/status normalization path shared by parse, transitions, serialization, toolbar state, and API query construction.
- T-11-06-03 closed by a pure pagination model that clamps every boundary target before navigation and disables first/previous or next/last actions at their edges.
- Restricted entity labels require `entity_type` only and do not consume protected identifiers or metadata.
- No endpoint, auth path, backend file, package, schema, migration, persistence, or production operation was introduced.

## Known Stubs

None. Empty strings, nullable filter values, and empty state payloads in the touched files are canonical query defaults or explicit idle/loading/error state, not unwired data.

## Issues Encountered

- The first Task 1 production build exposed a TypeScript structural mismatch because the controller state intentionally stores nullable page/error fields while the legacy response-kind declaration accepts omitted fields. The route now passes an explicit non-null view, keeping both public contracts narrow.
- Next lint reports longstanding Hook dependency warnings in unrelated routes. They predate 11-06, did not involve any plan file, and remain outside scope.

## User Setup Required

None - no dependency, environment variable, service, migration, or manual configuration was added.

## Next Phase Readiness

- Plan 11-07 can consume the shared `semantic-entity-types.mjs` label seam while completing lawful lineage links and detail disclosures.
- Plan 11-08 can exercise the real production route with controlled browser fetches; the route no longer uses a fixture-only parallel state path.
- Plan 11-09 can qualify security/UI/human gates after the remaining detail and browser interaction plans complete.
- User homepage, AppShell, workspace, config, catalog route, backend, and unrelated untracked WIP remained outside every 11-06 commit.

## Self-Check: PASSED

All ten implementation/test files, this summary, and commits `d8a6a24`, `a65e598`, `e0c3d99`, `ce1e1c1`, `6935bc6`, `577d5da`, and `a751d4b` were found. The coverage classifier accepted all three deliverables as automatically covered. The realized plan diff contains no deletions, package/backend/catalog-route changes, or staged user WIP; deviation ledger entries 11 and 12 are recorded as fixed.

---
*Phase: 11-semantic-catalog-ui*
*Completed: 2026-08-25*
