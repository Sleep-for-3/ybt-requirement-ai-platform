---
phase: 11-semantic-catalog-ui
verified: 2026-08-25T07:18:12Z
status: gaps_found
score: 6/13 must-haves verified
behavior_unverified: 1
overrides_applied: 0
requirement_statuses:
  SUI-01: blocked
  SUI-02: blocked
gaps:
  - truth: "Catalog and detail data remain project/institution isolated before, during, and after every project switch."
    status: failed
    reason: "The catalog can render the previous project's successful state for one render, and same-project subordinate semantic rows with a foreign institution_id are returned as formal versions, bindings, relations, counts, and relation flags."
    artifacts:
      - path: "frontend/app/semantics/page.tsx"
        issue: "CatalogState carries no requestKey; render accepts any prior success until the project-change effect runs."
      - path: "backend/app/services/semantic/catalog_query_service.py"
        issue: "Version, binding, relation, and partition queries do not consistently apply the authorized Project institution predicate."
      - path: "backend/app/services/semantic/version_service.py"
        issue: "resolve_effective_versions constrains project_id but not institution_id."
      - path: "backend/tests/test_semantic_catalog_api.py"
        issue: "Isolation fixtures cover a foreign root concept, not same-project foreign-institution subordinate rows."
    missing:
      - "Bind catalog render state to the current normalized project/query request key before rendering any rows or totals."
      - "Apply the authorized project's institution null/equality policy to every institution-bearing semantic version, binding, and relation query, including resolver results and audit partitions."
      - "Add adversarial same-project/foreign-institution version, binding, relation, catalog, detail, and project-switch render tests."
  - truth: "Server search, filters, facets, confirmed relation semantics, URL audit state, and pagination remain mutually consistent and bookmark-safe."
    status: partial
    reason: "Confirmed relations to draft concepts count in catalog filters, the emitted __uncategorized__ facet cannot match null/blank domains, direct audit/status URLs reach backend 422, and the required first/last controls are absent."
    artifacts:
      - path: "backend/app/services/semantic/catalog_query_service.py"
        issue: "Relation aggregates do not require confirmed, institution-visible endpoint concepts; domain matching treats the uncategorized sentinel literally."
      - path: "frontend/lib/semantic-catalog-view-model.mjs"
        issue: "audit and status normalize independently, allowing invalid bookmark combinations."
      - path: "frontend/components/semantic-catalog/CatalogToolbar.tsx"
        issue: "The internal uncategorized sentinel is rendered as user-facing option/chip text."
      - path: "frontend/app/semantics/page.tsx"
        issue: "Pagination exposes only previous/next controls."
    missing:
      - "Use confirmed, institution-visible source and target concepts for relation counts and has_relation."
      - "Map __uncategorized__ to null/blank filtering server-side and 未分类 presentation client-side."
      - "Canonicalize audit/status as one state machine and serialize the normalized URL."
      - "Add 首页/末页 controls when total pages exceed five, with URL-backed tests."
  - truth: "All detail traceability and governance facts remain inspectable through lawful destinations and complete neutral presentation."
    status: partial
    reason: "Valid /lineage?... links are rejected by the frontend allowlist, conflict source summaries are dropped, restricted mapping/lineage types degrade to a generic label, and evidence excerpts lack the required accessible disclosure."
    artifacts:
      - path: "frontend/components/semantic-catalog/BindingList.tsx"
        issue: "lawfulHref accepts /lineage/fields/... but rejects the backend's exact /lineage?... routes."
      - path: "frontend/components/semantic-catalog/SemanticDetailHeader.tsx"
        issue: "conflict.sources is never rendered."
      - path: "frontend/lib/semantic-catalog-dom-contract.mjs"
        issue: "Restricted entity labels omit mapping and scenario technical lineage types and duplicate a fuller map elsewhere."
      - path: "frontend/app/semantics/[id]/page.tsx"
        issue: "Evidence excerpts render unbounded text without aria-expanded/aria-controls disclosure."
    missing:
      - "Allow the exact canonical /lineage pathname with approved query parameters."
      - "Render a bounded accessible neutral conflict source list without choosing a winner."
      - "Use one exhaustive entity label map for every permitted EntityType."
      - "Add per-item six-line evidence disclosure with stable IDs and keyboard/component tests."
  - truth: "The required loading, empty, error, unauthorized, stale-scope, keyboard, restricted-DOM, and long-content states are exercised against production routes/components."
    status: partial
    reason: "The DOM suite renders SemanticContractFixture instead of the production catalog/detail routes and components, so it cannot catch the confirmed catalog render leak or production-markup drift."
    artifacts:
      - path: "frontend/tests/semantic-catalog-dom.test.mjs"
        issue: "Tests serialize a test-only fixture rather than CatalogToolbar, SemanticTabs, AsyncRegion, BindingList, or either route."
      - path: "frontend/tests/semantic-catalog-view-model.test.mjs"
        issue: "Project-switch coverage validates only AbortController/coordinator behavior, not stale content removal at render time."
    missing:
      - "Add a production component/route harness with ProjectContext and controlled out-of-order fetches."
      - "Assert actual production tab/focus, retry, restricted DOM, toolbar URL, conflict sources, long text, and stale project behavior."
behavior_unverified_items:
  - truth: "Catalog and detail layouts remain coherent and visibly keyboard-operable at 320x720, 768x1024, 1280x800, and 1440x900."
    test: "After the automated gaps are closed, open representative populated, empty, forbidden, conflict, historical, restricted-reference, long-definition, table, tab, and bounded-chain states at all four approved viewports; traverse search, filters, view switch, pagination, tabs, disclosure, retry, and links using only the keyboard."
    expected: "No unintended page overflow or overlap; only deliberate table/tab scrolling; visible focus; readable wrapping; stable skeletons; conflict/history/current-only notices stay visible; the chain is nonblank and its list order matches the visual order."
    why_human: "The current Node tests and production build prove code/markup availability, not rendered geometry, focus visibility, browser scrolling, or visual density. No 11-UI-REVIEW.md exists."
---

# Phase 11: Semantic Catalog UI Verification Report

**Phase Goal:** 在现有 Next.js 与 Design Tokens 中提供完整语义目录和详情体验。  
**Verified:** 2026-08-25T07:18:12Z  
**Status:** GAPS FOUND  
**Re-verification:** No — initial verification

## Verdict

Phase 11 is **not complete**. The implementation is substantial, both routes are wired to real APIs, canonical temporal selection is reused, audit/candidate partitions exist, permission-minimized DTOs are strict, and all current automated commands pass. Those green commands do not establish the phase goal because two release-blocking isolation failures are observable in the current code and one is reproduced dynamically.

The verifier independently confirmed every finding in `11-REVIEW.md`: **2 Critical and 9 Warning**. The two critical issues invalidate both the project/institution isolation contract and the claim that stale project data never renders. Later phases do not specifically own these defects, so none is deferred.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---:|---|---|---|
| 1 | `/semantics` and `/semantics/{id}` use registered authenticated routes and render real API projections. | ✓ VERIFIED | `main.py:56,185` imports/registers the secured router; catalog/detail pages call `apiGet` at `frontend/app/semantics/page.tsx:66-75` and `[id]/page.tsx:100-128`; production build emits both routes. |
| 2 | Catalog/detail data remains project- and institution-isolated, including subordinate rows and project switches. | ✗ FAILED | Catalog success state has no request identity (`page.tsx:27-30,56-80`). Dynamic TestClient proof returned a foreign-institution formal definition, one binding, and one relation with HTTP 200 because subordinate queries lack institution scope. |
| 3 | Server search, filters, totals, facets, relation counts, URL state, and pagination represent one truthful population. | ✗ FAILED | `_confirmed_relation_ids` counts confirmed edges without confirmed endpoints (`catalog_query_service.py:919-937`); `_facets` emits `__uncategorized__` while `_matches` compares it literally (`:983-988,1111-1120`); audit/status can become backend 422; first/last controls are absent. |
| 4 | The default grouped directory and comparison table render server-provided governed summaries with separate lifecycle/review dimensions. | ✓ VERIFIED | `GroupedSemanticDirectory`, `SemanticComparisonTable`, and `SemanticStatus` are substantive and wired from catalog success rendering; the view model groups blank domains last. |
| 5 | Formal meaning comes only from the server-selected confirmed `SemanticConceptVersion`, with inclusive `as_of`, ambiguity handling, historical mode, and no legacy/AI fallback. | ✓ VERIFIED | `resolve_effective_versions` is the only formal resolver; DTO formal version is nullable; header shows `暂无正式版本` and candidates separately; focused temporal/ambiguity tests passed. The cross-institution resolver defect is classified under Truth 2. |
| 6 | Confirmed/candidate/audit lifecycle, Pending Review workflow, and unresolved-question lifecycle stay distinct. | ✓ VERIFIED | Central status partitions are used; audit reads require `audit.read`; rejected/deprecated remain outside default trusted arrays; questions use `open/assigned/answered`; lifecycle and review render separately. |
| 7 | Restricted references are minimized before serialization and optional region permissions fail with explicit HTTP 403. | ✓ VERIFIED | Strict restricted DTOs contain only `entity_type` and `restricted=true`; JSON tests inspect absence of protected fields; evidence/lineage/audit region permission gates return 403. Translation completeness is a traceability presentation gap, not a metadata disclosure. |
| 8 | Bindings, relations, evidence/knowledge, lineage, governance, and versions are fully traceable through lawful destinations and bounded displays. | ✗ FAILED | Regions and real data flows exist, but backend `/lineage?...` links are rejected by `BindingList`, restricted mapping/lineage labels degrade, and evidence disclosure is missing. |
| 9 | Conflicts and open questions remain inspectable without a false winner. | ✗ FAILED | The UI correctly avoids choosing a winner and filters resolved questions, but `SemanticDetailHeader.tsx:48-53` drops the API's `conflict.sources`, so the required competing-source summaries are not inspectable. |
| 10 | Required loading/empty/error/unauthorized/no-binding/conflict/pending/audit/historical states are tested through production routes/components. | ✗ FAILED | Current DOM tests render `SemanticContractFixture`; project-switch coverage tests only the coordinator. They cannot validate production render identity or production component markup. |
| 11 | URL/bookmark and async request identity prevent unsafe state or stale project/query rendering. | ✗ FAILED | Detail shell has a request-key guard; catalog does not. Audit/status pairs normalize independently and direct bookmarks can become 422 instead of a canonical UI state. |
| 12 | The read model is projection-only, bounded, set-based, and adds no fact store, migration, index, graph package, or mutation workflow. | ✓ VERIFIED | No model/migration/package diff exists in the Phase 11 range. Current 701-concept SQLite spot-check used 7 statements and 63.51 ms; chain/region caps are explicit. PostgreSQL was unavailable and is not claimed. |
| 13 | Responsive geometry and visible keyboard operation satisfy the approved viewport contract. | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | Responsive classes and keyboard controller/wiring exist, but no live viewport/UI review exists; see Human Verification Required. |

**Score:** 6/13 truths verified; 1 present but behavior/visual-unverified.

## Required Artifacts

| Artifact | Existence / substance | Wiring / data | Status |
|---|---|---|---|
| `backend/app/schemas/semantic_catalog.py` | Strict `extra="forbid"` catalog/detail/lazy DTOs and discriminated restricted unions | Response models for all catalog routes | ✓ VERIFIED |
| `backend/app/services/semantic/catalog_query_service.py` | 1,100+ lines of real query/projection logic; no static fallback | Called by all routes and reads canonical stores, but subordinate institution scope and several aggregate/filter contracts are incomplete | ✗ PARTIAL |
| `backend/app/api/semantic_catalog.py` | Eight additive authenticated read routes with bounded inputs and optional permission gates | Registered under secured `/api`; delegates to query service | ✓ VERIFIED |
| `backend/tests/test_semantic_catalog_api.py` | 1,300+ lines; temporal, audit, redaction, permission, cap, query-count, and performance cases | Executes against TestClient/SQLite, but misses adversarial subordinate-institution fixtures | ✗ PARTIAL |
| `frontend/app/semantics/page.tsx` | Real catalog route, toolbar, views, state branches, pagination | Calls real API, but success/error state is not bound to current request identity | ✗ PARTIAL |
| Catalog components and view model | Substantive toolbar, grouping, table, status, URL and request helpers | Wired to the route, but uncategorized/audit state and first/last pagination contracts are incomplete | ✗ PARTIAL |
| `frontend/app/semantics/[id]/page.tsx` and detail components | Real shell plus six independently loaded regions | Calls strict region APIs; some lawful links/data are dropped and evidence disclosure is absent | ✗ PARTIAL |
| `frontend/tests/semantic-catalog-dom.test.mjs` | Substantive low-level contract tests | Tests a fixture rather than production routes/components | ⚠️ PARTIAL |
| `frontend/components/AppShell.tsx` Phase 11 hunk | `BookOpenCheck` import and `/semantics` navigation only | Active prefix uses existing shell behavior; user WIP remained unstaged | ✓ VERIFIED |

## Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `main.py` | `api/semantic_catalog.py` | secured router registration | WIRED | `main.py:185`. |
| Catalog API | query service | authorized Project plus effective permissions | PARTIAL | Project is authorized, but the institution predicate is not propagated to every subordinate semantic query. |
| Query service | `resolve_effective_versions` | batched canonical resolver | PARTIAL | Inclusive and confirmed-only behavior is correct; resolver lacks institution scope. |
| Catalog route | catalog API | shared `apiGet`, normalized URL/query, AbortSignal | PARTIAL | Late writes are rejected, but prior successful render state is not invalidated synchronously. |
| Detail tab | lazy endpoint | scoped request key and local state machine | WIRED | Optional failures stay region-local and HTTP 403 remains distinct. |
| Restricted ORM reference | JSON/DOM | server restricted union then type-only render | WIRED | Protected identifiers/name/code/href are absent; entity label coverage is incomplete. |
| Binding/lineage projection | existing asset route | backend href then frontend allowlist | NOT_WIRED | Exact backend `/lineage?...` links are rejected by the client allowlist. |
| Conflict DTO | title banner | `conflicts[]` render | PARTIAL | Summary/review link renders; `sources[]` is discarded. |

## Data-Flow Trace (Level 4)

| Output | Authoritative source | Flow | Status |
|---|---|---|---|
| Catalog identity/summary | `SemanticConcept` + effective `SemanticConceptVersion` | SQLAlchemy -> query service -> DTO -> `apiGet` -> directory/table | ⚠️ FLOWING, UNSAFE SCOPE |
| Formal detail definition | confirmed effective `SemanticConceptVersion` | resolver -> detail shell -> `SemanticDetailHeader` | ⚠️ FLOWING, UNSAFE SCOPE |
| Binding/relation counts and regions | `SemanticBinding` / `SemanticRelation` / related concepts | set-based rows -> partitions/counts -> catalog/detail | ⚠️ FLOWING, UNSAFE/INCONSISTENT |
| Evidence/knowledge | existing evidence references and `KnowledgeUnit` | region projection -> permission-safe references -> Evidence tab | ✓ FLOWING; excerpt UX incomplete |
| Lineage | existing `LineageNode` / `LineageEdge` and asset entities | region projection -> canonical href -> `SemanticReference` | ✗ HOLLOW DESTINATION for `/lineage?...` |
| Governance/questions/audit | `ReviewTask`, `PendingQuestion`, `AuditLog` | query service -> shell/governance DTO -> header/regions | ⚠️ FLOWING; conflict sources dropped |
| Versions | `SemanticConceptVersion` | partitioned chronological projection -> timeline | ⚠️ FLOWING, UNSAFE SCOPE |

## Independent Review-Finding Reproduction

| Finding | Verdict | Independent evidence |
|---|---|---|
| CR-01 prior-project catalog render | CONFIRMED — BLOCKER | Catalog state omits requestKey; effects clear only after render. Existing test exercises only `createCatalogRequestCoordinator`. |
| CR-02 subordinate institution bypass | CONFIRMED — BLOCKER | Dynamic SQLite/TestClient adversarial fixture returned HTTP 200 and exposed `FOREIGN_INSTITUTION_FORMAL_DEFINITION`, one foreign binding, one foreign relation, related count `1`, and `has_relation=true`. |
| WR-01 relation count accepts draft endpoint | CONFIRMED | `_confirmed_relation_ids` checks relation status only; existing test deliberately connects confirmed -> draft and expects `has_relation=true`. |
| WR-02 uncategorized facet cannot filter | CONFIRMED | Facet emits `__uncategorized__`; matcher compares it to `None`/blank; toolbar prints the sentinel. |
| WR-03 audit/status URL yields 422 | CONFIRMED | Fields normalize independently; backend rejects statuses outside effective mode at `catalog_query_service.py:435-437`. |
| WR-04 lineage href rejected | CONFIRMED | Backend emits `/lineage?scenarioTechnicalLineageId=...` and `/lineage?nodeId=...`; UI allowlist accepts only `/lineage/fields/...`. |
| WR-05 conflict sources omitted | CONFIRMED | Header maps `summary` and `review_href`, never `conflict.sources`. |
| WR-06 fixture-only DOM tests | CONFIRMED | `semantic-catalog-dom.test.mjs` imports and renders `SemanticContractFixture`, not production components/routes. |
| WR-07 restricted label map drift | CONFIRMED | DOM contract map omits four mapping/lineage types present in the view-model map. |
| WR-08 evidence has no disclosure | CONFIRMED | Detail page renders `excerpt` directly with `whitespace-pre-wrap`; no `aria-expanded`, `aria-controls`, clamp, or per-item state. |
| WR-09 missing first/last pagination | CONFIRMED | `CatalogPagination` contains only 上一页/下一页. |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Focused backend catalog contract | `PYTHONPATH=backend python -m pytest backend/tests/test_semantic_catalog_api.py -q -s` | 16 passed; 701 concepts; 7 statements; 63.51 ms; existing SQLite project index | PASS, but does not cover adversarial institution rows |
| Phase 8 semantic compatibility plus catalog | `PYTHONPATH=backend python -m pytest backend/tests/test_semantic_catalog_api.py backend/tests/test_semantic_layer.py -q` | 34 passed in 28.16s | PASS |
| Frontend tests | `npm test` | 51 passed | PASS, but production-route gap remains |
| Frontend production build | `npm run build` | exit 0; `/semantics` and `/semantics/[id]` emitted | PASS |
| Frontend lint | `npm run lint` | exit 0; warnings only in unrelated pre-existing routes | PASS |
| Same-project foreign-institution subordinate rows | one-off TestClient/SQLite adversarial scenario | shell/catalog exposed foreign formal definition; bindings=1; relations=1; count=1; relation=true | FAIL — BLOCKER |

Execution also reported a 200-pass prior-phase regression gate with four existing SQLite deprecation warnings. The verifier did not substitute that report for current evidence: the current focused 34-test semantic/catalog gate was rerun, and the adversarial test demonstrates a goal-critical gap despite green regressions.

## Probe Execution

Step 7c: **SKIPPED** — Phase 11 plans/summaries declare no probe script, and no conventional `probe-*.sh` exists under `scripts`.

## Requirements Coverage

| Requirement | Source plans | Description | Status | Evidence |
|---|---|---|---|---|
| SUI-01 | 11-01, 11-02 | Browse/filter `/semantics` with loading/empty/error/unauthorized/pending states | ✗ BLOCKED | Real route and states exist, but stale prior-project rendering, inconsistent relation/domain/audit filters, incomplete pagination, and non-production state tests violate the requirement contract. |
| SUI-02 | 11-03, 11-04 | Browse definition, bindings, relations, knowledge, evidence, lineage, versions, governance | ✗ BLOCKED | Real regions exist, but foreign-institution subordinate facts leak, lawful lineage links fail, conflict sources are missing, and evidence disclosure/production component coverage is incomplete. |

Both Phase 11 requirement IDs appear in plan frontmatter and map only to Phase 11 in `REQUIREMENTS.md`; no requirement is orphaned.

## Anti-Patterns and Scope Fence

No `TBD`, `FIXME`, or `XXX` blocker marker exists in the Phase 11 implementation files. Empty list/dict returns are guarded no-input behavior, and placeholder text is functional form copy rather than a stub.

Verified scope prohibitions:

- No semantic mutation/inline confirm/reject/deprecate workflow was added.
- No persisted catalog/detail fact store, migration, index, new package, graph library, or external service was added.
- Phase 8/9 semantic APIs remain registered and the combined semantic regression gate passes.
- The Phase 11 AppShell commit contains exactly two additions. The user's pre-existing AppShell/frontend WIP remains outside the Phase 11 commit and was not edited by this verifier.

## Security and UI Review Gates

- `11-SECURITY.md` does not exist. Security enforcement is not disabled, and a confirmed cross-institution disclosure exists. After gap closure and re-verification, run `$gsd-secure-phase 11`; do not treat the current test suite as a security pass.
- `11-UI-REVIEW.md` does not exist while `workflow.ui_review` is enabled. After automated gaps close, run `$gsd-ui-review 11` and complete the live viewport/keyboard checks below.

## Human Verification Required

Automated gaps take precedence, so the overall status remains `gaps_found`. After closing them:

### 1. Responsive catalog and detail matrix

**Test:** Inspect populated, empty, forbidden, error, conflict, audit, historical, restricted, long-text, comparison-table, tab, and bounded-chain states at 320x720, 768x1024, 1280x800, and 1440x900.  
**Expected:** No unintended page overflow/overlap; deliberate table/tab scroll only; stable skeletons; readable long text; nonblank bounded chain; all governance notices remain visible.  
**Why human:** Build and serialized markup do not establish rendered geometry or density.

### 2. Production keyboard and return flow

**Test:** With a real authorized project, operate search, filters, view switch, first/previous/next/last pagination, tabs, disclosure, retries, semantic/asset/review links, and catalog return using only the keyboard.  
**Expected:** Visible focus, correct Arrow/Home/End tab movement, no focus loss after retries/disclosure, safe catalog state restoration, and no inaccessible hidden data.  
**Why human:** Current tests exercise low-level controllers/fixtures rather than the complete browser route and focus system.

## Deferred Item Filter

No gap is deferred. Phases 12-15 cover Requirement Workspace, Dashboard, Quality Expectations, and Semantic Impact; none explicitly owns Phase 11 isolation, filtering, route, conflict, evidence, pagination, or test-harness defects.

## Gaps Summary

Phase 11 has **4 grouped gap concerns**: one critical isolation/security concern, one authoritative catalog-state concern, one traceability/governance presentation concern, and one production interaction-test concern. The first concern alone blocks phase completion. The green test/build record is useful regression evidence but does not falsify the demonstrated cross-institution disclosure or stale-render path.

**Next command:** `$gsd-plan-phase 11 --gaps`

---

_Verified: 2026-08-25T07:18:12Z_  
_Verifier: the agent (gsd-verifier)_
