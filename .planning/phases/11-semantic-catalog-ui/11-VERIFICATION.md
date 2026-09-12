---
phase: 11-semantic-catalog-ui
verified: 2026-08-25T15:23:56Z
status: human_needed
score: 12/13 must-haves verified
behavior_unverified: 1
overrides_applied: 0
requirement_statuses:
  SUI-01: satisfied_automated
  SUI-02: satisfied_automated
re_verification:
  previous_status: gaps_found
  previous_score: 6/13
  gaps_closed:
    - "CR-01: catalog render state is request-keyed and synchronously clears stale project/query data."
    - "CR-02: canonical versions and every institution-bearing subordinate semantic query are scoped to the authorized Project institution."
    - "WR-01/02/03/09: confirmed relation semantics, uncategorized filtering, audit/status URL state, and first/last pagination are truthful."
    - "WR-04/05/07/08: lawful lineage links, conflict sources, exhaustive restricted labels, and accessible evidence disclosures are production-wired."
    - "WR-06: real production routes/components are exercised by a browser harness with deferred network completions."
  gaps_remaining: []
  regressions: []
behavior_unverified_items:
  - truth: "Catalog and detail layouts remain coherent and visibly keyboard-operable at 320x720, 768x1024, 1280x800, and 1440x900."
    test: "Inspect representative populated, empty, forbidden, conflict, historical, restricted-reference, long-definition, table, tab, and bounded-chain states at all four approved viewports; traverse the visible controls by keyboard."
    expected: "No unintended page overflow or overlap; only deliberate table/tab scrolling; visible focus; readable wrapping; stable skeletons; conflict/history/current-only notices remain visible; the bounded chain is nonblank and its list order matches the visual order."
    why_human: "The production browser suite proves DOM, focus state, keyboard transitions, and long-content availability at its automated viewport, but not rendered geometry, visual density, or visible focus treatment across all four approved viewport sizes."
human_verification:
  - test: "Complete the Phase 11 responsive catalog/detail matrix at 320x720, 768x1024, 1280x800, and 1440x900, including keyboard-only traversal."
    expected: "All layouts, scroll boundaries, focus rings, long text, banners, disclosures, tabs, table, and bounded chain remain coherent and visibly operable."
    why_human: "Visual geometry and focus visibility require live human judgment; no canonical 11-UI-REVIEW.md exists yet."
---

# Phase 11: Semantic Catalog UI Verification Report

**Phase Goal:** 在现有 Next.js 与 Design Tokens 中提供完整语义目录和详情体验。  
**Verified:** 2026-08-25T15:23:56Z
**Status:** HUMAN NEEDED
**Re-verification:** Yes — after closure of the prior 2 Critical and 9 Warning findings

## Verdict

The previous four grouped automated gaps are closed in the current code. The verifier independently traced the repaired production wiring and reran the behavior-dependent high-risk paths: institution/project isolation, temporal truth, rejected/deprecated isolation, confirmed relation semantics, uncategorized filtering, request-key stale-state clearing, audit/status canonicalization, pagination, lawful lineage navigation, conflict provenance, restricted DTO/DOM absence, independent disclosures, production keyboard interaction, and browser teardown.

The phase is not marked `passed` because the required human viewport/visible-focus review has not occurred. Under the verifier decision tree, one non-empty human-verification item makes the overall status `human_needed`, even though no automated implementation gap remains.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Current evidence |
|---:|---|---|---|
| 1 | `/semantics` and `/semantics/{id}` use registered authenticated routes and render real API projections. | ✓ VERIFIED | `backend/app/main.py:185` registers the secured router; catalog/detail pages call shared `apiGet`; the unchanged source HEAD previously passed the production build, and the current real-route browser suite passed 12/12. |
| 2 | Catalog/detail data remains project- and institution-isolated, including subordinate rows and project switches. | ✓ VERIFIED | `resolve_effective_versions` distinguishes omitted/integer/explicit-null institution scope; Phase 11 calls pass `project.institution_id`; `_institution_scope` guards versions, bindings, relations, questions, audits, lineage nodes/edges. Current focused API isolation tests and real project-switch browser tests passed. |
| 3 | Server search, filters, totals, facets, relation counts, URL state, and pagination represent one truthful population. | ✓ VERIFIED | Confirmed source/target aliases are required for relation aggregates; `__uncategorized__` maps null/trimmed-blank domains; audit/status normalize together; four-way pagination is server-metadata bounded. Current focused backend/view-model/browser tests passed. |
| 4 | The grouped directory and comparison table render server-provided governed summaries with separate lifecycle/review dimensions. | ✓ VERIFIED | Production components consume the page DTO without global client filtering; lifecycle, review, and audit mode remain separate; grouping keeps `未分类` last. |
| 5 | Formal meaning comes only from the confirmed effective `SemanticConceptVersion`, with inclusive `as_of`, ambiguity handling, and no legacy/AI fallback. | ✓ VERIFIED | Canonical resolver is server-side; shell formal version is nullable; candidate content has a separate warning region. Current inclusive-boundary/ambiguity test passed. |
| 6 | Confirmed/candidate/audit lifecycle, Pending Review workflow, and unresolved-question lifecycle stay distinct. | ✓ VERIFIED | Central status partitions, `audit.read`, audit-only DTOs, and `open/assigned/answered` unresolved-question policy are production-wired; rejected/deprecated remain non-current. |
| 7 | Restricted references are minimized before serialization and optional region permissions fail with explicit HTTP 403. | ✓ VERIFIED | Strict `extra="forbid"` restricted DTOs contain only `entity_type` and `restricted=true`; current three-test DTO/permission gate and browser DOM/attribute/link/AX absence case passed. |
| 8 | Bindings, relations, evidence/knowledge, lineage, governance, and versions are traceable through lawful destinations and bounded displays. | ✓ VERIFIED | Exact `/lineage` selector/provenance/current-concept validation preserves lawful href bytes; readable unsupported references remain text; evidence, chain, and timeline bounds are production-wired. Current contract and browser tests passed. |
| 9 | Conflicts and open questions remain inspectable without a false winner. | ✓ VERIFIED | Header renders stable source summaries, bounded overflow, and exact long-summary disclosure; `winner` is structurally `None`; browser conflict expansion passed. |
| 10 | Required loading/empty/error/unauthorized/no-binding/conflict/pending/audit/historical states are tested through production routes/components. | ✓ VERIFIED | The CDP suite navigated real `/semantics` and `/semantics/42`, intercepted only APIs, and passed all 12 named production-route cases with zero skips. |
| 11 | URL/bookmark and async request identity prevent unsafe state or stale project/query rendering. | ✓ VERIFIED | Catalog render derives `visibleState` through `catalogStateForScope`; reducer authorizes success/error by request key plus attempt; detail shell/regions use full request identities and abort/accept guards. Current reducer and browser race tests passed. |
| 12 | The read model is projection-only, bounded, set-based, and adds no fact store, migration, index, graph package, mutation workflow, or Phase 12+ implementation. | ✓ VERIFIED | Phase diff adds no model/migration/package/lockfile; semantic catalog router has GET routes only. Current 701-concept check used 7 statements, 86.43 ms, and the existing project index. User-owned workspace/AppShell WIP is excluded from the Phase 11 commit range. |
| 13 | Responsive geometry and visible keyboard operation satisfy the approved four-viewport contract. | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | Keyboard/focus transitions pass in the real browser, but exact 320x720, 768x1024, 1280x800, and 1440x900 geometry/focus visibility has not received canonical live UI review. |

**Score:** 12/13 truths verified; 1 present but visual/behavior-unverified.

## Previous Gap Closure

| Finding | Status | Re-verification evidence |
|---|---|---|
| CR-01 prior-project catalog render | CLOSED | Production reducer and route use immutable request identity; real ProjectSelector A→B, late-success, and late-error browser cases passed. |
| CR-02 subordinate institution bypass | CLOSED | Resolver and subordinate queries apply equality-or-null institution scope; same-project foreign-institution version/partition tests passed. |
| WR-01 relation count accepts draft/foreign endpoint | CLOSED | Relation aggregate joins two confirmed, institution-visible concept aliases; named API test passed. |
| WR-02 uncategorized facet cannot filter | CLOSED | Wire sentinel maps null/trimmed blank server-side and `未分类` presentation client-side; named API and browser cases passed. |
| WR-03 audit/status URL yields 422 | CLOSED | One normalization state machine produces API-valid tuples; focused view-model and production-browser canonicalization passed. |
| WR-04 lineage href rejected | CLOSED | Exact `/lineage` pathname and three-entry query contract accepts both production shapes byte-for-byte; adversarial URL tests passed. |
| WR-05 conflict sources omitted | CLOSED | Production header renders first two sources plus accessible overflow and long-summary disclosures; browser case passed. |
| WR-06 fixture-only DOM tests | CLOSED | New CDP harness exercises the real routes, contexts, effects, components, events, focus, and intercepted `apiGet` traffic. |
| WR-07 restricted label drift | CLOSED | One exhaustive `semantic-entity-types.mjs` table serves catalog, detail, and DOM contracts; all API types are tested. |
| WR-08 evidence has no disclosure | CLOSED | `EvidenceDisclosure` uses stable per-item IDs, `aria-expanded`, `aria-controls`, local state, 6-line bounds, and exact expanded text; two-item browser case passed. |
| WR-09 missing first/last pagination | CLOSED | Production pagination exposes bounded first/previous/next/last controls for more than five pages; browser boundary case passed. |

## Required Artifacts

| Artifact | Existence / substance | Wiring / data | Status |
|---|---|---|---|
| `backend/app/schemas/semantic_catalog.py` | Strict catalog/detail/lazy DTOs and discriminated restricted unions | Response models for all read routes | ✓ VERIFIED |
| `backend/app/services/semantic/catalog_query_service.py` | Real set-based query/projection service; no static fact fallback | Canonical semantic/version/binding/relation/evidence/lineage/governance stores flow into DTOs with project/institution predicates | ✓ VERIFIED |
| `backend/app/api/semantic_catalog.py` | Eight authenticated GET routes, bounded inputs, permission gates | Registered under secured `/api`; delegates to the query service | ✓ VERIFIED |
| `backend/tests/test_semantic_catalog_api.py` | 20 focused API/DTO/security/performance tests | Current 10 selected high-risk tests passed across two verifier runs | ✓ VERIFIED |
| `frontend/app/semantics/page.tsx` | Real catalog route and all state branches | Shared `apiGet`, production controller, toolbar, directory/table, and pagination | ✓ VERIFIED |
| Catalog components/view models | Substantive URL, status, grouping, table, filter, entity-label, and request-authority logic | Wired into the production route and exercised by real browser interactions | ✓ VERIFIED |
| `frontend/app/semantics/[id]/page.tsx` and detail components | Real shell plus independently loaded governed regions | Strict region APIs, current-concept-safe links, disclosures, tabs, and request keys | ✓ VERIFIED |
| `frontend/tests/semantic-catalog-browser-harness.mjs` / `.test.mjs` | Bounded first-party CDP harness and 12 production-route cases | Starts installed Next and Edge/Chrome; teardown removes processes/profiles | ✓ VERIFIED |
| `11-GAP-QUALIFICATION.md` | Exactly 43 unique evidence rows | Every production path and evidence artifact exists; every markdown anchor resolves | ✓ VERIFIED |

## Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `main.py` | `api/semantic_catalog.py` | secured router registration | WIRED | Registered at `main.py:185`; semantic catalog declares GET routes only. |
| Catalog/detail API | query service | authorized Project and effective permission set | WIRED | Project visibility/audit/optional-region permissions precede projection. |
| Query service | `resolve_effective_versions` | batch canonical resolver with explicit institution scope | WIRED | Formal catalog/detail/version calls pass project and institution, including explicit null. |
| Catalog route | catalog API | canonical query, shared `apiGet`, AbortSignal, request-key reducer | WIRED | Scope mismatch becomes loading synchronously; stale success/error events are rejected. |
| Detail tab | lazy endpoint | URL/request key plus local async state | WIRED | Region 403/error/empty/retry remains local while the canonical header stays mounted. |
| Restricted ORM reference | JSON/DOM/AX | strict restricted union then type-only production render model | WIRED | Protected identifiers and metadata are absent from serialized and browser outputs. |
| Binding/lineage projection | existing lineage route | exact approved `/lineage` query validation | WIRED | Both backend-emitted selector shapes retain byte-identical hrefs. |
| Conflict DTO | persistent header | source collection plus bounded disclosure | WIRED | All sources remain inspectable and no winner is inferred. |

## Data-Flow Trace (Level 4)

| Output | Authoritative source | Flow | Status |
|---|---|---|---|
| Catalog identity/summary | `SemanticConcept` + effective confirmed `SemanticConceptVersion` | SQLAlchemy → query service → strict DTO → `apiGet` → directory/table | ✓ FLOWING |
| Formal definition | confirmed effective `SemanticConceptVersion` | institution-scoped resolver → detail shell → header formal region | ✓ FLOWING |
| Bindings/relations/counts | canonical `SemanticBinding` / `SemanticRelation` plus confirmed endpoints | scoped set-based partitions → counts/regions → lists/chain | ✓ FLOWING |
| Evidence/knowledge | existing evidence references and `KnowledgeUnit` | scoped projection → permission-safe reference → bounded disclosure | ✓ FLOWING |
| Lineage | existing `LineageNode` / `LineageEdge` and asset entities | scoped projection → canonical href → exact client allowlist | ✓ FLOWING |
| Governance/questions/audit | `ReviewTask`, `PendingQuestion`, `AuditLog` | scoped service → separate workflow/conflict/audit DTOs → header/governance region | ✓ FLOWING |
| Versions | `SemanticConceptVersion` | scoped chronological partitions → timeline | ✓ FLOWING |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Critical institution/temporal/audit/relation/facet/performance paths | Seven exact `pytest nodeid` targets from `test_semantic_catalog_api.py` | 7 passed; 701 concepts, 7 statements, 86.43 ms, existing project index | ✓ PASS |
| Restricted DTO and optional permission fail-closed paths | Three exact `pytest nodeid` targets | 3 passed | ✓ PASS |
| Lawful lineage, restricted render model, conflict, and evidence disclosures | focused `semantic-detail-contract.test.mjs` command | 10 passed | ✓ PASS |
| Request identity, pagination, audit/status, sentinel, and entity labels | focused `semantic-catalog-view-model.test.mjs` command | 9 passed | ✓ PASS |
| Real production routes and browser interactions | `node --test frontend/tests/semantic-catalog-browser.test.mjs` | 12 passed, 0 failed/skipped, 65.68 s | ✓ PASS |
| Browser teardown | before/after profile/process audit | 0 temp profiles before/after; no surviving Next/Edge harness process | ✓ PASS |
| Full focused backend gate | recorded at unchanged source HEAD | 68 passed | ✓ QUALIFIED, not rerun |
| Normal frontend/build/lint gate | recorded at unchanged source HEAD | 83 passed; production build/lint exit 0 | ✓ QUALIFIED, not rerun |
| High-risk backend gate | recorded at unchanged source HEAD | 424 passed, exactly two named Windows deselections | ✓ QUALIFIED, not rerun |

## Evidence Matrix Verification

The 43-row ledger was parsed independently rather than trusted as prose:

- required identifier set: exactly CR-01, CR-02, WR-01..WR-09, SUI-01, SUI-02, D-01..D-30;
- 43 rows present, 43 unique, no missing/extra identifiers;
- every production path exists;
- every result is exactly `PASS`;
- every evidence artifact exists and every markdown anchor resolves;
- all rows map to current production behavior and runnable tests.

One non-blocking documentation drift remains: the WR-03 cell calls the test `semantic-catalog audit and status canonicalize...`, while the actual title is `catalog audit and status canonicalize...`. The row still points to the correct view-model production path and automated-results anchor, and the actual test passed in this re-verification.

## Probe Execution

Step 7c: **SKIPPED** — no plan or summary declares a probe script, and no Phase 11 conventional probe is required.

## Requirements Coverage

| Requirement | Source plans | Status | Evidence |
|---|---|---|---|
| SUI-01 | 11-01, 11-02, 11-05, 11-06, 11-08, 11-09 | ✓ SATISFIED (automated) | Real `/semantics`, authoritative API filters/totals/facets/pagination, distinct route states, request-key isolation, and six production catalog browser cases. |
| SUI-02 | 11-03, 11-04, 11-05, 11-07, 11-08, 11-09 | ✓ SATISFIED (automated) | Canonical detail truth, independent permission-aware regions, lawful bindings/relations/evidence/lineage/governance/versions, and six production detail browser cases. |

Both IDs appear in plan frontmatter and map only to Phase 11 in `REQUIREMENTS.md`; no requirement is orphaned.

## Anti-Patterns and Scope Fence

- No unreferenced `TBD`, `FIXME`, or `XXX` marker exists in Phase 11 implementation/test files.
- Empty list/dict/null returns are bounded no-input, safe-empty, or optional-region behavior, not stubs.
- No semantic mutation route, inline Confirm/Reject/Deprecate action, duplicate fact store, model, migration, index, dependency, lockfile, graph package, or Phase 12+ committed implementation was added.
- Current user-owned dirty/untracked files remain preserved. The dirty `AppShell.tsx` still contains the Phase 11 `/semantics` navigation entry; its broader navigation/workspace changes are not attributed to Phase 11.

## Human Verification Required

### 1. Approved viewport and visible-focus matrix

**Test:** At 320x720, 768x1024, 1280x800, and 1440x900, inspect populated, both empty variants, forbidden, retryable error, conflict, audit, historical, restricted-reference, long-text, comparison-table, horizontal tabs, and bounded-chain states. Traverse search, filters, view switch, first/previous/next/last pagination, tabs, disclosures, retries, and links with the keyboard.
**Expected:** No unintended page overflow or overlap; only deliberate table/tab scrolling; visible focus; readable wrapping; stable skeletons; conflict/history/current-only notices remain visible; the chain is nonblank and its text/list order matches the visual order.
**Why human:** Automated browser evidence proves DOM/state/focus transitions and data absence, not exact rendered geometry, density, contrast, or visible focus treatment across the four contract viewports.

## Environment Qualifications and Dedicated Gates

- `11-SECURITY.md` is absent. Run `$gsd-secure-phase 11`; this verifier does not impersonate the dedicated security verdict.
- `11-UI-REVIEW.md` is absent. Run `$gsd-ui-review 11`; that workflow owns screenshots, four-viewport scoring, and final visual/keyboard approval.
- PostgreSQL was unavailable. Query-count/latency evidence is SQLite-only and is a regression measurement, not a production benchmark.
- The exact high-risk Windows command needs repository-root `PYTHONPATH` after entering `backend`; the corrected environment-only invocation passed 424 tests with exactly the two named Windows deselections.
- The verifier did not rerun the 68-test, 83-test, build/lint, or 424-test broad gates because the user identified the exact same source HEAD as already green. It independently reran the goal-critical 10 backend tests, 19 Node contract/state tests, and 12 production-browser tests.

## Deferred Item Filter

No automated gap is deferred. Phases 12-15 cover Requirement Workspace, Dashboard, Quality Expectations, and Semantic Impact; none owns Phase 11 isolation, temporal truth, audit separation, traceability, state handling, or browser-route correctness.

## Gaps Summary

No implementation gap remains from the previous verification. The sole unresolved item is human visual/viewport approval, so the phase status is `human_needed`, not `passed`.

**Next actions:** run `$gsd-secure-phase 11`, then `$gsd-ui-review 11`, and complete the four-viewport human verification item.

---

_Verified: 2026-08-25T15:23:56Z_
_Verifier: the agent (gsd-verifier)_
