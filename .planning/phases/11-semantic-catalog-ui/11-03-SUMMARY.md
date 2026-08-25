---
phase: 11-semantic-catalog-ui
plan: 03
subsystem: ui
tags: [nextjs, react, semantic-catalog, temporal, accessibility, security, tdd]

requires:
  - phase: 11-semantic-catalog-ui
    plan: 02
    provides: canonical catalog URL/return state, typed API client, and governed catalog navigation
  - phase: 11-semantic-catalog-ui
    plan: 04
    provides: strict detail shell and independently authorized lazy-region DTOs
provides:
  - canonical effective-version semantic detail shell with durable temporal and tab URL state
  - independent permission-aware bindings, relations, evidence, lineage, governance, and version regions
  - permission-minimized references, confirmed-only bounded chains, and audit/candidate separation
  - shared DOM/keyboard contract with serialized accessibility and state-transition regressions
affects: [phase-12-requirement-workspace, phase-13-dashboard, semantic-detail-ui, phase-ui-review]

actuals:
  tokens: 20622
  tasks: 3
  commits: 6

tech-stack:
  added: []
  patterns:
    - URL-backed semantic detail state with full request identity and stale-response rejection
    - strict shell plus independent lazy region state machines
    - shared dependency-free DOM contract consumed by React components and Node/ReactDOMServer tests
    - pre-render restricted-reference minimization and confirmed-only bounded chain projection

key-files:
  created:
    - frontend/app/semantics/[id]/page.tsx
    - frontend/components/semantic-catalog/SemanticDetailHeader.tsx
    - frontend/components/semantic-catalog/SemanticTabs.tsx
    - frontend/components/semantic-catalog/AsyncRegion.tsx
    - frontend/components/semantic-catalog/TrustSourceRegion.tsx
    - frontend/components/semantic-catalog/BindingList.tsx
    - frontend/components/semantic-catalog/BindingChain.tsx
    - frontend/components/semantic-catalog/RelationList.tsx
    - frontend/components/semantic-catalog/VersionTimeline.tsx
    - frontend/lib/semantic-catalog-dom-contract.mjs
    - frontend/tests/semantic-catalog-dom.test.mjs
  modified:
    - frontend/lib/semantic-catalog-view-model.mjs
    - frontend/lib/semantic-catalog-view-model.d.mts
    - frontend/tests/semantic-catalog-view-model.test.mjs

key-decisions:
  - "Keep formal meaning exclusively on the server-selected confirmed SemanticConceptVersion; candidate and AI content render only in explicit non-formal regions."
  - "Bind every shell and region response to project, concept, date, audit mode, and region identity before committing or rendering it."
  - "Use the backend discriminated restricted reference as a type-only render branch so protected identifiers and metadata never enter links or accessibility text."
  - "Share tab, panel, retry, disclosure, redaction, and chain contracts between production React components and direct Node tests."

patterns-established:
  - "Detail isolation: optional region 403/error/empty states never unmount or redefine the canonical shell."
  - "Temporal presentation: as_of controls formal meaning; current-only regions carry an explicit local historical disclaimer."
  - "Accessibility contract: URL-backed tabs use stable tab/panel IDs and pure keyboard controllers for ArrowLeft/ArrowRight/Home/End."

requirements-completed: [SUI-02]

coverage:
  - id: D1
    description: "The detail route renders canonical temporal meaning first and independently loads all governed lazy regions without formal fallback to legacy or AI fields."
    requirement: SUI-02
    verification:
      - kind: unit
        ref: "frontend/tests/semantic-catalog-view-model.test.mjs#semantic-detail shell, URL, request identity, and lazy region tests"
        status: pass
      - kind: integration
        ref: "backend/tests/test_semantic_catalog_api.py#strict shell and lazy detail route contract"
        status: pass
      - kind: other
        ref: "npm --prefix frontend run build"
        status: pass
    human_judgment: false
  - id: D2
    description: "Bindings, relations, evidence, lineage, governance, versions, trust, candidates, audit history, and confirmed-only bounded chains render truthful status partitions."
    requirement: SUI-02
    verification:
      - kind: unit
        ref: "frontend/tests/semantic-catalog-dom.test.mjs#SUI-14 through SUI-24 and SUI-27 through SUI-28"
        status: pass
      - kind: integration
        ref: "python -m pytest backend/tests/test_semantic_catalog_api.py -q"
        status: pass
    human_judgment: false
  - id: D3
    description: "Restricted references, tabs, loading/403/error/conflict markup, retry, disclosure, and keyboard focus/selection share one serialized DOM contract."
    requirement: SUI-02
    verification:
      - kind: automated_ui
        ref: "frontend/tests/semantic-catalog-dom.test.mjs#SUI-22, SUI-23, and SUI-25 ReactDOMServer and pure-controller tests"
        status: pass
      - kind: other
        ref: "npm --prefix frontend run lint"
        status: pass
    human_judgment: true
    rationale: "Final density, wrapping, horizontal overflow, and visible focus treatment at the approved viewport sizes still require the phase UI review's live browser judgment."

duration: 29min
completed: 2026-08-25
status: complete
---

# Phase 11 Plan 03: Governed Semantic Detail UI Summary

**Canonical temporal semantic detail with independently authorized traceability regions, permission-minimized references, bounded chain/timeline views, and directly tested DOM and keyboard contracts**

## Performance

- **Duration:** 29 min
- **Started:** 2026-08-25T06:04:51Z
- **Completed:** 2026-08-25T06:33:21Z
- **Tasks:** 3
- **Files modified:** 14 implementation/test files

## Accomplishments

- Built `/semantics/[id]` on the Plan 11-04 canonical shell so successful absence is `暂无正式版本`, AI/draft definitions remain candidate-only, historical `as_of` state is durable, and conflicts never receive a false winner.
- Added URL-backed accessible tabs and independent `idle | loading | success-empty | success-populated | forbidden | error` regions with stable skeletons, local retry, full request identity, aborts, and late/stale response rejection.
- Rendered trust/provenance, lifecycle versus review workflow, bindings, relations, evidence, knowledge, lineage, governance, questions, audit history, and chronological inline version disclosure without adding mutation controls or a graph dependency.
- Rendered restricted references only as translated entity type plus `受限`; confirmed-only chains are capped, report overflow, and include a complete list/text equivalent.
- Added ReactDOMServer and pure-controller regressions for SUI-11 through SUI-28, including direct ArrowLeft/ArrowRight/Home/End, focus/selection, disclosure, retry, 403/error/conflict markup, and restricted JSON/DOM/accessibility absence.

## Task Commits

1. **Task 1 RED: Define semantic detail shell and region states** - `ecb4838` (test)
2. **Task 1 GREEN: Build canonical semantic detail shell** - `87766ad` (feat)
3. **Task 2: Render governed semantic traceability regions** - `2558bc2` (feat)
4. **Task 3 RED: Define semantic detail DOM and keyboard contract** - `5f00ae4` (test)
5. **Task 3 GREEN: Enforce semantic detail DOM and keyboard contracts** - `2bab964` (feat)
6. **Rule 1 correction: Reject stale semantic shell identity** - `826f3e1` (fix)

## TDD Gate Compliance

- Task 1 RED (`ecb4838`) failed because the shell/region request and state exports did not exist; Task 1 GREEN (`87766ad`) passed all 43 then-current frontend tests and the production build.
- Task 3 RED (`5f00ae4`) failed with `ERR_MODULE_NOT_FOUND` for the planned shared DOM adapter; Task 3 GREEN (`2bab964`) passed 51 frontend tests, production build, and lint.
- The post-implementation stale-identity regression was added before the Rule 1 fix and remains green in the complete suite.

## Files Created/Modified

- `frontend/app/semantics/[id]/page.tsx` - Project-scoped shell loading, URL temporal/tab state, independent lazy orchestration, and all region composition.
- `frontend/components/semantic-catalog/SemanticDetailHeader.tsx` - Canonical definition, historical banner, governance summary, candidates, and persistent conflict alert.
- `frontend/components/semantic-catalog/SemanticTabs.tsx` - URL-backed WAI-ARIA tabs using the shared keyboard/ID contract.
- `frontend/components/semantic-catalog/AsyncRegion.tsx` - Local loading, empty, forbidden, error, and retry presentation.
- `frontend/components/semantic-catalog/TrustSourceRegion.tsx` - Lifecycle, workflow, authority, provenance, interval, confirmation, and conflict presentation.
- `frontend/components/semantic-catalog/BindingList.tsx` - Trusted/candidate/audit partitions and type-only restricted references.
- `frontend/components/semantic-catalog/BindingChain.tsx` - Capped Concept-to-Target-to-Mart-to-Source visualization and text equivalent.
- `frontend/components/semantic-catalog/RelationList.tsx` - Directional concept relationships partitioned by governance status.
- `frontend/components/semantic-catalog/VersionTimeline.tsx` - Oldest-to-newest inline disclosure with selected-date/current/audit markers.
- `frontend/lib/semantic-catalog-dom-contract.mjs` - Shared tab, panel, retry, disclosure, restricted-reference, chain, and SSR fixture contract.
- `frontend/lib/semantic-catalog-view-model.mjs` / `.d.mts` - Detail DTO declarations, URL/request identity, state transitions, partitions, ordering, and labels.
- `frontend/tests/semantic-catalog-dom.test.mjs` - Serialized DOM/accessibility plus keyboard/retry/disclosure transition coverage.
- `frontend/tests/semantic-catalog-view-model.test.mjs` - Shell, URL, request, region, and stale identity regressions.

## Decisions Made

- The detail page derives audit access only from the safe catalog `returnTo` audit state; it does not invent a separate mutation or governance mode.
- A server success with no effective confirmed version is a formal absence, not an excuse to use legacy projection or AI candidate text.
- Current-only region disclaimers remain local to bindings, relations, evidence, lineage, or governance rather than making the historical shell ambiguous.
- Backend-provided canonical routes are accepted only through the existing local destination allow-list; unsupported references show `尚无可导航详情`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Kept the planned runtime-only DOM adapter inside the exact file scope**
- **Found during:** Task 3 GREEN production build
- **Issue:** The plan required `semantic-catalog-dom-contract.mjs` but did not allow a same-basename `.d.mts`; strict Next.js type checking rejected TSX imports of the runtime module.
- **Fix:** Added precise import-site `@ts-expect-error` annotations in the five planned consumers, each documenting that the runtime surface is verified directly by Node/ReactDOMServer tests. No plan-external declaration file was introduced.
- **Files modified:** `AsyncRegion.tsx`, `SemanticTabs.tsx`, `BindingList.tsx`, `BindingChain.tsx`, `VersionTimeline.tsx`
- **Verification:** 51 frontend tests, production build, and lint passed.
- **Committed in:** `2bab964`

**2. [Rule 1 - Security Bug] Prevented prior-project shell identity from rendering during context switches**
- **Found during:** Plan-level security review after Task 3
- **Issue:** A project/concept/date change could render the previous successful shell for one React render before the loading effect cleared it.
- **Fix:** Stored full shell request identity on every state and made mismatched identity render as loading immediately; the request coordinator still aborts and rejects late work.
- **Files modified:** `page.tsx`, `semantic-catalog-view-model.mjs`, `.d.mts`, and the focused view-model test
- **Verification:** Stale success identity regression, 51 frontend tests, and the final production build passed.
- **Committed in:** `826f3e1`

---

**Total deviations:** 2 auto-fixed (1 blocking type-integration issue, 1 security correctness bug).
**Impact on plan:** Both fixes preserve the planned file and architecture boundaries; no package, backend contract, mutation path, or extra data surface was added.

## Verification Results

- `PYTHONPATH=backend python -m pytest backend/tests/test_semantic_catalog_api.py -q` - **16 passed**.
- `npm --prefix frontend test` - **51 passed, 0 failed, 0 skipped**.
- `npm --prefix frontend test -- --test-name-pattern="semantic-catalog-dom|semantic-catalog"` - **51 passed**; the repository's Node script executes the full test glob and all semantic tests are named directly.
- `npm --prefix frontend run build` - **passed**; compiled, typechecked, generated 41 static pages, and emitted `/semantics/[id]` at 10.1 kB / 115 kB first load.
- `npm --prefix frontend run lint` - **passed**. Existing `react-hooks/exhaustive-deps` warnings remain only in unrelated routes; no warning originates in Plan 11-03 files.
- Keyboard/DOM evidence directly covers ArrowLeft, ArrowRight, Home, End, focus/selection, version disclosure, retry transitions, tab/panel ARIA wiring, loading/403/error/conflict roles, restricted data absence, and bounded-chain overflow text.
- Live human viewport judgment was not fabricated in this autonomous executor; it remains explicitly routed to the phase UI review, consistent with Plan 11-02's visual follow-up.

## Known Stubs

None. Every region uses the real strict API, and successful empty values are modeled states rather than mock or deferred data.

## Threat Flags

None. The page consumes only the detail/lazy API, permission-safe DTO, temporal URL, and DOM boundaries already enumerated by T-11-10 through T-11-14.

## Issues Encountered

- Next.js continues to report pre-existing Hook dependency warnings in unrelated routes. They did not fail lint, build, type checking, or static generation and were outside the allowed scope.
- The live viewport inspection needs an authenticated project with representative semantic fixtures and is reserved for the phase UI review; all deterministic keyboard and serialized DOM contracts are automated here.

## User Setup Required

None - no packages, environment variables, migrations, external services, or governance mutations were added.

## Next Phase Readiness

- SUI-02 implementation and deterministic verification are complete; Phase 12 can link Requirement Workspace facts to `/semantics/{id}` while preserving canonical `returnTo` state.
- Phase UI review should inspect long definitions, horizontal tab overflow, focus treatment, conflict banners, restricted placeholders, and bounded chains at the approved viewport sizes.

## Self-Check: PASSED

All 14 implementation/test files and commits `ecb4838`, `87766ad`, `2558bc2`, `5f00ae4`, `2bab964`, and `826f3e1` were found. The plan range contains no file deletions and no code changes outside the allowed 11-03 files.

---
*Phase: 11-semantic-catalog-ui*
*Completed: 2026-08-25*
