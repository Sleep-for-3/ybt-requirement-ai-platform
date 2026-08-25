---
phase: 11-semantic-catalog-ui
plan: 07
subsystem: ui
tags: [nextjs, react, semantic-detail, lineage, provenance, accessibility, tdd]

requires:
  - phase: 11-semantic-catalog-ui
    plan: 05
    provides: institution-isolated detail projections and truthful reference DTOs
  - phase: 11-semantic-catalog-ui
    plan: 06
    provides: shared exhaustive semantic entity labels and request-authoritative detail state
provides:
  - exact byte-preserving allowlist for both backend canonical lineage query shapes
  - bounded complete conflict-source provenance separated from formal truth
  - stable independent three-line and six-line accessible disclosures with exact expanded text
affects: [11-08, 11-09, semantic-detail-ui, lineage-navigation]

actuals:
  tokens: 8951
  tasks: 3
  commits: 7

tech-stack:
  added: []
  patterns:
    - exact local URL tuple validation before rendering backend-provided navigation
    - stable semantic type-and-id disclosure identities with component-local expansion state
    - bounded evidence presentation that preserves exact source text only in expanded state

key-files:
  created:
    - frontend/components/semantic-catalog/EvidenceDisclosure.tsx
    - frontend/lib/semantic-detail-contract.mjs
    - frontend/lib/semantic-detail-contract.d.mts
    - frontend/tests/semantic-detail-contract.test.mjs
  modified:
    - frontend/app/semantics/[id]/page.tsx
    - frontend/components/semantic-catalog/BindingList.tsx
    - frontend/components/semantic-catalog/SemanticDetailHeader.tsx

key-decisions:
  - "Treat the threat table's single-query-key shorthand as one selector plus the two mandatory provenance keys: from=semantics and the matching semanticConceptId."
  - "Preserve a lawful backend href byte-for-byte after validation; never rebuild, reorder, or infer a lineage destination."
  - "Render restricted references from entity_type and restricted=true only; readable but unsupported destinations retain their lawful display label as nonnavigable text."
  - "Keep each long conflict/evidence item in its own native-button disclosure with an identity derived from stable domain keys, never list position alone or a random runtime ID."

patterns-established:
  - "Lineage navigation seam: /lineage accepts exactly three query entries, one supported selector, one from=semantics, and one current-concept match."
  - "Disclosure seam: collapsed content is deterministically bounded, aria-controls always targets a stable region, and expanded content equals the original source text."

requirements-completed: [SUI-02]

coverage:
  - id: D1
    description: "Both backend canonical lineage URL shapes navigate unchanged while malformed, duplicated, unknown, mismatched, fragmented, and external forms remain text-only."
    requirement: SUI-02
    verification:
      - kind: unit
        ref: "frontend/tests/semantic-detail-contract.test.mjs#lineage query tests"
        status: pass
    human_judgment: false
  - id: D2
    description: "Conflict banners expose all attributed sources in stable order without moving any evidence into the formal definition region."
    requirement: SUI-02
    verification:
      - kind: unit
        ref: "frontend/tests/semantic-detail-contract.test.mjs#conflict source tests"
        status: pass
    human_judgment: false
  - id: D3
    description: "The production evidence region uses stable independent disclosures whose expanded state returns exact original text."
    requirement: SUI-02
    verification:
      - kind: integration
        ref: "frontend/app/semantics/[id]/page.tsx#EvidencePartition"
        status: pass
      - kind: other
        ref: "npm --prefix frontend run build"
        status: pass
    human_judgment: false

duration: 47min
completed: 2026-08-25
status: complete
---

# Phase 11 Plan 07: Lawful Detail Traceability and Accessible Disclosure Summary

**The production semantic detail view now follows every authorized canonical lineage URL exactly, exposes complete attributed conflict provenance, and bounds long evidence behind stable independent accessible controls without weakening formal-truth or restricted-data boundaries.**

## Performance

- **Duration:** 47 min, including the approved tracer verification checkpoint
- **Started:** 2026-08-25T10:11:26Z
- **Completed:** 2026-08-25T10:58:24Z
- **Tasks:** 3
- **Implementation/test files modified:** 7

## Accomplishments

- Accepted the exact backend-emitted `scenarioTechnicalLineageId` and `nodeId` query shapes only when one selector, `from=semantics`, and the current `semanticConceptId` are each present exactly once.
- Preserved every approved href byte-for-byte and rejected duplicates, both selectors, unknown keys, mismatched concepts, missing/empty fields, fragments, external origins, malformed encodings, and wrong paths.
- Kept readable unsupported references useful as nonnavigable name/Code/type text, while restricted references reduce to translated `entity_type` plus `受限` with no identifier or protected metadata.
- Rendered the first two conflict sources persistently, exposed every overflow source through a native-button disclosure, and independently bounded long source summaries to three lines.
- Reused one production disclosure for six-line evidence bounds, stable type/id control and panel IDs, component-local expansion state, exact full text, and clean short/empty states.
- Wired current concept identity into both Binding and Lineage production references so both canonical lineage selector forms are actually reachable.

## Task Commits

1. **Task 1 RED:** `08ff7ca` — expose unsafe lineage-query and restricted-reference handling.
2. **Task 1 GREEN:** `3c52c2f` — validate canonical lineage tuples and render safe reference models.
3. **Task 2 RED:** `141686e` — expose missing conflict source order, overflow, and long-summary disclosure.
4. **Task 2 GREEN:** `847da67` — render complete bounded conflict provenance with reusable accessible controls.
5. **Task 3 RED:** `d04d93f` — expose unbounded evidence and unstable multi-item disclosure behavior.
6. **Task 2 follow-up fix:** `bec1d62` — scope source disclosure identities across multiple conflict banners.
7. **Task 3 GREEN:** `a9200b6` — wire bounded evidence and canonical node lineage links into the production detail route.

## TDD Gate Compliance

- Task 1 RED failed because `semantic-detail-contract.mjs` did not exist; GREEN passed four lineage/restricted contract cases and the production build.
- Task 2 RED failed on missing `boundedDisclosureModel` and conflict-source exports; GREEN passed stable ordering, empty, long-summary, and overflow cases.
- Task 3 RED failed on the missing evidence-specific disclosure contract; GREEN passed exact expansion, stable/unique IDs, independent state, short text, and empty evidence cases.
- Every RED commit precedes its corresponding GREEN commit. No refactor commit was needed.

## Files Created/Modified

- `frontend/lib/semantic-detail-contract.mjs` / `.d.mts` — exact destination validation, safe reference render models, conflict collection bounds, and stable disclosure models.
- `frontend/components/semantic-catalog/BindingList.tsx` — current-concept-aware safe navigation plus separate readable and restricted branches.
- `frontend/components/semantic-catalog/SemanticDetailHeader.tsx` — persistent attributed source rows, overflow disclosure, and formal-definition separation.
- `frontend/components/semantic-catalog/EvidenceDisclosure.tsx` — reusable native-button disclosure with stable control/panel association and local state.
- `frontend/app/semantics/[id]/page.tsx` — production evidence integration and current-concept-aware node lineage links.
- `frontend/tests/semantic-detail-contract.test.mjs` — adversarial URL, redaction, conflict, and multi-item evidence contract coverage.

## Decisions Made

- An approved lineage query contains exactly three entries: one selector and the two required provenance keys. The threat register's singular wording never means provenance may be omitted.
- Selector values must be nonempty, and `semanticConceptId` must match the positive current detail concept exactly after URL parsing.
- Already supported internal destinations remain unchanged; only the exact `/lineage` query route receives the new tuple validation.
- Restricted references never read or infer entity ID, display fields, destination, title, source content, or metadata, even if an adversarial runtime object carries those fields.
- Long text is bounded deterministically at the presentation seam; the expanded region uses the original string unchanged.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Scoped conflict source disclosure IDs across multiple banners**
- **Found during:** Task 3 acceptance review
- **Issue:** A source type/id pair repeated under two distinct conflicts could create duplicate DOM control/panel IDs.
- **Fix:** Included the stable conflict key in each source disclosure identity while preserving source order and text.
- **Files modified:** `frontend/components/semantic-catalog/SemanticDetailHeader.tsx`
- **Commit:** `bec1d62`

---

**Total deviations:** 1 auto-fixed bug.  
**Impact on plan:** The fix strengthens the declared stable-ID and independent multi-item contract without changing API, backend, route, package, or governance scope.

## Automated Test Results

- Task 1 focused lineage/restricted gate — **64 passed** at tracer verification.
- Task 2 focused conflict-source gate — **68 passed**.
- Task 3 focused evidence-disclosure gate — **71 passed**.
- Plan-level lineage/conflict/restricted/evidence gate — **71 passed**.
- Complete frontend Node suite — **71 passed**.
- Frontend lint — **passed** with only pre-existing Hook dependency warnings in unrelated routes.
- Frontend production build — **passed**; `/semantics` and `/semantics/[id]` emitted successfully.

## Security and Threat Coverage

- T-11-07-01 closed by exact local path, three-entry query, selector exclusivity, provenance multiplicity/value, current-concept, fragment, origin, encoding, and unknown-key checks.
- T-11-07-02 closed by attributed source-only conflict presentation that remains above and structurally separate from the canonical formal definition.
- T-11-07-03 closed by a strict type-only restricted render model whose serialized output contains no identifier, name, Code, href, title, source content, or metadata.
- No unplanned endpoint, auth path, schema, file-access pattern, backend behavior, package, graph, governance mutation, or production operation was introduced.

## Known Stubs

None. Empty source lists, empty disclosure text, nullable hrefs, and default arrays are explicit safe-empty or nonnavigable contract states, not unwired data.

## Issues Encountered

- The initial adversarial Task 1 test incorrectly rejected the already authorized `/lineage/fields/{id}` route. The test was corrected before GREEN to honor the plan's requirement to preserve existing internal destinations unchanged.
- The tracer checkpoint was emitted because auto-advance was disabled; execution resumed after explicit approval with both Task 1 commits verified.

## User Setup Required

None - no package, environment variable, service, migration, backend change, or manual configuration was added.

## Next Phase Readiness

- Plan 11-08 can exercise the production components and keyboard behavior through its real-browser interaction harness.
- Plan 11-09 can run the final security, UI, and human qualification gates with lawful lineage and disclosure gaps closed.
- User homepage, AppShell, workspace, config, backend, and unrelated untracked WIP remained outside all seven implementation/test commits.

## Self-Check: PASSED

All seven created/modified implementation and test files, this summary, and commits `08ff7ca`, `3c52c2f`, `141686e`, `847da67`, `d04d93f`, `bec1d62`, and `a9200b6` were found. The realized implementation diff contains no deletions, backend/package/schema/governance changes, or staged user WIP; deviation ledger entry 13 is recorded as fixed.
