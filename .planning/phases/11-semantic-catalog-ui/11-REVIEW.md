---
phase: 11-semantic-catalog-ui
reviewed: 2026-08-25T06:55:06Z
depth: standard
files_reviewed: 30
files_reviewed_list:
  - backend/app/api/semantic_catalog.py
  - backend/app/main.py
  - backend/app/schemas/semantic_catalog.py
  - backend/app/services/semantic/catalog_query_service.py
  - backend/tests/test_semantic_catalog_api.py
  - frontend/app/semantics/[id]/page.tsx
  - frontend/app/semantics/page.tsx
  - frontend/components/AppShell.tsx
  - frontend/components/semantic-catalog/AsyncRegion.tsx
  - frontend/components/semantic-catalog/BindingChain.tsx
  - frontend/components/semantic-catalog/BindingList.tsx
  - frontend/components/semantic-catalog/CatalogToolbar.tsx
  - frontend/components/semantic-catalog/GroupedSemanticDirectory.tsx
  - frontend/components/semantic-catalog/RelationList.tsx
  - frontend/components/semantic-catalog/SemanticComparisonTable.tsx
  - frontend/components/semantic-catalog/SemanticDetailHeader.tsx
  - frontend/components/semantic-catalog/SemanticStatus.tsx
  - frontend/components/semantic-catalog/SemanticTabs.tsx
  - frontend/components/semantic-catalog/TrustSourceRegion.tsx
  - frontend/components/semantic-catalog/VersionTimeline.tsx
  - frontend/lib/api.ts
  - frontend/lib/http-response.d.mts
  - frontend/lib/http-response.mjs
  - frontend/lib/semantic-catalog-dom-contract.mjs
  - frontend/lib/semantic-catalog-view-model.d.mts
  - frontend/lib/semantic-catalog-view-model.mjs
  - frontend/lib/types.ts
  - frontend/tests/http-response.test.mjs
  - frontend/tests/semantic-catalog-dom.test.mjs
  - frontend/tests/semantic-catalog-view-model.test.mjs
findings:
  critical: 2
  warning: 9
  info: 0
  total: 11
status: issues_found
---

# Phase 11: Code Review Report

**Reviewed:** 2026-08-25T06:55:06Z  
**Depth:** standard  
**Files Reviewed:** 30  
**Status:** issues_found

## Summary

The Phase 11 catalog and detail surfaces were reviewed against D-01 through D-30, SUI-01/SUI-02, authorization and isolation requirements, temporal truth, rejected/deprecated separation, stale-response behavior, accessibility, and regression risk. The Phase 11 portion of `AppShell.tsx` was restricted to the `BookOpenCheck` import and `/semantics` navigation entry introduced by commit `6908d5f`; unrelated working-tree changes were not attributed to this phase.

The focused backend suite passed (16 tests), the frontend suite passed (51 tests), and the production frontend build completed. Those results do not cover the two release-blocking isolation failures below. The implementation can briefly expose the previous project's catalog after a context switch, and subordinate semantic data is not institution-scoped. Nine further correctness and test-coverage warnings remain.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: A project switch can render the previous project's catalog

**Classification:** BLOCKER (Critical)  
**Files:** `frontend/app/semantics/page.tsx:27-30`, `frontend/app/semantics/page.tsx:56-65`, `frontend/app/semantics/page.tsx:79-107`, `frontend/tests/semantic-catalog-view-model.test.mjs:199-210`  
**Issue:** `CatalogState` stores neither a project/request identity nor the parameters that produced a successful page. When `projectId` changes, React first renders with the prior success state; the effect that changes the state to `loading` runs only after that render. Consequently, the old project's semantic names, definitions, counts, and statuses can remain visible for a render/paint before the new request starts. Aborting the old request prevents a late write, but it does not invalidate already-rendered data. The detail route has an explicit request-key check, while the catalog route does not. The existing test exercises only the request coordinator and cannot detect this render-time leak.

**Fix:** Add a stable request key (at minimum `projectId` plus the normalized catalog query) to loading, success, and error states. During render, show catalog results only when `state.requestKey === currentRequestKey`; otherwise render the loading shell. Add a route/component regression test that renders project A, switches context to project B, and asserts that no project-A content exists before effects or the project-B response complete.

### CR-02: Subordinate semantic rows bypass institution isolation

**Classification:** BLOCKER (Critical)  
**Files:** `backend/app/services/semantic/catalog_query_service.py:83-93`, `backend/app/services/semantic/catalog_query_service.py:502-549`, `backend/app/services/semantic/catalog_query_service.py:910-937`, `backend/tests/test_semantic_catalog_api.py:673-727`  
**Issue:** Root concept queries apply `_institution_scope`, but version resolution/selection and confirmed binding/relation lookups are constrained only by project/concept identifiers. The affected models carry `institution_id`, and the reviewed code does not establish a database invariant that makes a matching project imply a matching institution. A malformed, migrated, or legacy version/binding/relation row with the correct project/concept and a foreign institution can therefore contribute a formal definition, metadata, binding, or relationship to another institution's response. The isolation test covers only a foreign-institution root concept, not subordinate rows.

**Fix:** Apply the project's institution predicate (including the intended null policy) to every semantic-version, binding, relation, question, and audit query that exposes an institution-bearing row. Extend the version resolver or validate its result before projection. Add adversarial fixtures with correct project/concept IDs but mismatched `institution_id` for versions, bindings, and relations, and assert that they are omitted or the detail request is rejected.

## Warnings

### WR-01: Confirmed relationship filters count edges to non-confirmed concepts

**Classification:** WARNING  
**Files:** `backend/app/services/semantic/catalog_query_service.py:200-207`, `backend/app/services/semantic/catalog_query_service.py:919-937`, `backend/tests/test_semantic_catalog_api.py:483-490`, `backend/tests/test_semantic_catalog_api.py:525-538`  
**Issue:** The directory's `has_relation` flag and relationship counts require only a confirmed relation row whose endpoint IDs are in the project. They do not require both endpoint concepts to be confirmed. The detail projection correctly drops the same edge when the related concept is not confirmed, so directory filtering and detail truth disagree. The API test currently codifies this inconsistency by expecting an edge to a draft concept to satisfy `has_relation=true`.

**Fix:** Join source and target concept aliases and require both concepts to be confirmed and institution-visible before counting the relation. Change the regression test so draft/rejected/deprecated counterpart concepts do not satisfy the relation filter, and retain a confirmed-to-confirmed positive case.

### WR-02: The emitted “uncategorized” facet cannot retrieve uncategorized rows

**Classification:** WARNING  
**Files:** `backend/app/services/semantic/catalog_query_service.py:983-988`, `backend/app/services/semantic/catalog_query_service.py:1111-1120`, `frontend/components/semantic-catalog/CatalogToolbar.tsx:56-57`, `frontend/components/semantic-catalog/CatalogToolbar.tsx:104`  
**Issue:** The backend emits `__uncategorized__` as a selectable facet value, but `_matches` compares it literally against the row's null/blank category, so selecting the facet returns an empty result set. The toolbar also exposes the internal sentinel as both option and active-chip text instead of the required user-facing “未分类”.

**Fix:** Treat the sentinel as a null-or-blank category predicate in the service, and map it to “未分类” in the toolbar while preserving the sentinel only in the wire/query value. Add an endpoint and UI serialization test for this selection.

### WR-03: Direct audit/status URL combinations produce 422 instead of a canonical UI state

**Classification:** WARNING  
**Files:** `frontend/lib/semantic-catalog-view-model.mjs:424-439`, `frontend/app/semantics/page.tsx:84-100`, `backend/app/services/semantic/catalog_query_service.py:435-437`  
**Issue:** URL normalization handles `audit` and `status` independently. Thus `?status=rejected` remains in normal mode and `?audit=1&status=confirmed` remains in audit mode; the backend rejects both combinations. This turns a bookmarkable UI state into an API error rather than enforcing the audit-mode state machine and canonicalizing the URL.

**Fix:** Normalize the fields together: either make rejected/deprecated status imply audit mode and clear non-audit statuses when audit is active, or select and document the reverse precedence. Serialize the normalized state back to the URL and test both direct-link combinations.

### WR-04: Backend-generated lineage links are always rejected by the UI allowlist

**Classification:** WARNING  
**Files:** `backend/app/services/semantic/catalog_query_service.py:717-722`, `backend/app/services/semantic/catalog_query_service.py:871-878`, `frontend/components/semantic-catalog/BindingList.tsx:24-31`  
**Issue:** The API emits canonical links such as `/lineage?scenarioTechnicalLineageId=...` and `/lineage?nodeId=...`, but `BindingList` accepts only paths beginning with `/lineage/fields/`. Valid backend links are therefore replaced with the non-navigable fallback, breaking D-26.

**Fix:** Parse the URL and allow the exact `/lineage` pathname with the approved query parameters in addition to `/lineage/fields/...`; do not broaden this to arbitrary `/lineage*` paths. Add component tests using the exact href shapes returned by the backend.

### WR-05: Conflict notices omit the source summaries required for review

**Classification:** WARNING  
**File:** `frontend/components/semantic-catalog/SemanticDetailHeader.tsx:48-53`  
**Issue:** The component renders the conflict summary and a generic explanation but never renders `conflict.sources`. Reviewers therefore cannot see the competing source summaries that D-21/SUI-16 require, despite the API carrying them.

**Fix:** Render a bounded, accessible list of the competing source type and summary values, exposing identifiers only when authorized. Preserve the neutral presentation and do not imply a winner. Test two-source and long-summary rendering in the production component.

### WR-06: DOM tests validate a fixture, not the production routes and components

**Classification:** WARNING  
**Files:** `frontend/tests/semantic-catalog-dom.test.mjs:6-21`, `frontend/tests/semantic-catalog-dom.test.mjs:23-134`, `frontend/tests/semantic-catalog-view-model.test.mjs:199-210`  
**Issue:** The DOM suite renders `SemanticContractFixture`, a test-only HTML generator, rather than `CatalogToolbar`, `SemanticTabs`, `AsyncRegion`, or either Next route. It can pass while production markup, keyboard behavior, request identity, and restricted-data handling are broken. The long-text test checks a class token rather than real disclosure or overflow behavior, and the project-switch test exercises only an isolated coordinator.

**Fix:** Add a production component/route harness with project context and controlled fetches. Assert stale-content removal at render time, actual tab semantics and focus behavior, retry behavior, restricted DOM absence, toolbar URL behavior, and long-content disclosure. Keep fixture tests only as low-level contract-unit tests, not SUI coverage.

### WR-07: Restricted references fall back to an untranslated generic type

**Classification:** WARNING  
**Files:** `frontend/lib/semantic-catalog-dom-contract.mjs:7-17`, `frontend/lib/semantic-catalog-dom-contract.mjs:78-84`, `frontend/lib/semantic-catalog-view-model.mjs:14-27`, `frontend/components/semantic-catalog/BindingList.tsx:24`  
**Issue:** The DOM contract's entity-label map omits mapping and lineage entity types that the view-model map already knows. A restricted `source_to_mart_mapping`, `mart_to_ybt_mapping`, `scenario_business_mapping`, or `scenario_technical_lineage` therefore renders as the generic “数据资产 · 受限”, losing the required translated type label. The duplicated maps have already drifted.

**Fix:** Use one shared, exhaustive entity-type label map for both contracts and add restricted-reference tests for every `EntityType` value.

### WR-08: Evidence excerpts have no accessible collapse/expand behavior

**Classification:** WARNING  
**File:** `frontend/app/semantics/[id]/page.tsx:179`  
**Issue:** Evidence excerpts are rendered in full with `whitespace-pre-wrap`; there is no six-line collapsed state or “展开全文/收起” control. A long source excerpt can dominate the page and does not meet the specified keyboard-accessible disclosure behavior.

**Fix:** Implement a per-evidence-item disclosure keyed by stable item ID, use visual line-clamping only while collapsed, and connect the button with `aria-expanded` and `aria-controls`. Keep the full text selectable when expanded and test keyboard activation plus state isolation between items.

### WR-09: Catalog pagination omits the required first/last controls

**Classification:** WARNING  
**File:** `frontend/app/semantics/page.tsx:146-150`  
**Issue:** The catalog footer provides only previous/next buttons. For result sets exceeding five pages, the UI specification requires first/last controls; users otherwise cannot make the specified bounded jump and keyboard navigation contract is incomplete.

**Fix:** Add stable “首页” and “末页” controls when `total_pages > 5`, with correct disabled states and URL-backed navigation. Test the first, middle, and last page states for both small and large page counts.

---

_Reviewed: 2026-08-25T06:55:06Z_  
_Reviewer: the agent (gsd-code-reviewer)_  
_Depth: standard_
