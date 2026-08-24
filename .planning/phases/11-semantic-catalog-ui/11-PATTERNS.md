# Phase 11: Semantic Catalog UI - Pattern Map

**Mapped:** 2026-08-25  
**Files analyzed:** 27 explicit or implied new/modified product and test files  
**Analogs found:** 21 / 27 (direct or role/data-flow match)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/app/api/semantic_catalog.py` | route/controller | request-response, read projection | `backend/app/api/semantic.py` | exact role + domain |
| `backend/app/schemas/semantic_catalog.py` | schema/DTO | transform/read projection | `backend/app/schemas/semantic.py` | exact role |
| `backend/app/services/semantic/catalog_query_service.py` | service/query | CRUD read, batch transform | `backend/app/services/semantic/version_service.py` | exact service + temporal; partial aggregate |
| `backend/app/main.py` | config/router registration | request-response wiring | existing `include_router` registrations | exact role |
| `frontend/app/semantics/page.tsx` | route/component | request-response, paginated read | `frontend/app/catalog/page.tsx` | exact role + project-aware catalog |
| `frontend/app/semantics/[id]/page.tsx` | route/component | request-response, lazy regions | `frontend/app/lineage/page.tsx` | role match; lazy tabs gap |
| `frontend/components/semantic-catalog/CatalogToolbar.tsx` | component | form/filter transform | `frontend/app/catalog/page.tsx` toolbar | role match |
| `frontend/components/semantic-catalog/GroupedSemanticDirectory.tsx` | component | projection-to-list transform | `frontend/app/catalog/page.tsx` table/list sections | role match |
| `frontend/components/semantic-catalog/SemanticComparisonTable.tsx` | component | projection-to-table | `frontend/components/LineageGraph.tsx` | role + accessible overflow table |
| `frontend/components/semantic-catalog/SemanticStatus.tsx` | component/utility | status transform | `frontend/app/review-tasks/page.tsx` `statusBadge` | exact status presentation role; separate workflow dimension is new |
| `frontend/components/semantic-catalog/SemanticDetailHeader.tsx` | component | read projection + URL state | `frontend/components/WorkspaceHeader.tsx` | role match |
| `frontend/components/semantic-catalog/SemanticTabs.tsx` | component | URL-backed navigation | no complete analog | no direct analog |
| `frontend/components/semantic-catalog/AsyncRegion.tsx` | component/state | local async request-response | `frontend/components/LineageGraph.tsx` empty state | partial; state machine is new |
| `frontend/components/semantic-catalog/TrustSourceRegion.tsx` | component | read projection transform | `frontend/app/review-tasks/page.tsx` status/metadata rows | role match; provenance consolidation is new |
| `frontend/components/semantic-catalog/BindingList.tsx` | component | read projection, permission-safe union | `frontend/components/LineageGraph.tsx` edge rows | partial; restricted DTO is new |
| `frontend/components/semantic-catalog/BindingChain.tsx` | component | bounded transform/visualization | `frontend/components/LineageGraph.tsx` | exact bounded-display intent; different domain |
| `frontend/components/semantic-catalog/RelationList.tsx` | component | read projection, one-hop graph | `frontend/components/LineageGraph.tsx` | role + bounded graph match |
| `frontend/components/semantic-catalog/VersionTimeline.tsx` | component | chronological read + inline state | `frontend/app/catalog/page.tsx` lazy table columns | partial; timeline/disclosure is new |
| `frontend/lib/semantic-catalog-view-model.mjs` | utility/view model | transform, URL serialization, partition | `frontend/lib/workspace-view-model.mjs` | exact pure view-model pattern |
| `frontend/lib/semantic-catalog-view-model.d.mts` | type declaration | transform contract | `frontend/lib/workspace-view-model.d.mts` | exact role |
| `frontend/lib/api.ts` | shared client | authenticated request-response, cancellation | current `api.ts` | exact existing client; extend narrowly |
| `frontend/lib/http-response.mjs` | utility/error seam | error transform | current `http-response.mjs` | exact role |
| `frontend/lib/http-response.d.mts` | type declaration | error contract | current declaration | exact role |
| `frontend/lib/types.ts` | shared DTO types | API-to-UI transform | existing catalog types | exact role |
| `frontend/components/AppShell.tsx` | shell/navigation | route navigation | current `AppShell.tsx` | exact role; dirty-file caution |
| `frontend/tests/semantic-catalog-view-model.test.mjs` | test | pure transform/state | `frontend/tests/workspace-view-model.test.mjs` | exact role |
| `frontend/tests/http-response.test.mjs` | test | error behavior | current HTTP tests | exact role; extend 403/500 typed status |
| `backend/tests/test_semantic_catalog_api.py` | API/security test | request-response, project scope | `backend/tests/test_semantic_layer.py` | exact domain/security harness |

The `components/semantic-catalog` list is the approved UI contract. Components may be combined when trivial, but the planner should preserve the ownership boundaries for async regions, redaction, status dimensions, and URL state.

## Pattern Assignments

### `backend/app/api/semantic_catalog.py` (controller, request-response)

**Analog:** `backend/app/api/semantic.py`

**Imports and router pattern** (`backend/app/api/semantic.py:1-48`):

```python
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.auth.dependencies import CurrentPrincipal
from app.services.auth.permission_service import PermissionService

router = APIRouter(tags=["regulatory semantics"])
```

Use a separate additive router and register it with the existing secured API prefix. Keep read-only projection routes separate from mutation-oriented semantic CRUD routes.

**Project authorization and read route** (`backend/app/api/semantic.py:74-96`):

```python
@router.get("/projects/{project_id}/semantic-concepts", response_model=list[SemanticConceptRead])
def list_concepts(...):
    PermissionService(db, principal).require_project_permission(project_id, "project.view")
    statement = select(SemanticConcept).where(SemanticConcept.project_id == project_id)
    ...
    concepts = list(db.scalars(statement.order_by(SemanticConcept.id).limit(limit)).all())
    return [_attach_version_projection(db, concept) for concept in concepts]
```

Copy the permission boundary and typed `Query` bounds, but do not copy the hard-limit list or per-row `_attach_version_projection`. The catalog route must derive filters, total/facets, and page IDs from one population and call the batch effective resolver once.

**Effective-version route pattern** (`backend/app/api/semantic.py:198-211`):

```python
PermissionService(db, principal).require_project_permission(project_id, "project.view")
get_project_semantic_resource(db, project_id, "semantic_concept", concept_id)
return resolve_effective_version(db, concept_id, as_of or date.today(), project_id=project_id)
```

The detail shell should preserve this project check and resource lookup, then delegate the additive projection to the query service. Optional tabs should have independent endpoints and not make the header depend on all region permissions.

**Binding/relation filter pattern** (`backend/app/api/semantic.py:299-320`, `387-407`):

```python
statement = select(SemanticBinding).where(SemanticBinding.project_id == project_id)
for column, value in (
    (SemanticBinding.semantic_concept_id, semantic_concept_id),
    (SemanticBinding.entity_type, entity_type),
    (SemanticBinding.entity_id, entity_id),
    (SemanticBinding.status, status),
):
    if value is not None:
        statement = statement.where(column == value)
return list(db.scalars(statement.order_by(SemanticBinding.id).limit(limit)).all())
```

Use this as the starting shape for region queries, adding explicit trusted/candidate/audit mode, stable ordering, and server-side target permission before constructing a DTO.

### `backend/app/schemas/semantic_catalog.py` (schema, transform)

**Analog:** `backend/app/schemas/semantic.py`

**Strict vocabulary and ORM DTO pattern** (`backend/app/schemas/semantic.py:7-22`):

```python
ConceptType = Literal["business_term", "metric", "dimension", "code_set", "business_rule", "regulatory_rule"]
SemanticStatus = Literal["draft", "ai_suggested", "confirmed", "rejected", "deprecated"]
EntityType = Literal["target_table", "target_field", "mart_table", "mart_field", ...]

class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
```

Reuse exact literals rather than inventing UI-only enum strings. New catalog DTOs should use `extra="forbid"`, bounded strings/lists, stable IDs, and explicit unions for readable versus restricted references. A restricted reference must omit `entity_id`, name, code, `href`, title, and metadata entirely.

**Canonical version DTO fields** (`backend/app/schemas/semantic.py:180-208`):

```python
class SemanticConceptVersionRead(OrmModel):
    id: int
    semantic_concept_id: int
    project_id: int
    version_no: int
    concept_name: str
    definition: str | None
    aliases_json: list[str]
    business_domain: str | None
    owner_department: str | None
    provenance_json: dict
    status: str
    confirmed_by: str | None
    confirmed_at: datetime | None
    effective_from: date
    effective_to: date | None
```

The catalog/detail formal definition should be a nullable effective-version projection. Do not backfill it from `SemanticConcept.definition` or AI content when no confirmed effective version exists.

### `backend/app/services/semantic/catalog_query_service.py` (service, CRUD read/batch transform)

**Analog:** `backend/app/services/semantic/version_service.py`

**Batch temporal resolver** (`backend/app/services/semantic/version_service.py:357-402`):

```python
def resolve_effective_versions(db, concept_ids, as_of, *, project_id=None):
    target_date = _as_date(as_of)
    normalized_ids = sorted({int(concept_id) for concept_id in concept_ids})
    if not normalized_ids:
        return {}
    statement = select(SemanticConceptVersion).join(
        SemanticConcept, SemanticConcept.id == SemanticConceptVersion.semantic_concept_id,
    ).where(
        SemanticConceptVersion.semantic_concept_id.in_(normalized_ids),
        SemanticConcept.project_id == SemanticConceptVersion.project_id,
        status_predicate(SemanticConcept.status, SemanticVisibilityMode.TRUSTED),
        status_predicate(SemanticConceptVersion.status, SemanticVisibilityMode.TRUSTED),
        SemanticConceptVersion.effective_from <= target_date,
        or_(SemanticConceptVersion.effective_to.is_(None), SemanticConceptVersion.effective_to >= target_date),
    )
    ...
```

Call `resolve_effective_versions(db, page_ids, as_of, project_id=project_id)` once. Preserve inclusive boundaries and surface `SEMANTIC_VERSION_AMBIGUOUS`; never sort versions in the browser or use `_attach_version_projection`.

**Projection service responsibilities:**

- Build one filtered, project-scoped base population with explicit `trusted`/candidate/audit mode.
- Derive total, facets, and page IDs from that same population.
- Resolve effective versions in one batch and aggregate confirmed binding/relation/review counts set-wise.
- Enforce per-entity permission before constructing readable asset references.
- Return read DTO inputs only; do not persist a semantic detail table or duplicate evidence/knowledge/lineage facts.

**Status policy analog:** `backend/app/services/semantic/status_policy.py:1-21` (referenced by `version_service.py` and tested in `backend/tests/test_semantic_layer.py:368-403`). Trusted is `("confirmed",)`, candidate is `("confirmed", "draft", "ai_suggested")`, audit-only is `("rejected", "deprecated")`. Keep these partitions centralized and exclude audit rows from trusted counts/paths.

### `backend/app/main.py` (router/config, request-response wiring)

**Analog:** existing registrations (`backend/app/main.py:178-184`):

```python
app.include_router(lineage.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(deliverables.router, prefix=settings.api_prefix)
app.include_router(semantic.router, prefix=settings.api_prefix, dependencies=secured)
```

Register `semantic_catalog.router` under `settings.api_prefix` with `dependencies=secured` like the semantic router. Keep route registration separate from the existing router so Phase 8/9 endpoints remain compatible.

### `frontend/app/semantics/page.tsx` (route, request-response)

**Analog:** `frontend/app/catalog/page.tsx:1-47,79-157`

**Project-aware data loading and API imports:**

```tsx
import { useEffect, useState } from "react";
import { useProjectWorkspace } from "@/components/ProjectContext";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { apiGet } from "@/lib/api";

export default function CatalogPage() {
  const { projectId } = useProjectWorkspace();
  ...
  useEffect(() => {
    if (!projectId) return;
    void apiGet<{ items: CatalogTable[]; total: number }>(`/projects/${projectId}/catalog/tables?...`)
      .then((response) => { setTables(response.items); setTableTotal(response.total); });
  }, [projectId, ...filters]);
```

Use the same shell/project boundary and `WorkspaceHeader`, but add URL parse/canonicalize state before requesting, explicit loading/error/403 states, AbortController/key checks, and server-authoritative totals. Search remains a form whose committed `q` changes only on Enter/Search; enum filters update immediately.

**Pagination and empty-state layout** (`frontend/app/catalog/page.tsx:152-157,214-223`):

```tsx
<div className="empty-state m-3">当前筛选下暂无目录表...</div>
<Pagination page={tablePage} pageSize={TABLE_PAGE_SIZE} total={tableTotal} ... />
```

Copy the stable pagination/row dimensions and existing `empty-state` vocabulary, but distinguish loading, successful empty, filtered empty, 403, and 500. Never initialize a failed request as an empty result.

### `frontend/app/semantics/[id]/page.tsx` (route, lazy request-response)

**Analog:** `frontend/app/lineage/page.tsx:1-91` plus `frontend/components/LineageGraph.tsx`.

Reuse the `useProjectWorkspace` project guard and `apiGet` calls, but the existing lineage page has no complete tab/region state machine. Implement header/Overview first, then one request per selected lazy tab keyed by project, concept, `as_of`, and tab. On project/concept/date change abort the previous request and ignore late responses whose immutable request key no longer matches. A tab error retains the header and other successful regions.

### `frontend/components/semantic-catalog/CatalogToolbar.tsx` (component, form/filter transform)

**Analog:** `frontend/app/catalog/page.tsx:83-111`:

```tsx
<section className="panel flex flex-wrap items-center gap-2 p-4">
  <select className="control max-w-56" ... />
  <input className="control min-w-64 flex-1" ... />
  <button className="button-primary" onClick={search}>
    <Search size={16} /> 搜索目录
  </button>
</section>
```

Use a real `<form>` and labeled controls. Keep local draft search separate from committed URL query; immediate filters write URL and reset page to 1. Advanced filters and chips must preserve URL defaults/invalid-value canonicalization.

### `frontend/components/semantic-catalog/GroupedSemanticDirectory.tsx` (component, list transform)

**Analog:** `frontend/app/catalog/page.tsx:121-150`.

Use button/link rows with stable minimum heights, dense metadata, and domain grouping. Group blank/null domains under `未分类` and sort that group last. Result rows link to `/semantics/{id}` with safe encoded return state; do not render rejected/deprecated rows in the trusted mode.

### `frontend/components/semantic-catalog/SemanticComparisonTable.tsx` (component, table transform)

**Analog:** `frontend/components/LineageGraph.tsx:27-69`:

```tsx
<div className="overflow-x-auto">
  <table className="w-full text-left text-sm">
    <thead className="border-b border-line bg-slate-50/80 text-xs ...">
      ...
    </thead>
    <tbody>...</tbody>
  </table>
</div>
```

Use real table semantics, deliberate horizontal scrolling, stable 56px rows, accessible full values for ellipsized cells, and all required columns (name, code, type, domain, effective version, lifecycle/review, owner, confirmed assets, update time).

### `frontend/components/semantic-catalog/SemanticStatus.tsx` (component/utility, transform)

**Analog:** `frontend/app/review-tasks/page.tsx:19-24`:

```tsx
function statusBadge(status: string) {
  if (["approved", "completed", "success"].includes(status)) return "badge-success";
  if (["failed", "rejected", "error"].includes(status)) return "badge-danger";
  if (["pending", "running", "processing"].includes(status)) return "badge-warning";
  return "badge-neutral";
}
```

Copy the centralized mapping style, but define semantic lifecycle and review workflow separately. `confirmed`, `draft`, `ai_suggested`, `rejected`, `deprecated` are lifecycle labels; Pending Review is a separate restrained process indicator. Do not infer a winner or mutate status in the UI.

### `frontend/components/semantic-catalog/SemanticDetailHeader.tsx` (component, read projection + URL state)

**Analog:** `frontend/components/WorkspaceHeader.tsx:1-13`:

```tsx
export function WorkspaceHeader({ title, meta, actions }) {
  return (
    <div className="border-b border-line bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-5 lg:px-6">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
          {meta ? <p className="mt-1 text-sm text-slate-500">{meta}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}
```

Extend this hierarchy with semantic name/code/type, effective version/date control, definition, domain/owner, historical `role="status"` banner, and persistent conflict `role="alert"`. Current-only labels belong to affected regions, not the entire page.

### `frontend/components/semantic-catalog/SemanticTabs.tsx` (component, URL-backed navigation)

**Analog:** none. No existing route uses a complete WAI-ARIA URL-backed tab pattern (`rg` found no `role="tab"`/`aria-selected` implementation).

**Required new pattern:**

- Use `role="tablist"`, `role="tab"`, `aria-selected`, `aria-controls`, and `role="tabpanel"`.
- Read/write tab from URL; preserve project/concept/as_of and validate enum values.
- Implement ArrowLeft/ArrowRight/Home/End keyboard movement, visible focus, and horizontal scroll on mobile.
- Lazy tab panel receives focus only on explicit navigation; background loading does not steal focus.

### `frontend/components/semantic-catalog/AsyncRegion.tsx` (component/state, local request-response)

**Analog:** `frontend/components/LineageGraph.tsx:7-15` only covers the null empty state:

```tsx
if (!graph) {
  return <div className="empty-state"><GitBranch ... /><p>选择项目或对象后查看血缘。</p></div>;
}
```

The full `idle | loading | success-empty | success-populated | forbidden | error` state machine has no direct analog. Preserve stable skeleton dimensions, `aria-busy`, object-specific retry text, and never map 403/500 to `empty-state`. Keep each region independent.

### `frontend/components/semantic-catalog/TrustSourceRegion.tsx` (component, projection transform)

**Analog:** `frontend/app/review-tasks/page.tsx:42-72` status/metadata row layout. Use labeled definition-list sections rather than a badge wall: lifecycle, review workflow, authority, source/provenance, confirmation actor/time, effective interval, and conflict/reason. Link only to real `/tasks/{id}` or `/review-tasks` destinations for authorized users.

### `frontend/components/semantic-catalog/BindingList.tsx` (component, permission-safe read transform)

**Analog:** `frontend/components/LineageGraph.tsx:27-69` edge table. Keep confirmed and candidate bindings in separate sections and use the restricted-reference union from the backend DTO. A restricted item may render only translated entity type plus `受限`; no hidden identifier/name/href/title may enter React state, DOM, accessibility tree, or cache.

### `frontend/components/semantic-catalog/BindingChain.tsx` (component, bounded visualization)

**Analog:** `frontend/components/LineageGraph.tsx:17-25,27-69`:

```tsx
const nodes = new Map(graph.nodes.map((item) => [item.id, item]));
...
{graph.nodes.length} 节点 / {graph.edges.length} 边{graph.truncated ? " / 已截断" : ""}
```

Use a capped CSS chain `Concept -> Target -> Mart -> Source`, report omitted counts, and provide the complete text/list equivalent in the same region. Candidates and audit-only bindings cannot feed the trusted chain. No graph library or free-drag canvas.

### `frontend/components/semantic-catalog/RelationList.tsx` (component, bounded graph/read transform)

**Analog:** `frontend/components/LineageGraph.tsx` plus semantic graph API (`backend/app/api/semantic.py:448-471`). Render directional relation type, target/source identity, lifecycle, and candidate/audit partitions. Keep concept-to-concept topology here; do not mix it into the asset chain.

### `frontend/components/semantic-catalog/VersionTimeline.tsx` (component, chronological read/disclosure)

**Analog:** `frontend/app/catalog/page.tsx:49-51,204-205` lazy column loading and pagination, plus `backend/app/api/semantic.py:148-166` chronological `version_no` list. There is no existing inline disclosure timeline. Implement oldest-to-newest ordering with tie-breaker `version_no`, then id; write selected `version` to URL; expand inline with canonical definition, interval, source/provenance, status, confidence, and confirmation metadata. Mark selected-date-effective versus current-effective versions. Audit statuses stay non-current.

### `frontend/lib/semantic-catalog-view-model.mjs` (utility, transform/URL state)

**Analog:** `frontend/lib/workspace-view-model.mjs`.

**Pure status/partition style** (`frontend/lib/workspace-view-model.mjs:13-54`):

```javascript
export function isQuestionOpen(question) {
  return !["accepted", "rejected", "closed"].includes(
    String(question?.question_status || "").toLowerCase()
  );
}

export function isMappingLocked(status) {
  return ["approved", "confirmed", "in_review"].includes(
    String(status || "").toLowerCase()
  );
}
```

Copy the pure-function/testable approach. New functions should parse/canonicalize/serialize catalog and detail query state, group null domains, partition trusted/candidate/audit rows, compute confirmed-only counts, resolve formal definition only from effective confirmed version, mark current-only regions, validate safe `returnTo`, build allowed destination hrefs, and redact restricted references before render models.

### `frontend/lib/semantic-catalog-view-model.d.mts` (type declaration, transform contract)

**Analog:** `frontend/lib/workspace-view-model.d.mts`, which declares each pure function and its input/output types. Declare exact query-state, status partition, destination, restricted-reference, async-state, and timeline model types; keep runtime logic in `.mjs` so Node tests do not require React.

### `frontend/lib/api.ts` (shared client, authenticated request-response)

**Analog:** current client (`frontend/lib/api.ts:39-65`):

```ts
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    const response = await fetchWithTimeout(`${API_BASE}${path}`, init);
    return readApiResponse<T>(response, path, browserAuthEnvironment());
  } catch (error) {
    throw normalizeRequestError(error);
  }
}

async function fetchWithTimeout(url: string, init?: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const externalSignal = init?.signal;
  ...
  return await fetch(url, { ...init, signal: controller.signal });
}

export async function apiGet<T>(path: string): Promise<T> {
  return request<T>(path, { cache: "no-store", headers: authHeaders() });
}
```

Preserve `cache: "no-store"`, auth headers, timeout, and external AbortSignal forwarding. Extend the public `apiGet`/request signature narrowly if routes need caller `signal`; do not create a second fetch client or cache layer.

### `frontend/lib/http-response.mjs` and `.d.mts` (utility/types, error transform)

**Analog:** current implementation (`frontend/lib/http-response.mjs:69-98`):

```javascript
export function normalizeRequestError(error) {
  if (error instanceof Error && error.name === "AbortError") {
    return new Error("请求超时，请稍后重试");
  }
  if (error instanceof TypeError) {
    return new Error("无法连接服务器，请检查服务是否已启动");
  }
  if (error instanceof Error) return new Error(safeMessage(error.message));
  return new Error("请求失败");
}

export async function throwApiError(response, path, environment) {
  if (response.status === 401 && path !== "/auth/login" && environment) {
    environment.sessionStorage.removeItem(ACCESS_TOKEN_KEY);
    environment.sessionStorage.removeItem(REFRESH_TOKEN_KEY);
    environment.location.replace("/login");
    return new Promise(() => undefined);
  }
  throw new Error(formatApiErrorText(await response.text(), response.status));
}
```

Preserve the exact 401 clearing/redirect/pending behavior. Add a backward-compatible `ApiError` carrying `status` for non-401 failures, preserve it in `normalizeRequestError`, and expose it in `.d.mts`; components must use typed status, never localized message matching, to distinguish 403 from 500.

### `frontend/lib/types.ts` (shared DTO types, transform)

**Analog:** existing catalog DTO aliases (`frontend/lib/types.ts:170-176`):

```ts
export type CatalogTable = { id:number; datasource_id:number; schema_name:string; ... };
export type CatalogColumn = { id:number; datasource_id:number; ... };
```

Add semantic catalog DTOs as explicit types, including optional effective version, facets/page metadata, review summaries, current-only flags, lawful destination references, and a discriminated restricted reference. Keep backend literal values aligned with `backend/app/schemas/semantic.py`; do not add copied facts or client-only authority fields.

### `frontend/components/AppShell.tsx` (shell/navigation)

**Analog/current pattern:** `frontend/components/AppShell.tsx:48-72,104-112`:

```tsx
const NAV_GROUPS = [
  ...,
  {
    label: "数据资产",
    items: [
      { href: "/datasources", label: "数据源", icon: Database },
      { href: "/catalog", label: "数据目录", icon: LibraryBig },
      ...
    ]
  }
];

function isActive(pathname: string, item: NavItem) {
  const prefix = item.match || item.href;
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}
```

Make one narrow insertion under `数据资产`, import the closest Lucide catalog/ontology icon (`BookOpenCheck` if available), and preserve all current dirty `AppShell` restructuring. Do not replace the file or add a second project selector.

### `frontend/tests/semantic-catalog-view-model.test.mjs` (test, pure transform)

**Analog:** `frontend/tests/workspace-view-model.test.mjs:1-47`:

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { isQuestionOpen, buildLineageLabels } from "../lib/workspace-view-model.mjs";

test("仅未闭环问题计入待确认", () => {
  assert.equal(isQuestionOpen({ question_status: "open" }), true);
  assert.equal(isQuestionOpen({ question_status: "accepted" }), false);
});
```

Use table-driven Node tests for URL defaults/invalid values, `未分类` ordering, lifecycle/workflow separation, audit isolation, confirmed counts, effective-version selection, current-only flags, safe destinations/returnTo, restricted redaction, and long/invalid values.

### `frontend/tests/http-response.test.mjs` (test, error behavior)

**Analog:** current tests (`frontend/tests/http-response.test.mjs:22-45,117-125`) preserve 401 behavior and transport messages:

```javascript
test("protected API 401 clears the session and redirects ...", async () => { ... });
test("request transport failures become understandable Chinese messages", () => { ... });
```

Keep these tests unchanged in intent. Add assertions that 403 and 500 produce status-bearing `ApiError`, normalization preserves the type/status, and 401 still removes both tokens and redirects without a rejection race.

### `backend/tests/test_semantic_catalog_api.py` (test, API/security request-response)

**Analog:** `backend/tests/test_semantic_layer.py` test harness and isolation cases (`:62-105,368-403,406-434,651-684`).

**Harness and project isolation pattern:**

```python
with _semantic_client() as (client, sessions):
    project_a, project_b = _projects(sessions)
    created = _post(client, f"/api/projects/{project_a}/semantic-concepts", {...})
    hidden = client.get(f"/api/projects/{project_b}/semantic-concepts/{created['id']}")
    assert hidden.status_code == 404
```

Reuse `_semantic_client`, `_projects`, `_required_binding_entities`, and `TestClient`/SQLite fixtures. Add focused tests for server-side search/filter/total/facets, inclusive `as_of`, ambiguity, status partitions/audit permission, N+1 avoidance, restricted reference JSON leakage, lazy region 403, candidate counts, and stable pagination. Keep `test_semantic_layer.py` as regression coverage rather than moving existing lifecycle tests.

## Shared Patterns

### Project and Institution Isolation

**Sources:** `frontend/components/ProjectContext.tsx:18-57`; `backend/app/api/semantic.py:84,209,310`; `backend/app/services/semantic/version_service.py:370-385`.

```tsx
const { projectId } = useProjectWorkspace();
if (!projectId) return;
```

```python
PermissionService(db, principal).require_project_permission(project_id, "project.view")
...
SemanticConcept.project_id == SemanticConceptVersion.project_id
```

Every request key and server query includes project scope. Abort/ignore old project responses; never reuse cached concept identity/counts across projects or institutions. Invisible cross-project resources remain safe 404; visible project permission failures remain typed 403.

### Canonical Temporal Truth

**Source:** `backend/app/services/semantic/version_service.py:357-402`.

Use `resolve_effective_versions` with inclusive `effective_from <= as_of <= effective_to`, trusted concept/version predicates, and project constraint. Effective version is the sole formal definition source; current/legacy Concept fields and AI candidates are never fallback formal truth.

### Trusted, Candidate, and Audit Partitions

**Sources:** `backend/app/services/semantic/status_policy.py:14-21`; `backend/tests/test_semantic_layer.py:368-403`.

- Trusted formal facts/counts/paths: `confirmed` only.
- Discoverable non-formal candidates: `confirmed`, `draft`, `ai_suggested`, clearly labeled.
- Audit-only: `rejected`, `deprecated`, explicit audit/history mode and permission only.

Keep lifecycle status separate from review workflow status. Resolved questions are not current open-question summaries; current tuple is `open`, `assigned`, `answered` as documented in research.

### Authenticated API, Timeout, and Error States

**Sources:** `frontend/lib/api.ts:39-65`; `frontend/lib/http-response.mjs:69-98`.

All semantic reads use shared `apiGet`, `no-store`, auth headers, external AbortSignal, and existing 401 redirect. Add status-bearing errors without exposing unsafe diagnostics. Model 403 as unauthorized and 500/network/timeout as retryable operational error; successful zero is the only source of empty state.

### URL and Request-Key State

**Sources:** `frontend/components/ProjectContext.tsx:28-37`; `frontend/app/catalog/page.tsx:41-47`.

Pure view-model functions parse, validate, canonicalize, and serialize `q`, filters, `as_of`, `view`, `page`, `tab`, `version`, and safe return paths. Search commits only on Enter/action; enum filters commit immediately. Request keys include project, concept, date, tab, filters, page, and view. Abort on dependency change and compare captured key before state commit.

### Operational Layout and Accessibility

**Sources:** `frontend/app/catalog/page.tsx:79-210`; `frontend/components/LineageGraph.tsx:20-69`; `frontend/app/review-tasks/page.tsx:42-72`.

Reuse `WorkspaceHeader`, `panel`, `control`, `button-*`, `badge-*`, `grid-row`, `empty-state`, border-line separators, stable row dimensions, and deliberate table overflow. Use one `h1`, ordered region headings, real form/table/tab semantics, `aria-busy` skeleton regions, `role=alert` for errors/conflicts, `role=status` for pending/historical banners, Lucide icons, visible focus, and text/list equivalents for the chain.

## No Analog Found

| File/Responsibility | Role | Data Flow | Gap and Planner Guidance |
|---|---|---|---|
| `frontend/components/semantic-catalog/SemanticTabs.tsx` | component | URL-backed navigation | No existing ARIA tab implementation. Implement WAI-ARIA tabs and URL synchronization explicitly; add keyboard tests. |
| `frontend/components/semantic-catalog/AsyncRegion.tsx` | component/state | lazy request-response | Existing components distinguish null/empty only. Build explicit local loading/success-empty/forbidden/error state and retry action. |
| `frontend/components/semantic-catalog/VersionTimeline.tsx` | component | chronological disclosure | Existing version API is a flat list and no inline disclosure exists. Use stable date/version/id sort and URL `version`. |
| `backend/app/schemas/semantic_catalog.py` restricted union | schema/DTO | permission-safe transform | No existing type-only restricted asset DTO. Add separate readable/restricted variants; never redact after serialization. |
| `backend/app/services/semantic/catalog_query_service.py` aggregate read model | service | batch query/aggregate | Existing catalog pagination is a useful count/offset analog but lacks semantic permission/status/temporal policy. Build one filtered population and set-based aggregates. |

## Metadata

**Analog search scope:** `backend/app/api`, `backend/app/schemas`, `backend/app/services/semantic`, `backend/app/services/auth`, `frontend/app`, `frontend/components`, `frontend/lib`, `frontend/tests`, `backend/tests`.  
**Files scanned:** 31 focused analog/config/test files plus all phase upstream documents.  
**Important worktree constraint:** `frontend/components/AppShell.tsx` and other frontend files are already dirty/untracked. The planner/executor must make narrow edits, inspect the current file immediately before patching, and never revert user-owned work.

**Pattern extraction date:** 2026-08-25
