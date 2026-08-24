# Phase 11: Semantic Catalog UI - Research

**Researched:** 2026-08-25
**Domain:** Governed semantic catalog read models, temporal truth, permission-safe traceability, and Next.js operational UI
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

## Implementation Decisions

### Catalog Browsing and Filtering

- **D-01 Product model:** `/semantics` follows an enterprise Data Catalog model. Its default is a scannable grouped directory, not a traditional dense CRUD table and not a card waterfall.
- **D-02 Default grouping:** Concepts are grouped by Business Domain. Concepts without a domain appear in a dedicated `未分类` group.
- **D-03 View modes:** Users can switch between the grouped directory and a medium-density comparison table. The grouped directory is the default.
- **D-04 Default fields:** Each result exposes Concept name, Concept Code, type, business domain, current effective version, governance status, Owner, related-asset count and update time.
- **D-05 Search contract:** Search covers name, code, aliases and definition. Search is explicitly submitted with Enter or a search action; enum/filter controls update immediately. The browser must not pretend a partially loaded page is the full searchable dataset.
- **D-06 Filter contract:** Primary filters are Concept Type, Business Domain, Governance Status and Owner. Advanced filters add effective date/`as_of`, has Binding, has Relation and has Pending Review.
- **D-07 Rejected/deprecated isolation:** Rejected and deprecated concepts are hidden by default and appear only after an explicit audit/history-state filter. Their existence must never contaminate the current trusted view, relationship counts or current fact presentation.
- **D-08 Durable navigation state:** Search, all filters, `as_of` and view mode are synchronized to URL query parameters so the catalog state survives refresh and can be bookmarked or shared.

### Detail Page and Temporal Versions

- **D-09 Information architecture:** `/semantics/{id}` uses a top summary plus `Overview`, `Bindings`, `Relations`, `Evidence`, `Lineage`, `Governance` and `Versions` tabs. It must not become an unbounded long page.
- **D-10 Summary hierarchy:** The header shows semantic name/Code, type, effective governance state, definition, domain, Owner and current effective version. Overview first answers: what it means, which version is effective now, why it is trusted, which major Target/Mart/Source assets it binds to, and whether unresolved questions exist.
- **D-11 Canonical temporal truth:** The effective `SemanticConceptVersion` is the definition source for the requested date. Phase 11 must not redesign or bypass the Phase 8/9 version model or turn legacy Concept projection fields into an independent truth.
- **D-12 Historical entry point:** The detail header provides the `as_of` control near the effective-version summary. Current mode is the default. Historical mode shows a prominent `Viewing as of YYYY-MM-DD` banner plus a one-action return to the current version.
- **D-13 Mixed temporal capability:** In historical mode, temporal semantic content is resolved strictly as of the selected date. Binding, Evidence, Lineage or other sections that only expose current state may remain visible, but must be labeled `当前状态，不代表该历史日期` rather than being presented as historical facts.
- **D-14 Loading boundary:** Overview loads first. Other tabs load on demand and own their loading, empty, error and retry states; a local request failure must not collapse the full detail page or appear as empty data.
- **D-15 Version timeline:** Versions uses a chronological timeline. Selecting a version expands it inline to show definition, effective interval, status, source/provenance and confirmation metadata. Phase 11 does not add a separate version-detail route.

### Governance, Authority and Provenance

- **D-16 Visual priority:** Confirmed is the formal trusted state. Pending Review, AI Suggested, Draft, Rejected and Deprecated remain clearly distinguishable without filling the interface with high-saturation badges.
- **D-17 Separate state dimensions:** Semantic lifecycle state and review-workflow state are shown separately. A Draft or AI Suggested resource may additionally show a restrained Pending Review process indicator; Pending Review does not replace or masquerade as a semantic lifecycle state.
- **D-18 Read-only governance boundary:** The catalog displays governance state, reviewers and reasons, then links authorized users to the existing Review Task workflow. It does not confirm, reject or deprecate semantics inline.
- **D-19 AI candidate isolation:** If no current confirmed version exists, Overview says `暂无正式版本`. AI Suggested content appears in a separate candidate region with `AI 建议，尚未成为正式监管语义`; it must not populate the current formal Definition area.
- **D-20 Trust and source region:** Authority, provenance, effective interval and regulatory/business source references are consolidated into a `可信度与来源`/Governance region. Individual facts should not compete through a wall of authority badges.
- **D-21 Conflict behavior:** A real unresolved high-authority conflict produces a persistent, non-dismissible warning banner in the title area, with conflicting-fact/source summaries and a human-review link. Other tabs remain inspectable, but the UI must not present an AI-recommended winner.
- **D-22 Audit-only states:** Rejected/deprecated resources are reachable through explicit Governance, Versions or audit/history paths only and remain visually marked as non-current.

### Binding Traceability and Exceptional States

- **D-23 Binding-first traceability:** Binding is a core Semantic Catalog capability. The detail experience exposes structured Binding lists, Concept relations and a small bounded relationship visualization; it does not introduce a large free-drag knowledge graph.
- **D-24 Bounded visualization focus:** The small visualization prioritizes the governed data-asset chain `Concept -> Target -> Mart -> Source`. Concept-to-Concept topology remains in Relations.
- **D-25 Confirmed versus candidate bindings:** Bindings are split into `Confirmed Bindings` and a separate, visible `待治理候选` section. Candidate bindings are clearly non-formal and do not contribute to trusted paths or confirmed related-asset counts.
- **D-26 Existing-route navigation:** Asset links navigate in the current tab to existing Target, Mart, Source, Knowledge or Lineage routes. Links carry `from=semantics` and the originating Concept identifier so the destination can preserve a return path; Phase 11 does not duplicate asset details in new drawers.
- **D-27 Permission-safe references:** If a Binding may lawfully be shown but its target asset is not readable, render an unlinked restricted placeholder containing only the asset type and restricted state. Do not expose its name, Code, source content or other protected metadata.
- **D-28 Distinct exceptional states:** `无绑定`, `存在待治理绑定`, `高权威冲突`, `无权限`, `加载失败` and ordinary empty data are different states with different copy and behavior. Failures provide retry and are never converted to `无数据`.
- **D-29 Question lifecycle:** Resolved questions are excluded from current open-question summaries. They may appear only in history/audit context.
- **D-30 Required state coverage:** The two routes require explicit tests for loading, empty, error, unauthorized, no-binding, conflict, pending-review, AI-only/no-confirmed-version, rejected/deprecated audit filtering and historical `as_of` presentation.

### the agent's Discretion

- Exact component boundaries, query/cache mechanism, server/client rendering split and additive read-model endpoint shape, provided the real API remains authoritative and project/institution isolation is preserved.
- Pagination/cursor mechanics, bounded graph node limits, responsive table behavior and the exact restrained token assignments for status presentation.
- Exact copy refinements beyond the user-specified trust, historical, AI-candidate and exceptional-state language.

### Deferred Ideas (OUT OF SCOPE)

- Requirement Workspace V2 and document-preview behavior belong to Phase 12.
- Semantic/mapping/lineage coverage dashboard and project readiness belong to Phase 13.
- Structured DataQualityExpectation belongs to Phase 14.
- Semantic Impact propagation belongs to Phase 15.
- SQL Generator remains outside Phase 11.
- A large free-form draggable semantic/knowledge graph is not part of the first Semantic Catalog UI.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SUI-01 | 用户可通过 `/semantics` 浏览、筛选语义目录并看到 loading/empty/error/unauthorized/pending 状态。 | Server-side catalog projection, URL-state contract, status-bearing errors, scoped cancellation, pagination/facets, and catalog state tests. [VERIFIED: .planning/REQUIREMENTS.md:34-35] |
| SUI-02 | 用户可在 `/semantics/{id}` 浏览定义、绑定、关系、知识、证据、血缘、版本和治理状态。 | Canonical effective-version reuse, lazy region endpoints, permission-safe references, current-only historical labeling, and detail state tests. [VERIFIED: .planning/REQUIREMENTS.md:34-35] |
</phase_requirements>

## Summary

Phase 11 should be planned as an additive, read-only projection layer plus two project-scoped React routes. The existing semantic list is not a catalog contract: it searches only `concept_code` and `concept_name`, has a hard `limit` with no total/facets/page metadata, and invokes `_attach_version_projection` once per returned concept. That helper selects the latest version by descending `version_no`, not the version effective for a requested date. [VERIFIED: backend/app/api/semantic.py:74-96] [VERIFIED: backend/app/api/semantic.py:650-661]

The implementation should reuse `resolve_effective_versions(...)` for catalog batches and detail headers. It already filters both concept and version through trusted visibility, uses inclusive `effective_from <= as_of <= effective_to`, optionally constrains `project_id`, and fails with `SEMANTIC_VERSION_AMBIGUOUS` when more than one confirmed version matches. [VERIFIED: backend/app/services/semantic/version_service.py:357-417] This lets the new projection remain a view over canonical stores instead of creating another semantic fact source.

The main security boundary is server-side field minimization. A readable binding does not imply a readable target asset: the projection must evaluate target-specific permission before constructing the response and return either a lawful reference or a type-only restricted placeholder. The frontend must never receive hidden target name, code, content, identifier, URL, tooltip text, or serialized metadata. Project invisibility already resolves as 404 while an insufficient permission on a visible project resolves as 403; new endpoints must preserve this distinction. [VERIFIED: backend/app/services/auth/permission_service.py:94-155]

**Primary recommendation:** Add a dedicated `semantic_catalog` query service and Pydantic read DTOs, expose a paginated catalog summary plus a small detail shell and lazy region endpoints, then build URL-driven pure view models and route components against those projections.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|--------------|----------------|-----------|
| Catalog search, filters, totals, facets, stable pagination | API / Backend | Database / Storage | Search must cover the full project dataset and totals/facets must derive from the same filtered query; client-side filtering of one loaded page violates D-05. |
| Effective definition for `as_of` | API / Backend | Database / Storage | The canonical batch resolver already owns trusted visibility, project scope, inclusive dates, and ambiguity detection. [VERIFIED: backend/app/services/semantic/version_service.py:357-417] |
| Permission-safe binding/evidence/lineage references | API / Backend | Database / Storage | Authorization and redaction must occur before DTO construction; browser redaction is only defense in depth. |
| URL synchronization and bookmark restoration | Browser / Client | Frontend Server (SSR) | The approved contract makes query state durable; pure parse/serialize functions should canonicalize it before requests. [VERIFIED: .planning/phases/11-semantic-catalog-ui/11-UI-SPEC.md:455-490] |
| Grouped directory, comparison table, tabs, local async states | Browser / Client | API / Backend | These are presentation and interaction responsibilities over authoritative server projections. |
| Canonical semantic, binding, relation, evidence, knowledge, lineage, review, audit facts | Database / Storage | API / Backend | Existing models remain source-of-truth stores; the phase only joins/projects them. Semantic tables already separate concept identity, versions, bindings, and relations. [VERIFIED: backend/app/models/semantic.py:9-135] |
| Bounded Concept -> Target -> Mart -> Source display | Browser / Client | API / Backend | The API supplies a capped, already-redacted graph/list; the client renders a stable CSS visualization plus text equivalent. |

## Standard Stack

### Core

| Library / facility | Existing version/contract | Purpose | Why Standard Here |
|--------------------|---------------------------|---------|-------------------|
| Next.js | `^14.2.20` | App Router routes at `/semantics` and `/semantics/[id]` | Existing frontend framework; no migration is needed. [VERIFIED: frontend/package.json:12-16] |
| React / React DOM | `^18.3.1` | Client state, effects, lazy regions, accessible interactions | Existing runtime and component model. [VERIFIED: frontend/package.json:12-16] |
| Tailwind CSS | `^3.4.17` | Existing design-token utility styling | The approved UI contract explicitly keeps the manual Tailwind system. [VERIFIED: frontend/package.json:18-27] |
| Lucide React | `^0.468.0` | Navigation and action icons | Existing icon dependency and approved UI-SPEC choice. [VERIFIED: frontend/package.json:12-16] |
| FastAPI + Pydantic | Existing backend dependencies | Typed, permission-protected read endpoints and DTO validation | Existing API pattern uses `APIRouter`, response models, `Depends`, and Pydantic schemas. [VERIFIED: backend/app/api/semantic.py:146-166] |
| SQLAlchemy | Existing backend dependency | Filtered joins, aggregate counts, stable ordering, and batch loading | Existing semantic persistence and query services use SQLAlchemy ORM/select constructs. [VERIFIED: backend/app/models/semantic.py:1-6] [VERIFIED: backend/app/services/semantic/version_service.py:370-385] |

### Supporting

| Facility | Existing contract | Purpose | When to Use |
|----------|-------------------|---------|-------------|
| `apiGet` / shared response helpers | `cache: "no-store"`, request timeout, external AbortSignal forwarding | Authenticated reads and cancellation | All semantic catalog requests; extend error shape without replacing the shared client. [VERIFIED: frontend/lib/api.ts:39-64] |
| Node built-in test runner | `node --test tests/*.test.mjs` | Pure view-model and HTTP error tests | Query parsing, state partitioning, safe-return validation, and request race handling. [VERIFIED: frontend/package.json:5-10] |
| pytest | 8.4.2 available locally | API/query/security contract tests | Backend projection, temporal, pagination, redaction, and permission cases. [VERIFIED: local command `python -m pytest --version`, 2026-08-25] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Existing React state/effects plus pure view model | Add a query/cache package | Rejected for this phase: no new dependency is needed, and scope-safe keys plus AbortSignal fit the existing client. |
| Additive projection endpoints | Expand every legacy CRUD DTO | Rejected: catalog/detail fields span multiple permission domains and would overload mutation-oriented contracts. |
| Server-computed effective projection | Client-select a version from a list | Rejected: it would duplicate and risk diverging from the canonical resolver. |
| Bounded CSS/list visualization | Add a graph library | Rejected by the approved UI contract and unnecessary for the capped one-root chain. |

**Installation:** No package installation is recommended. Use the existing lockfile and dependencies.

## Package Legitimacy Audit

Not applicable. Phase 11 should install no external packages, so the package legitimacy gate has no candidates to audit.

## Verified Domain Vocabulary

The following discrete values were read from their source-of-truth definitions and must be copied verbatim into schemas, fixtures, and view-model partitions:

- Concept types: `"business_term", "metric", "dimension", "code_set", "business_rule", "regulatory_rule"`. [VERIFIED: backend/app/schemas/semantic.py:7-8]
- Semantic lifecycle statuses: `"draft", "ai_suggested", "confirmed", "rejected", "deprecated"`. [VERIFIED: backend/app/schemas/semantic.py:7-9]
- Trusted, candidate, and audit-only tuples: `("confirmed",)`, `("confirmed", "draft", "ai_suggested")`, and `("rejected", "deprecated")`. [VERIFIED: backend/app/services/semantic/status_policy.py:14-21]
- Binding entity types: `"target_table", "target_field", "mart_table", "mart_field", "source_table", "source_field", "scenario", "knowledge_unit", "source_to_mart_mapping", "mart_to_ybt_mapping", "scenario_business_mapping", "scenario_technical_lineage"`. [VERIFIED: backend/app/schemas/semantic.py:10-14]
- Relation types: `"is_a", "part_of", "uses", "derived_from", "classified_by", "identified_by", "reported_as", "governed_by", "related_to"`. [VERIFIED: backend/app/schemas/semantic.py:15-18]
- PendingQuestion schema statuses: `"open", "assigned", "answered", "accepted", "rejected", "closed"`; the existing open-summary tuple is `("open", "assigned", "answered")`. [VERIFIED: backend/app/schemas/deliverables.py:111-117] [VERIFIED: backend/app/api/deliverables.py:900-910]

## Architecture Patterns

### System Architecture Diagram

```text
Browser route (/semantics or /semantics/[id])
  -> parse + canonicalize URL state
  -> key request by project + concept + as_of + tab + filters
  -> shared authenticated API client (AbortSignal, typed status error)
  -> project-scoped semantic catalog endpoint
       -> PermissionService project visibility
       -> base SemanticConcept identity query
       -> explicit trusted/candidate/audit visibility branch
       -> resolve_effective_versions(batch, as_of, project_id)
       -> aggregate bindings/relations/reviews in set-based subqueries
       -> per-region permission gates
            -> readable target: minimal lawful display reference
            -> unreadable target: translated type + restricted=true only
       -> projection DTO (no persisted duplicate facts)
  -> current request scope still matches?
       -> yes: render grouped/table or selected detail region
       -> no: discard late response
  -> local error?
       -> header/list error: route-level retry state
       -> lazy tab error: tab-only retry state; retain loaded header
```

### Recommended Project Structure

```text
backend/app/
├── api/semantic_catalog.py                 # additive read-only routes
├── schemas/semantic_catalog.py             # projection DTOs only
└── services/semantic/catalog_query_service.py # joins, aggregates, redaction

frontend/
├── app/semantics/page.tsx
├── app/semantics/[id]/page.tsx
├── components/semantic-catalog/            # approved route components
├── lib/semantic-catalog-view-model.mjs
├── lib/semantic-catalog-view-model.d.mts
└── tests/semantic-catalog-view-model.test.mjs

backend/tests/
└── test_semantic_catalog_api.py
```

These are recommended new boundaries, not existing files. Keep `frontend/components/AppShell.tsx` to a narrow navigation-entry edit because it currently contains user-owned uncommitted changes. [VERIFIED: `git status --short`, 2026-08-25]

### Pattern 1: Projection-Only Query Service

**What:** A service returns catalog/detail DTO inputs assembled from existing tables. It performs no writes and persists no projection table.

**When to use:** Both route families, especially whenever totals, temporal resolution, related counts, review state, or permission-safe references cross model boundaries.

**Recommended endpoints (new, not currently implemented):**

| Endpoint | Response responsibility |
|----------|-------------------------|
| `GET /projects/{project_id}/semantic-catalog` | Filtered population, server total, page metadata, facets, effective version summary, current confirmed binding count, active review summary. |
| `GET /projects/{project_id}/semantic-catalog/{concept_id}` | Identity plus Overview/header projection and canonical effective version for `as_of`. |
| `GET .../{concept_id}/bindings` | Confirmed/candidate partitions and permission-safe target references. |
| `GET .../{concept_id}/relations` | Directional one-hop relations with trusted/candidate/audit partitioning. |
| `GET .../{concept_id}/evidence` | Lawful source/evidence references; temporal capability declared per item/region. |
| `GET .../{concept_id}/lineage` | Capped Target/Mart/Source chain and text equivalent data. |
| `GET .../{concept_id}/governance` | Lifecycle, active review workflow, conflict, question, and lawful audit summaries. |
| `GET .../{concept_id}/versions` | Chronological version timeline, including explicit audit access when authorized. |

Keep existing Phase 8 endpoints compatible. The existing effective endpoint is exactly `"/projects/{project_id}/semantic-concepts/{concept_id}/versions/effective"` and calls the canonical resolver with `as_of or date.today()`. [VERIFIED: backend/app/api/semantic.py:198-211]

### Pattern 2: One Filtered Population, Multiple Aggregates

Build one base population from `SemanticConcept.project_id`, explicit visibility mode, search, enums, owner/domain, and flags. Derive `total`, facets, and the page IDs from that same population. Then fetch effective versions and aggregate counts for only page IDs. This avoids both mismatched facet totals and the current per-row version query. Existing catalog pagination demonstrates `count(subquery)`, stable `order_by`, `offset`, and `limit`, but Phase 11 must add permission enforcement and richer filters rather than copying its compressed implementation. [VERIFIED: backend/app/api/catalog.py:16-23]

Stable order must be explicit: business-domain null-last grouping, normalized name/code, then ID as a tie-breaker. Pagination resets to page 1 when a submitted search or immediate filter changes; a response echoes canonical page/page_size and total.

### Pattern 3: Temporal Resolution Stays on the Server

For page IDs, call `resolve_effective_versions(db, ids, as_of, project_id=project_id)` once. Do not call `_attach_version_projection`; it reads the latest version and therefore cannot implement historical `as_of`. [VERIFIED: backend/app/api/semantic.py:650-661] Detail Overview should return a nullable `effective_version`; if absent, formal definition remains empty and candidate content is separately labeled.

### Pattern 4: Server-Side Permission Projection

The top-level catalog/detail identity requires `"project.view"`. Target-specific data must use the permission expected by its existing resource guard: read catalog routes map to `"catalog.search"`, knowledge reads/search map to `"knowledge.search"`, lineage reads map to `"lineage.view"`, and audit reads use `"audit.read"`. [VERIFIED: backend/app/services/auth/resource_guard.py:67-75] [VERIFIED: backend/app/api/audit.py:16-38]

Do not fail the whole detail page merely because one optional region is not readable. Return a region-level forbidden state or omit that region under a documented policy. For an individually restricted binding target that the user may know exists, construct only `{ entity_type, restricted: true }`; do not first serialize the target and then delete fields.

Knowledge scope also needs row-level filtering: project/institution units are limited to the selected project, and global restricted units are excluded by the existing retriever. [VERIFIED: backend/app/services/retrieval/hybrid_retriever.py:41-54] [VERIFIED: backend/app/services/retrieval/hybrid_retriever.py:303-317]

### Pattern 5: URL as Navigation State, Not Request Draft State

The search input keeps a local draft. Enter or Search commits `q` to the URL; enum/filter changes commit immediately. A pure `.mjs` view model parses, validates, canonicalizes, and serializes route state so Node tests can cover it without React. The request key includes project ID, concept ID, `as_of`, tab, filters, page, and view mode. On scope change, abort the old request and also compare the captured key before committing state, because cancellation can race with response settlement. The existing fetch wrapper already forwards an external AbortSignal. [VERIFIED: frontend/lib/api.ts:48-60]

### Pattern 6: Status-Bearing API Errors

Introduce a backward-compatible `ApiError extends Error` carrying `status` and a safe message. Keep the existing 401 branch exactly: remove both session tokens and replace location with `/login`; status-bearing errors apply to non-401 responses. Today `throwApiError` throws plain `Error`, and `normalizeRequestError` creates new plain errors, so callers cannot reliably distinguish 403 from 500. [VERIFIED: frontend/lib/http-response.mjs:70-97]

### Pattern 7: Lazy Region State Machines

Load the detail shell/Overview first. Each non-overview tab owns `idle | loading | success-empty | success-populated | forbidden | error`, its request key, and its retry action. Keep the header mounted when a tab fails. Exact historical copy for current-only regions is `当前状态，不代表该历史日期`; it is applied per region, never as a global flag that suppresses truly temporal evidence. [VERIFIED: .planning/phases/11-semantic-catalog-ui/11-UI-SPEC.md:479-488]

### Anti-Patterns to Avoid

- **Client-side pretend-global search:** filtering only the loaded page produces false results and totals; send committed query/filter state to the server.
- **N+1 version projection:** calling `_attach_version_projection` for every catalog row repeats a query and selects latest rather than effective truth.
- **Legacy definition fallback:** never populate the formal definition from `SemanticConcept.definition` or AI suggestion when no effective confirmed version exists.
- **Redact after serialization:** hidden values can leak through DOM attributes, tooltips, React state, logs, or cached JSON.
- **Global detail failure:** one lineage/evidence request must not replace a successful header with an error page.
- **Lifecycle/workflow conflation:** `confirmed` and a pending ReviewTask can coexist; display them as separate dimensions.
- **Audit contamination:** `rejected` and `deprecated` must not enter trusted counts, graph edges, formal facts, or default results.
- **Unvalidated return URL:** do not navigate directly to arbitrary `returnTo`; accept only decoded, normalized relative `/semantics` destinations and reject absolute, protocol-relative, backslash, control-character, or repeated-encoding bypasses.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Effective-date selection | A client-side sort-and-pick resolver | `resolve_effective_versions(...)` | It already enforces trusted statuses, project scope, inclusive dates, and ambiguity errors. [VERIFIED: backend/app/services/semantic/version_service.py:357-417] |
| Authentication/session redirect | A route-specific token handler | Shared `api.ts` / `http-response.mjs` | The shared helper already clears both tokens and redirects on 401. [VERIFIED: frontend/lib/http-response.mjs:82-90] |
| Authorization | Visibility inferred from UI role names | `PermissionService` and resource guards | Visible-project 403/404 semantics and permission sets are centralized. [VERIFIED: backend/app/services/auth/permission_service.py:94-155] |
| Semantic status sets | Repeated string arrays in endpoints/components | `status_policy.py` on backend; one mirrored tested view-model mapping | Existing source explicitly centralizes trusted/candidate/audit partitions. [VERIFIED: backend/app/services/semantic/status_policy.py:1-21] |
| Graph layout engine | Free-drag canvas/physics | Bounded CSS chain plus structured list | The approved scope is one small capped `Concept -> Target -> Mart -> Source` visualization. |
| Client cache library | New cross-app cache layer | Route-local keyed state + AbortController | Sufficient for two routes and avoids new dependency/risk. |
| Duplicate fact storage | Materialized semantic detail table | Projection DTO over existing stores | The phase is read-oriented and existing tables remain authoritative. |

**Key insight:** The difficult part is not visual rendering; it is preserving canonical temporal truth and permission boundaries while combining multiple stores. The query service should therefore be the deepest module, with the React layer consuming already-partitioned, already-redacted data.

## Common Pitfalls

### Pitfall 1: Latest Version Masquerades as Effective Version

**What goes wrong:** Historical pages show the newest definition or a future version.

**Why it happens:** The existing list helper orders by `version_no DESC` and knows nothing about `as_of`. [VERIFIED: backend/app/api/semantic.py:650-661]

**How to avoid:** Batch-call the canonical resolver for catalog pages and call the same service for detail.

**Warning signs:** A client sorts versions, a projection calls `_attach_version_projection`, or inclusive boundary tests fail.

### Pitfall 2: Counts and Facets Drift from Results

**What goes wrong:** The UI says 18 results while page/filter rows represent a different population.

**Why it happens:** Separate queries omit one filter or include audit/candidate rows differently.

**How to avoid:** Derive page IDs, total, and facets from a single filtered base subquery and test all status/filter combinations.

**Warning signs:** Filters are reimplemented in multiple service methods or counts are computed after pagination.

### Pitfall 3: Restricted Target Data Leaks

**What goes wrong:** A placeholder looks restricted but sensitive name/code/id still exists in JSON, DOM, href, accessible name, title, or cache.

**Why it happens:** The backend returns full target objects and the client hides fields visually.

**How to avoid:** Decide lawfulness before DTO construction; serialize a distinct restricted-reference type with no sensitive fields.

**Warning signs:** A union shares `id`, `name`, or `href` fields across readable and restricted variants.

### Pitfall 4: Stale Project Response Wins

**What goes wrong:** Switching from Project A to B briefly or permanently renders A data under B.

**Why it happens:** An earlier request resolves after the scope changes.

**How to avoid:** Abort on dependency change and compare an immutable request key before setting state.

**Warning signs:** Cache keys omit project/concept/date/tab/filter or tests only cover in-order responses.

### Pitfall 5: Errors Render as Empty Data

**What goes wrong:** 403 or 500 becomes `无数据`, hiding operational and authorization problems.

**Why it happens:** Current frontend errors discard HTTP status. [VERIFIED: frontend/lib/http-response.mjs:82-97]

**How to avoid:** Preserve status in a typed error and model empty only after a successful response.

**Warning signs:** Components inspect localized error strings to infer unauthorized state.

### Pitfall 6: Resolved Questions Pollute Current Summaries

**What goes wrong:** Governance attention counts include closed historical matters.

**Why it happens:** The full schema contains `"open", "assigned", "answered", "accepted", "rejected", "closed"`, while existing current summary behavior explicitly uses `("open", "assigned", "answered")`. [VERIFIED: backend/app/schemas/deliverables.py:111-117] [VERIFIED: backend/app/api/deliverables.py:900-910]

**How to avoid:** Reuse the existing open-summary tuple for current summaries and keep other states in Governance/audit history.

**Warning signs:** `question_status != "closed"` is used as a substitute for an explicit current-state set.

### Pitfall 7: New Work Overwrites the Ongoing Frontend Rebuild

**What goes wrong:** Adding navigation accidentally removes the user's current `AppShell.tsx` restructuring.

**Why it happens:** The file is already modified in the worktree. [VERIFIED: `git status --short`, 2026-08-25]

**How to avoid:** Planner assigns a narrow, serial AppShell task; executor reads the current file immediately before patching and reviews the resulting diff.

**Warning signs:** A worker replaces the entire component or applies an old-file patch.

## Code Examples

These are implementation skeletons derived from verified local APIs; new names and DTO shapes are recommendations rather than claims about existing code.

### Batch Effective Projection

```python
# Existing resolver source: backend/app/services/semantic/version_service.py:357-417
page_ids = [row.id for row in concepts]
effective_by_concept = resolve_effective_versions(
    db,
    page_ids,
    as_of,
    project_id=project_id,
)
items = [
    build_catalog_item(
        concept,
        effective_version=effective_by_concept.get(concept.id),
        aggregates=aggregates_by_concept.get(concept.id),
    )
    for concept in concepts
]
```

### Permission-Safe Reference Union

```python
# Recommended DTO shape. Allowed entity_type values are quoted in
# "Verified Domain Vocabulary" from backend/app/schemas/semantic.py:10-14.
class RestrictedAssetReference(BaseModel):
    entity_type: EntityType
    restricted: Literal[True] = True

class ReadableAssetReference(BaseModel):
    entity_type: EntityType
    restricted: Literal[False] = False
    entity_id: int
    display_name: str
    href: str
```

Never construct `ReadableAssetReference` until the target resource permission check has passed. A restricted response must not contain nullable versions of protected fields; absence is easier to test and safer than `null` placeholders.

### Backward-Compatible Status Error

```javascript
// Existing 401 behavior remains as implemented in frontend/lib/http-response.mjs:82-90.
export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// For non-401 responses only:
throw new ApiError(formatApiErrorText(await response.text(), response.status), response.status);
```

`normalizeRequestError` must preserve an existing `ApiError` rather than wrap it into plain `Error`, while still translating `AbortError` and network `TypeError` as today. [VERIFIED: frontend/lib/http-response.mjs:70-90]

### Scope-Safe Request Effect

```typescript
useEffect(() => {
  const controller = new AbortController();
  const requestKey = makeSemanticRequestKey({ projectId, conceptId, asOf, tab, filters });
  activeKeyRef.current = requestKey;

  void loadSemanticRegion({ signal: controller.signal })
    .then((result) => {
      if (activeKeyRef.current === requestKey) setRegion({ kind: "success", result });
    })
    .catch((error) => {
      if (!controller.signal.aborted && activeKeyRef.current === requestKey) {
        setRegion({ kind: "error", error });
      }
    });

  return () => controller.abort();
}, [projectId, conceptId, asOf, tab, filters]);
```

The shared fetch wrapper already accepts and forwards the caller's AbortSignal. [VERIFIED: frontend/lib/api.ts:48-60]

## State of the Art

| Old/Current Approach | Required Phase 11 Approach | Impact |
|----------------------|----------------------------|--------|
| `list[SemanticConceptRead]`, hard limit, code/name search | Paginated semantic catalog projection with total/facets and alias/definition search | Makes server results authoritative for the whole project. [VERIFIED: backend/app/api/semantic.py:74-96] |
| Per-row latest-version projection | One batch effective-date resolution | Removes N+1 behavior and makes historical/current views consistent. [VERIFIED: backend/app/api/semantic.py:650-661] [VERIFIED: backend/app/services/semantic/version_service.py:357-417] |
| Plain frontend `Error` | Status-bearing `ApiError` preserving 401 redirect | Enables explicit unauthorized versus operational failure UI. [VERIFIED: frontend/lib/http-response.mjs:82-97] |
| One large detail fetch/render boundary | Overview-first shell plus lazy independent regions | Local failures remain local and tabs can be retried independently. |
| Client-hidden restricted values | Server-minimized reference union | Prevents sensitive values from entering browser state at all. |

**Deprecated/outdated for this phase:** `_attach_version_projection` is acceptable only for legacy compatibility; it must not drive catalog `as_of` or formal detail definition. [VERIFIED: backend/app/api/semantic.py:650-661]

## Test Strategy

The formal `## Validation Architecture` section is intentionally omitted because `workflow.nyquist_validation` is explicitly `false`. [VERIFIED: .planning/config.json:7-13] This does not waive acceptance testing: D-30 and the approved UI-SPEC require the full 28-row state matrix. [VERIFIED: .planning/phases/11-semantic-catalog-ui/11-UI-SPEC.md:455-490]

### Existing Baseline

- Frontend command: `npm test`; baseline on 2026-08-25 was 26 passing tests. [VERIFIED: local command `npm test`, 2026-08-25]
- Backend focused command: `python -m pytest -q tests/test_semantic_layer.py tests/test_governance.py`; baseline on 2026-08-25 was 48 passing tests. [VERIFIED: local command, 2026-08-25]
- Local environment currently has Node `v24.15.0`, npm `8.6.0`, Python `3.12.4`, pytest `8.4.2`, and `frontend/node_modules` present. [VERIFIED: local availability commands, 2026-08-25]

### Required Test Decomposition

| Layer | New/updated test target | Required coverage |
|-------|-------------------------|-------------------|
| Pure frontend view model | `frontend/tests/semantic-catalog-view-model.test.mjs` | URL parse/canonicalize/serialize; `未分类` grouping; status partitions; trusted counts; current-only labels; safe destination/returnTo; long/invalid values. |
| Shared HTTP layer | `frontend/tests/http-response.test.mjs` | `ApiError.status`; 401 redirect unchanged; normalization preserves typed errors; 403 and 500 remain distinguishable. Existing file is present. [VERIFIED: `rg --files frontend/tests`, 2026-08-25] |
| Backend catalog API | `backend/tests/test_semantic_catalog_api.py` | Project isolation, 403/404, filters/search, total/facets, stable pagination, inclusive `as_of`, ambiguity, no N+1, audit isolation, confirmed counts, lazy region errors, redaction. |
| Existing semantic/governance regression | `backend/tests/test_semantic_layer.py`, `backend/tests/test_governance.py` | Existing lifecycle, graph, resolver, and ReviewTask behavior remains green. [VERIFIED: `rg --files backend/tests`, 2026-08-25] |
| Route/component interaction | Add the smallest existing-compatible harness or isolate stateful route controllers behind pure functions | All SUI-01 through SUI-28 visible-state and interaction assertions from approved UI-SPEC. [VERIFIED: .planning/phases/11-semantic-catalog-ui/11-UI-SPEC.md:459-488] |
| Visual/responsive | Browser screenshots at 320x720, 768x1024, 1280x800, 1440x900 | No overlap/page overflow; stable skeleton dimensions; deliberate table/tab scroll only; nonblank bounded visualization; visible keyboard focus. [VERIFIED: .planning/phases/11-semantic-catalog-ui/11-UI-SPEC.md:490-490] |

Split the 28 cases across pure view-model, backend contract, and route interaction tests; do not force every state through slow browser E2E. SUI-22 requires assertions against both API JSON and DOM/accessibility output. SUI-10 requires an out-of-order deferred-response fixture, not only an AbortController spy. SUI-20 must test equality at both effective boundaries.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| Node.js | Frontend tests/build | Yes | v24.15.0 | Use repository-supported local Node if CI constrains engines. |
| npm | Frontend dependency/test commands | Yes | 8.6.0 | None required. |
| Frontend installed dependencies | Frontend tests/build | Yes | Present under `frontend/node_modules` | `npm ci` from existing lockfile if removed. |
| Python | Backend tests/API | Yes | 3.12.4 | None required. |
| pytest | Focused backend verification | Yes | 8.4.2 | None required. |
| External research providers | Library documentation lookup | Context7 quota unavailable | Not applicable | No external library claims or new packages are required; rely on verified repository contracts. |

**Missing dependencies with no fallback:** None identified for planning or implementation.

**Missing dependencies with fallback:** External documentation lookup was unavailable, but this phase uses only the verified existing stack and local patterns.

## Security Domain

Security enforcement is enabled because `.planning/config.json` does not set `security_enforcement` to `false`. [VERIFIED: .planning/config.json:1-19]

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| V2 Authentication | Yes | Reuse the secured router dependency and shared 401 session redirect; do not add route-local authentication. The semantic router is included with `dependencies=secured`. [VERIFIED: backend/app/main.py:183-183] |
| V3 Session Management | Yes | Preserve existing token removal and `/login` replacement on 401. [VERIFIED: frontend/lib/http-response.mjs:82-90] |
| V4 Access Control | Yes | Enforce project visibility, per-region permissions, row scope, and server-side field minimization. [VERIFIED: backend/app/services/auth/permission_service.py:94-155] |
| V5 Input Validation | Yes | Pydantic/Query validation for enums, positive IDs, page bounds and ISO date; whitelist destinations and canonicalize URL state. Existing semantic types are strict Literals. [VERIFIED: backend/app/schemas/semantic.py:7-18] |
| V6 Cryptography | No new cryptographic operation | Reuse existing transport/session infrastructure; Phase 11 must not introduce custom crypto. |
| V9 Communications | Yes | Retain `Cache-Control: no-store`, `nosniff`, frame denial, no-referrer, and restricted Permissions-Policy headers already applied by middleware. [VERIFIED: backend/app/core/observability.py:45-50] |
| V14 Configuration | Yes | No new public route, no debug payload leakage, deterministic error DTOs, and bounded query/page limits. |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Cross-project object reference | Spoofing / Information Disclosure | Load through `PermissionService`, constrain every join by project, return 404 for invisible project/resource. [VERIFIED: backend/app/services/auth/permission_service.py:120-155] |
| Restricted target metadata leak | Information Disclosure | Construct a separate restricted DTO before serialization; test JSON, DOM, accessibility tree, href, title, and cache. |
| Query/filter abuse | Denial of Service | Bound page size, normalize query length, use indexed predicates where available, and avoid per-row queries. Semantic tables already index project/status/name/effective fields. [VERIFIED: backend/app/models/semantic.py:11-18] [VERIFIED: backend/app/models/semantic.py:45-57] |
| Unsafe `returnTo` open redirect | Spoofing | Decode once under a strict parser, require a relative `/semantics` path, reject `//`, schemes, backslashes, control characters, and encoded bypasses. |
| Audit-state trust confusion | Tampering / Repudiation | Explicit visibility mode; rejected/deprecated only through named audit/history operation; never include in trusted counts. [VERIFIED: backend/app/services/semantic/status_policy.py:14-21] |
| Sensitive cache reuse across project/date | Information Disclosure | `no-store`; scope-complete request keys; abort plus late-response key check; clear region state on project/concept changes. [VERIFIED: frontend/lib/api.ts:39-64] |

## Planning Decomposition

Plan in dependency order so DTO/query policy is locked before presentation work:

1. **Wave 0, contract tests and shared error seam:** Add failing backend projection/security tests and frontend view-model/error tests. Preserve 401 behavior while adding status-bearing errors.
2. **Wave 1, backend read model:** Add projection schemas/service, catalog endpoint, detail shell, and lazy region endpoints. Reuse batch temporal resolver; implement one-population totals/facets and server redaction.
3. **Wave 2, pure frontend model and shell:** Implement URL state, partitions, destination validation, request keys, shared async-state helpers, and narrow AppShell navigation patch.
4. **Wave 3, catalog route:** Build toolbar, grouped directory, comparison table, pagination, accessibility announcements, and catalog states.
5. **Wave 4, detail route:** Build Overview-first shell, tabs, bindings/relations/evidence/lineage/governance/versions, bounded visualization, and current-only historical labels.
6. **Wave 5, convergence:** Run the full 28-state matrix, responsive screenshots, keyboard checks, backend/frontend regressions, and inspect network payloads for restricted-data leakage.

Do not parallelize writes to `AppShell.tsx` with other shell work, and do not assign two writers to the shared API/error layer. Backend projection and pure frontend view-model work can proceed in parallel after DTO fields and error semantics are agreed.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | [ASSUMED] FastAPI, Pydantic, and SQLAlchemy installed versions are compatible with the existing code patterns; exact package versions were not re-queried because no new dependency is proposed. | Standard Stack | Low; implementation uses current repository APIs, but environment lock metadata should remain authoritative. |
| A2 | [ASSUMED] The recommended new endpoint paths are acceptable additive names; CONTEXT.md leaves endpoint shape to the agent's discretion. | Architecture Patterns | Low; planner may choose a different additive prefix without changing responsibilities. |
| A3 | [ASSUMED] A distinct region-level forbidden state is preferable to failing the entire detail response for optional permissions. | Permission Projection | Medium; product/security owners may prefer omission or whole-page denial for a particular region. |
| A4 | [ASSUMED] No database migration is required because all new data is projection-only. | Architecture Patterns | Medium; a performance index may become necessary after query-plan measurement on production-scale data. |
| A5 | [ASSUMED] ASVS category naming and mapping follows the standard taxonomy from training knowledge; official ASVS documentation could not be fetched due provider quota. | Security Domain | Low; the concrete controls are verified against repository code. |

## Open Questions

1. **Should optional forbidden regions return HTTP 403, a typed `forbidden` region payload, or be omitted?**
   - What we know: top-level invisible resources must not leak identity, while D-27 permits type-only restricted binding references.
   - What's unclear: the uniform wire contract for an entire forbidden Evidence/Lineage/Governance region.
   - Recommendation: use HTTP 403 for standalone lazy region endpoints and let the client render a region-level unauthorized state; use restricted-reference DTOs only when the binding itself is lawfully visible.

2. **Which existing destination routes can accept every allowed binding entity type?**
   - What we know: the entity-type allow-list contains 12 exact values, while D-26 names Target, Mart, Source, Knowledge, and Lineage destinations. [VERIFIED: backend/app/schemas/semantic.py:10-14]
   - What's unclear: some mapping/scenario types may lack a stable detail route.
   - Recommendation: define a server/client shared allow-list of canonical destinations; render readable but non-navigable text when no existing route exists rather than inventing a Phase 11 route.

3. **Will query-plan evidence require new composite/search indexes?**
   - What we know: concept project/status/name and version project/status/effective indexes exist. [VERIFIED: backend/app/models/semantic.py:11-18] [VERIFIED: backend/app/models/semantic.py:45-57]
   - What's unclear: dataset size, database engine behavior for alias JSON/definition search, and production latency targets.
   - Recommendation: begin with set-based SQL and measure representative 700+ concept fixtures; add only evidence-backed indexes/migrations.

4. **How should audit authorization interact with rejected/deprecated catalog filtering?**
   - What we know: audit access uses `"audit.read"`; default trusted/candidate sets exclude `"rejected", "deprecated"`. [VERIFIED: backend/app/api/audit.py:16-38] [VERIFIED: backend/app/services/semantic/status_policy.py:14-21]
   - What's unclear: whether explicit semantic audit filters require `audit.read` or only `project.view` under current product policy.
   - Recommendation: require `audit.read` for any endpoint/filter that exposes audit-only semantic rows and test both 403 and successful audit paths.

## Sources

### Primary (HIGH confidence)

- `.planning/phases/11-semantic-catalog-ui/11-CONTEXT.md` - D-01 through D-30, discretion, and deferred scope.
- `.planning/phases/11-semantic-catalog-ui/11-UI-SPEC.md` - approved UI/API integrity contract and SUI-01 through SUI-28 state matrix.
- `.planning/REQUIREMENTS.md` - SUI-01 and SUI-02 requirement text.
- `backend/app/api/semantic.py` - current endpoints, filters, limits, permissions, and per-row latest projection.
- `backend/app/services/semantic/version_service.py` - canonical batch effective-date resolver.
- `backend/app/services/semantic/status_policy.py` - trusted/candidate/audit visibility vocabularies.
- `backend/app/services/auth/permission_service.py` and `resource_guard.py` - project visibility and permission mapping.
- `backend/app/models/semantic.py` and `backend/app/schemas/semantic.py` - source-of-truth fields and discrete vocabularies.
- `frontend/lib/api.ts` and `frontend/lib/http-response.mjs` - cancellation, no-store, auth redirect, and error behavior.
- Local test and environment commands executed 2026-08-25 - baseline and availability evidence.

### Secondary (MEDIUM confidence)

- None. External documentation provider lookup was blocked by quota, so no external factual claim is presented as verified.

### Tertiary (LOW confidence)

- ASVS taxonomy mapping is marked in Assumption A5; repository-specific mitigations themselves are locally verified.

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH - all recommended implementation dependencies already exist in `frontend/package.json` or current backend code; no new package is proposed.
- Architecture: HIGH - based on approved D-01 through D-30/UI-SPEC and direct inspection of the temporal, semantic, permission, governance, retrieval, audit, and frontend request layers.
- Pitfalls: HIGH - each critical failure mode is either present in current code or explicitly covered by the approved 28-state matrix.
- Security: HIGH for repository controls; MEDIUM for formal ASVS taxonomy labels because external documentation lookup was unavailable.

**Research date:** 2026-08-25
**Valid until:** 2026-09-24 (stable existing stack; refresh sooner if Phase 8-10 semantic or permission contracts change)
