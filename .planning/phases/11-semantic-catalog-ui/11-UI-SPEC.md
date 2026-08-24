---
phase: 11
slug: semantic-catalog-ui
status: draft
shadcn_initialized: false
preset: none
created: 2026-08-25
---

# Phase 11 - UI Design Contract

> Visual and interaction contract for the project-scoped Semantic Catalog. Generated from SUI-01/SUI-02, all D-01 through D-30 decisions in `11-CONTEXT.md`, and the live frontend/backend contracts.

---

## Product Boundary

Phase 11 adds two read-oriented routes inside the existing Next.js shell:

- `/semantics`: an enterprise catalog grouped by Business Domain, with an optional comparison table.
- `/semantics/[id]`: a governed semantic detail with Overview, Bindings, Relations, Evidence, Lineage, Governance, and Versions tabs.

The experience answers, in order: what the concept means; whether it is effective and trusted; why it is trusted; which regulatory and data assets it binds to; how it relates to other concepts; and how it changed over time. It is not a CRUD administration table. It does not confirm, reject, deprecate, edit, or create semantic facts inline.

Locked boundaries:

- The real API, `ProjectContext`, `PermissionService`, and canonical `SemanticConceptVersion` effective-date policy are authoritative.
- Legacy Concept projection fields are never presented as an independent definition source.
- Rejected/deprecated facts are audit-only and hidden from trusted counts and paths.
- Current-only binding, evidence, lineage, or governance facts are labeled as current when the user is viewing an historical date.
- Phase 12 Requirement Workspace V2, Phase 13 dashboard metrics, Phase 14 `DataQualityExpectation`, Phase 15 Semantic Impact, SQL generation, and a free-drag graph are absent.

---

## Design System

| Property | Value |
|----------|-------|
| Tool | Existing manual Tailwind Design Tokens; no shadcn |
| Preset | Not applicable |
| Component library | Existing local React components and native controls; no Radix/Base UI dependency |
| Icon library | `lucide-react` only |
| Font | Existing `font-sans`: system UI, Segoe UI, PingFang SC, HarmonyOS Sans SC, Microsoft YaHei fallbacks |
| Shell | Reuse `AppShell`, `ProjectContext`, `ProjectSelector`, and `WorkspaceHeader` |
| Data access | Reuse `apiGet` and normalized auth/error behavior in `frontend/lib/api.ts` and `http-response.mjs` |

Add `语义目录` to the `数据资产` navigation group in `AppShell`, using `BookOpenCheck` or the closest Lucide catalog/ontology icon. The active-route contract remains exact route or prefix match. Do not rebuild the shell or add a second project selector.

Registry policy: no component registry and no third-party block is permitted for this phase. The existing manual system is already established, so the shadcn initialization gate is not applicable.

### Surface Composition

- Keep the operational density and restrained treatment of `frontend/app/catalog/page.tsx`, `frontend/app/fields/page.tsx`, and `frontend/app/review-tasks/page.tsx`.
- Use one framed toolbar where controls need a shared boundary. Catalog groups and detail sections are full-width bands or unframed sections separated by `border-line`, not cards inside cards.
- A `.panel` is allowed for a bounded tool such as the relationship visualization or one asynchronous tab region. Never nest `.panel` inside `.panel`.
- Use 8px radius (`rounded-lg`) for controls and bounded tools. Existing 12px `.panel` may remain where reused; do not introduce larger decorative radii.
- No hero, illustration, decorative gradient, metric cards, marketing copy, or chat-style layout.

---

## Spacing Scale

Declared values, all multiples of 4:

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | Status icon gap, compact metadata gap |
| sm | 8px | Inline actions, badge/content gap, row sub-elements |
| md | 16px | Default control and row spacing, mobile page padding |
| lg | 24px | Desktop page padding and section spacing |
| xl | 32px | Major detail-region separation |
| 2xl | 48px | Empty-state vertical breathing room |
| 3xl | 64px | Reserved maximum page-level break; not used between every section |

Exceptions:

- Semantic-route icon-only buttons and mobile tap targets are at least 44px by 44px even though existing generic buttons are 36px high.
- Catalog desktop rows have a stable minimum height of 68px; comparison-table rows have a stable minimum height of 56px.
- Skeletons reserve the same minimum heights as the content they replace so loading cannot shift the layout.

---

## Typography

Only these four sizes and two weights are used by new Phase 11 UI. Existing shell typography remains unchanged.

| Role | Size | Weight | Line Height |
|------|------|--------|-------------|
| Label / metadata | 12px | 400 | 1.4 |
| Body / controls | 14px | 400 | 1.5 |
| Section heading / emphasized row text | 16px | 600 | 1.3 |
| Page title / concept name | 20px | 600 | 1.2 |

- Weight vocabulary is exactly regular 400 and semibold 600. Do not add 500 or 700 in new semantic components.
- Concept Codes, entity codes, versions, and dates use `font-mono` at 12px or 14px with tabular numerals where applicable.
- Letter spacing is `0`; do not use negative tracking or viewport-scaled font sizes.
- Definitions preserve authored paragraph breaks with `whitespace-pre-wrap`, 14px/1.5 body text, and a readable maximum line length of 80 characters (`max-w-[80ch]`).
- Long names and source titles wrap. Codes may use `break-all` on narrow screens. Ellipsis is allowed only in catalog comparison cells when the full value is also available through an accessible title or expansion, never for the primary detail definition.

---

## Color

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `#f4f7fa` (`mist`) | Page background, empty/skeleton fill, current-state neutral bands |
| Secondary (30%) | `#ffffff` with `#dfe6ee` (`line`) | Header, toolbar, rows, tab surface, bounded tools, separators |
| Accent (10%) | `#176b5f` (`pine`) | Active navigation/tab/view mode, primary search action, focus ring, trusted Confirmed state, primary semantic links |
| Warning | `#a66b00` (`gold`) | Pending Review, candidate binding, incomplete evidence, historical/current-only notice |
| Destructive / conflict | `#b8513f` (`coral`) | Load errors, high-authority conflict, Rejected audit state; no destructive action exists in Phase 11 |
| Informational candidate | Existing `sky` scale | AI Suggested lifecycle marker only |
| Neutral | Existing `slate` scale | Draft, Deprecated, metadata, disabled/unavailable controls |

Accent is reserved for active navigation/tab/view selection, the explicit `搜索语义` action, keyboard focus, trusted `Confirmed`, and navigable semantic links. It is not applied to every button, every icon, whole row backgrounds, or large page areas.

### Status Hierarchy

Lifecycle and review workflow are separate visible fields; never collapse them into one badge.

| State | Treatment | Required text behavior |
|-------|-----------|------------------------|
| Confirmed | `badge-success`; pine icon/text on pale pine, never solid green row | `已确认 / Confirmed` |
| Pending Review | Small `badge-warning` or inline clock indicator beside a separate `评审流程` label | `待评审` and current step/assignee when lawful |
| AI Suggested | `badge-info`; candidate region has a left border, not a full blue card | `AI 建议` plus non-formal explanation |
| Draft | `badge-neutral` | `草稿` |
| Rejected | `badge-danger`, only in explicit audit/history context | `已拒绝 · 非当前事实` |
| Deprecated | `badge-neutral` with muted text, only in explicit audit/history context | `已废弃 · 非当前事实` |
| High-authority conflict | Persistent pale coral banner with `TriangleAlert`; title, summary, sources, review link | Never imply a winner |
| Historical mode | Pale gold full-width banner under summary | Date and one-action `返回当前版本` |

Status meaning must be conveyed by text and icon as well as color. Authority is rendered as labeled text in `可信度与来源`, not repeated as a badge on every fact.

---

## Copywriting Contract

| Element | Copy |
|---------|------|
| Catalog page title | `语义目录` |
| Search placeholder | `搜索名称、Code、别名或定义` |
| Primary CTA | `搜索语义` |
| Group fallback | `未分类` |
| Unfiltered empty heading | `当前项目还没有可浏览的语义概念` |
| Unfiltered empty body | `语义概念经治理后会显示在这里。` |
| Filtered empty heading | `没有符合条件的语义概念` |
| Filtered empty body | `调整搜索词或筛选条件后重试。` |
| Catalog error | `语义目录加载失败。请重试；当前搜索和筛选条件已保留。` |
| Unauthorized | `你没有权限查看当前项目的语义目录。请切换项目或联系项目管理员。` |
| No binding | `当前语义尚未绑定数据资产。` |
| Candidate binding | `发现候选关联，但尚未经过人工确认。` |
| AI-only formal area | `暂无正式版本` |
| AI candidate region | `AI 建议，尚未成为正式监管语义` |
| No relation | `当前语义没有已确认的概念关系。` |
| No evidence | `当前语义还没有可查看的证据或知识来源。` |
| No lineage | `当前语义尚无可查看的已验证血缘路径。` |
| Pending review | `该语义正在人工评审中，生命周期状态尚未改变。` |
| Conflict title | `存在无法自动裁决的高权威冲突` |
| Conflict body | `多个高权威事实相互冲突。系统不会自动选择其中一项，请进入人工评审核实来源。` |
| Historical banner | `Viewing as of {YYYY-MM-DD} · 当前正在查看历史语义版本` |
| Current-only historical label | `当前状态，不代表该历史日期` |
| Restricted binding | `{资产类型} · 受限` |
| Generic tab error | `{区域名称}加载失败。其他区域仍可查看。` |
| Retry action | `重试` |
| Return current | `返回当前版本` |
| Review link | `前往评审任务` |
| Destructive confirmation | Not applicable: Phase 11 exposes no destructive command or inline lifecycle transition |

Copy rules:

- Do not use `暂无数据` for permission denial, request failure, no binding, no confirmed version, candidate-only data, or conflict.
- Counts use `0 个 / 1 个 / {n} 个`; do not display a dash where zero is known.
- Missing optional metadata uses `未提供`; unknown because it was not loaded or not authorized uses the corresponding error/restricted state instead.
- Raw backend enum values and English exception text must be mapped to user-facing Chinese labels, while stable Codes remain unchanged.

---

## Route And URL Contract

### Catalog Query Parameters

The catalog URL is the durable source for browse state. Defaults are omitted from the URL.

| Parameter | Values | Behavior |
|-----------|--------|----------|
| `q` | Trimmed text | Committed only on Enter or `搜索语义`; covers name, Code, aliases, and canonical definition server-side |
| `type` | One initial concept type or repeated/comma-delimited values | Immediate filter; reset `page=1` |
| `domain` | Server-provided domain value | Immediate filter; `__uncategorized__` maps to `未分类` |
| `status` | `confirmed`, `draft`, `ai_suggested`, `rejected`, `deprecated` | Omitted means current catalog population: Confirmed + Draft + AI Suggested; rejected/deprecated require `audit=1` |
| `owner` | Server-provided owner value | Immediate filter |
| `as_of` | ISO `YYYY-MM-DD` | Select canonical effective version for the catalog date |
| `has_binding` | `1` or `0` | Advanced immediate filter, confirmed binding semantics in trusted view |
| `has_relation` | `1` or `0` | Advanced immediate filter, confirmed relation semantics in trusted view |
| `pending_review` | `1` or `0` | Advanced immediate filter, separate from lifecycle status |
| `audit` | `1` only | Explicitly enables rejected/deprecated audit filtering |
| `view` | `directory` or `table` | Defaults to `directory` |
| `page` | Positive integer | Server pagination; reset on any search/filter change |
| `page_size` | `25`, `50`, or `100` | Defaults to `50` |

The current catalog population intentionally lets users discover Confirmed, Draft, and AI Suggested identities while keeping their lifecycle labels explicit. Formal definitions, effective-version fields, trusted counts, and governed paths remain Confirmed-only; Draft/AI Suggested content never fills those slots. The text input owns a local draft value; typing does not request or update `q`. Enter and the Search button commit the draft, reset page, and push one browser-history entry. Filter, view, date, and pagination changes use `router.replace(..., {scroll:false})` so repeated adjustments do not flood history. Refresh and shared URLs must hydrate controls before the first request.

`ProjectContext` remains the only project selection seam. When the project changes, cancel stale requests, reset semantic filters to trusted defaults, and never render the prior project's results while the new project loads. If the existing `projectId` query convention is present, preserve it; do not create a competing scope store.

The UI must not fetch a capped list and perform pretend-global client filtering. Search, facets, counts, pagination, `as_of`, and audit isolation are server-evaluated. An additive read endpoint may be introduced, for example `GET /projects/{project_id}/semantic-catalog`, returning `items`, `total`, `page`, `page_size`, and permitted filter facets. It remains a projection over canonical semantic, review, binding, and version sources; it persists nothing and returns no protected asset metadata.

### Detail Query Parameters

| Parameter | Values | Behavior |
|-----------|--------|----------|
| `tab` | `overview`, `bindings`, `relations`, `evidence`, `lineage`, `governance`, `versions` | Defaults to `overview`; invalid values normalize to Overview |
| `as_of` | ISO `YYYY-MM-DD` | Resolves canonical temporal content for the inclusive business date |
| `version` | Positive version id/no, Versions tab only | Expands one timeline item inline; never creates a new route |
| `returnTo` | Encoded relative `/semantics?...` only | Restores the originating catalog state; reject absolute/external values |

Tab, version expansion, and valid date changes update the URL without full-page navigation or scroll reset. Invalid dates show an inline validation message and do not send a request. `返回当前版本` removes only `as_of` and `version`, preserving `tab` and `returnTo`.

All asset destinations append `from=semantics&semanticConceptId={id}`. The destination resolver uses existing routes and real IDs:

- Target Field: `/fields/{id}/scenarios`; Target Table: `/fields?targetTableId={id}`.
- Mart Table/Field and double-layer mapping: `/mart` with the narrowest supported table/field/mapping filter.
- Source Table/Field: `/catalog` with the narrowest supported source reference filter.
- Scenario and scenario mapping/lineage: the canonical `/fields/{targetFieldId}/scenarios?scenarioId={id}` when that lawful context is available.
- Knowledge Unit: `/knowledge/documents/{documentId}?unitId={id}` when the permitted projection exposes its owning document.
- Verified lineage: the existing `/lineage` or `/lineage/fields/{fieldId}` route with the specific lawful reference.
- Active review task: `/tasks/{taskId}`; otherwise `/review-tasks` with the semantic return parameters.

If a destination cannot lawfully be resolved, render non-clickable metadata with `尚无可导航详情`; never invent a route. A restricted target is always unlinked and contains only translated asset type plus `受限`.

---

## Catalog Layout Contract

### Page Frame

- Use `WorkspaceHeader` with title `语义目录` and meta `共 {total} 个语义概念 · 截至 {date/current}` only after the first successful response. During loading use a stable-width skeleton; do not claim `0`.
- Main content uses `mx-auto max-w-[1600px] p-4 lg:p-6` and 20-24px vertical gaps.
- The toolbar is one `.panel` with a first row for search, primary filters, and view mode; a second collapsible `更多筛选` region contains date and boolean filters. Active filters appear as removable text chips below controls, never as colored status badges.
- Search has a visible label for screen readers, the Lucide `Search` icon, Enter behavior, and a text button label. The view switch is a two-option segmented control with `ListTree` and `TableProperties` icons, `目录` and `对比表` labels, `aria-pressed`, and a fixed 40px height.
- A right-aligned `清除筛选` text action resets all semantic parameters except project and view mode. It is disabled when nothing can be cleared.

### Grouped Directory (Default)

- Group by effective Business Domain returned by the server. Sort named domains using stable locale order; place `未分类` last. Preserve server item ordering within each group.
- Each group is an unframed section with a 16px semibold heading, count, and one bordered row collection. It is not a collection of individual cards.
- Desktop row columns: `minmax(260px,1.6fr) 140px 150px 120px minmax(140px,1fr) 96px 140px`. They contain name/Code, type, effective version, lifecycle state, Owner, confirmed related-asset count, and updated time. Domain is represented by the group heading, not repeated in every row.
- The name is the primary link. Definition is a two-line secondary preview only when space allows; it is not substituted for the canonical detail definition.
- Related-asset count includes only readable-or-restricted confirmed bindings in the trusted projection and excludes candidates, rejected, and deprecated bindings. It is a count, not a coverage metric.
- Pending Review is shown as a separate clock/text indicator beside lifecycle status, never replacing it.
- The entire row is not a button. Only the semantic name and an icon-only arrow with tooltip `查看语义详情` are links, preventing nested interactive targets.

### Comparison Table

- Medium-density table with sticky header inside one horizontal scroll region; minimum table width 1120px.
- Columns are exactly: Concept, Code, Type, Business Domain, Effective Version, Lifecycle, Review, Owner, Confirmed Assets, Updated.
- Sort state, if supported by the read endpoint, is server-side and represented by `sort`/`order` query parameters; otherwise render fixed server order without decorative nonfunctional sort icons.
- On screens below 768px, comparison mode remains horizontally scrollable and the Concept column is sticky with an opaque white background. It must not squeeze ten columns into unreadable text.

### Pagination And Result Integrity

- Show `第 {start}-{end} 条，共 {total} 条` and previous/next controls; numbered pages are optional, but first/last are required when total pages exceed 5.
- Keep pagination dimensions stable at zero/one/many pages. Hide or disable non-applicable navigation without collapsing the footer.
- If the API reports that results are truncated, show `仅显示前 {n} 条，请继续筛选` and do not label the number as the total.

---

## Detail Layout Contract

### Header And First Load

- First request loads the concept stable identity, effective canonical version for `as_of` or today, lifecycle/review summary, and conflict summary. This is the only blocking detail request.
- While it loads, render a summary skeleton with fixed title, metadata, definition, and tab-strip heights. Do not render `暂无正式版本` until the request succeeds.
- The header is a full-width white band below `WorkspaceHeader`, not a hero or card. It contains a `返回语义目录` link, 20px concept name, monospaced Code, type, lifecycle badge, separate review indicator, definition/empty formal state, domain, owner, and effective version/interval.
- The `as_of` control sits beside the effective version summary: a labeled native date input, `查看` action, and current/history state. It has a maximum date only if the backend contract supplies one; do not impose an arbitrary limit.
- A real conflict banner appears immediately below the identity row and above the definition. It is persistent, non-dismissible, includes short conflicting source summaries, and links to Governance or a real review task. Never show an AI recommendation.
- Historical mode adds the gold banner directly below the header. It remains visible on every tab.

### Tabs

- Tab order is fixed: Overview, Bindings, Relations, Evidence, Lineage, Governance, Versions.
- Use a single horizontal tab list below the summary. Active tab uses pine text and a 2px bottom border; inactive tabs use slate text. No pill-filled tab bar.
- Each tab is a link/button with `role=tab`, `aria-selected`, and `aria-controls`. Support Left/Right arrows, Home, End, and Enter/Space. On mobile the tab list scrolls horizontally and active tab is scrolled into view.
- Overview loads with the header. Every other tab fetches on first activation, caches by `{projectId, conceptId, as_of-or-current}`, and owns its loading, empty, error, and retry state. A tab error never clears the header or another tab's cached content.
- Abort prior requests on project, concept, or `as_of` change. Ignore late responses whose scope key no longer matches.

### Overview

Use a two-column layout at `xl`, `minmax(0,1.7fr) minmax(280px,1fr)`, and one column below `xl`.

- Primary column: `定义`, aliases, domain/owner metadata, major confirmed Target/Mart/Source bindings, and current open questions.
- Secondary column: one bounded `可信度与来源` region listing lifecycle, separate review workflow, authority, source title/location, provenance references, confirmation actor/time, and effective interval. This is a labeled definition list, not a badge wall.
- Formal Definition always comes from the resolved confirmed version. If none exists, show `暂无正式版本`; do not fall back to legacy projection or AI content.
- AI Suggested or Draft versions appear below in a visually separate `候选内容` region with the exact non-formal copy. Candidate text cannot occupy the formal definition slot.
- Open-question summary includes unresolved questions only. Each shows type, concise question, source, and lawful route to review. Resolved questions appear only in Governance/audit history.

### Bindings

- Top summary shows confirmed binding count and candidate count separately. Candidate count never contributes to trusted paths.
- `Confirmed Bindings` is grouped by translated entity family: Target, Mart, Source, Scenario/Mapping, Knowledge. Each row shows lawful name/Code, entity type, binding type, confidence, source/provenance, and navigation.
- `待治理候选` is a separate section after confirmed bindings with pale gold boundary and the candidate-state copy. Draft and AI Suggested lifecycle labels remain explicit.
- If there are neither confirmed nor candidate bindings, show the no-binding copy. If only candidates exist, show both the no-confirmed statement and candidate section; never collapse it to ordinary empty.
- A lawfully disclosed but unreadable target uses the restricted placeholder contract. No tooltip, DOM attribute, accessible name, analytics payload, or link may contain protected target metadata.
- In historical mode, display `当前状态，不代表该历史日期` at the top unless the endpoint explicitly returns temporal binding validity for the selected date.

### Bounded Binding Visualization

- Show inside Bindings after the structured lists, or as the major-asset summary on Overview. It visualizes only `Concept -> Target -> Mart -> Source` governed asset chains.
- Use four fixed CSS columns with labeled headers and simple connectors; do not add a graph library, physics, dragging, zooming, minimap, or free-form canvas.
- Cap at one concept root plus four nodes per asset layer (13 visible nodes). When more exist, show `另有 {n} 个，查看绑定列表`; never silently omit them.
- Nodes use 8px radius, stable 44px minimum height, translated type icon, wrapped lawful label, and lifecycle/restricted text. Candidate nodes do not appear in the trusted chain.
- Desktop flows left to right. Below 768px it becomes a vertical ordered chain with downward connectors. Keyboard order follows Concept, Target, Mart, Source and matches visual order.
- If no complete chain exists, render the available confirmed nodes and a dashed labeled gap such as `尚无已确认 Mart 绑定`; do not infer missing links.

### Relations

- Keep Concept-to-Concept topology here, separate from the asset chain.
- Primary representation is a directional list grouped as `上游关系` and `下游关系`, with relation type, related concept name/Code, lifecycle, provenance, and detail link.
- A small one-hop relation view may show the root and at most 12 confirmed neighbors using the existing semantic neighbors endpoint with `mode=trusted&max_depth=1&max_nodes=13`. Honor `truncated` with explicit copy and a list fallback.
- Candidate relations, when requested by the read projection, live in a separate `待治理候选` list. Rejected/deprecated relations never appear outside explicit audit history.

### Evidence

- Present two unframed sections: `监管与业务证据` and `知识来源`. Rows show source type, lawful title, location/article/page, concise excerpt, evidence/reference id, authority, and observed/confirmed time when real.
- Provenance is a chain of labeled references, not an unexplained confidence percentage. Retrieval similarity cannot be styled as confirmation.
- Evidence excerpts wrap and are capped to 6 lines with an accessible `展开全文/收起` control when full content is permitted.
- Restricted knowledge follows the same placeholder rule; confidentiality or source content is not exposed.
- Historical mode uses the current-only label unless each reference carries temporal validity matching `as_of`.

### Lineage

- Show only verified/current lineage paths supplied by the authoritative lineage service. Reuse the visual vocabulary of `LineageGraph`, but do not copy or reconstruct `LineageNode/Edge` into semantic storage.
- Start with a compact path summary and link to the canonical `/lineage` or `/lineage/fields/{fieldId}` route. A detailed edge table may follow with Source, Relation, Target, Transformation, and Evidence columns.
- Stale or unresolved lineage is labeled as such and excluded from `已验证路径` counts. Missing lineage uses the dedicated no-lineage copy.
- Historical mode always shows the current-only label unless the lineage API explicitly resolves an historical snapshot.

### Governance

- Render lifecycle state, review-workflow state, authority, source/provenance, confirmation actor/time, review reasons, audit events, and unresolved conflicts as separate labeled sections.
- Authorized users receive only navigation to a real active `/tasks/{id}` or `/review-tasks`; there are no inline Confirm/Reject/Deprecate controls.
- Pending Review shows current step, assignee role/user only when lawful, due date, and link. It does not mutate the lifecycle badge.
- Rejected/deprecated events and resolved questions may appear in the chronological audit list with clear `非当前事实` labels.
- In historical mode, governance fields that are current-only carry the current-only label; the effective version's own confirmation metadata remains historical version data.

### Versions

- Use one vertical timeline ordered from oldest effective date to newest, with stable tie-breaker `version_no` then id.
- Collapsed item shows version number, lifecycle, inclusive effective interval, source type/reference, and confirmation actor/time.
- Selecting an item expands it inline and writes `version` to the URL. Expanded content includes definition, description, aliases, domain, owner, provenance, status, confidence, effective dates, and confirmation metadata.
- The version effective for `as_of` is marked `所选日期生效`; the current effective version is marked `当前生效`. These can differ.
- Draft, AI Suggested, Rejected, and Deprecated versions are visually separated from confirmed history and never treated as effective formal truth.
- No separate version detail route, modal, editor, or lifecycle action is introduced.

---

## Component And State Contract

Recommended ownership boundaries; names are prescriptive enough for planning but may be combined when a component would be trivial:

| Component/module | Responsibility |
|------------------|----------------|
| `app/semantics/page.tsx` | Catalog route, URL hydration, project boundary, request orchestration |
| `app/semantics/[id]/page.tsx` | Detail identity/header, tab URL, `as_of`, scoped cache invalidation |
| `components/semantic-catalog/CatalogToolbar.tsx` | Draft search, primary/advanced filters, active filter chips, view switch |
| `GroupedSemanticDirectory.tsx` | Domain sections and semantic rows |
| `SemanticComparisonTable.tsx` | Accessible table and horizontal overflow |
| `SemanticStatus.tsx` | Lifecycle label plus separate review indicator; no business-policy inference |
| `SemanticDetailHeader.tsx` | Identity, effective version/date control, historical/conflict banners |
| `SemanticTabs.tsx` | URL-backed keyboard tab behavior |
| `AsyncRegion.tsx` | Region-scoped skeleton, empty, error, retry, `aria-busy` |
| `TrustSourceRegion.tsx` | Authority, provenance, source, confirmation, interval definition list |
| `BindingList.tsx` | Confirmed/candidate split, restricted reference handling |
| `BindingChain.tsx` | Bounded CSS chain visualization only |
| `RelationList.tsx` | Directional concept relations and bounded one-hop view |
| `VersionTimeline.tsx` | Chronological inline expansion and URL selection |
| `lib/semantic-catalog-view-model.mjs` plus `.d.mts` | Pure parsing/serialization, state labels, grouping, destination resolution, count semantics |

View-model rules must be unit-testable without React:

- Parse and canonicalize catalog/detail query parameters, removing defaults and invalid enum/date values.
- Group missing/blank domain under `未分类` and place it last.
- Keep lifecycle and workflow state separate.
- Partition confirmed, candidate, and audit-only items; audit-only items can never enter trusted counts or graph inputs.
- Resolve formal definition only from effective confirmed version.
- Mark current-only regions during historical mode.
- Build destination routes only from allowed entity types and lawful required IDs.
- Redact restricted targets before any render model is produced.

### Async State Rules

| State | Catalog | Detail header/Overview | Lazy tab |
|-------|---------|------------------------|----------|
| Idle/no project | Prompt `请先选择项目` without request | Route cannot resolve project; show project prompt | Not requested |
| Loading | Toolbar remains enabled except request-dependent facets; row skeletons and reserved total | Fixed summary/definition/tab skeleton | Region skeleton only; header stays usable |
| Populated | Server total, groups/table, pagination | Canonical effective content plus trust region | Region data and lawful links |
| Empty | Distinguish unfiltered and filtered empty copy | `暂无正式版本` only after successful effective lookup | Region-specific empty copy |
| Partial | Render available lawful fields, use `未提供`, preserve region warnings | Never backfill canonical fields from legacy/AI | Render successful subsections and identify unavailable subsection |
| Error | Error region with retry and retained URL; no empty copy | Page-level error with retry/back-to-catalog; no false semantic facts | Local error/retry only |
| Unauthorized | Dedicated 403 state; no counts/facets/results | Dedicated 403 state; no cached identity from another project | Restricted whole region or lawful placeholders per API contract |

Do not infer 403 from a generic error string. The API/error layer must expose a typed status or safe error code for view-state selection while retaining current 401 redirect behavior.

---

## Responsive Contract

| Viewport | Catalog | Detail |
|----------|---------|--------|
| `>=1280px` | Full shell sidebar; toolbar in one/two rows; seven-column directory rows; table at full width | Summary metadata in two lines; Overview two columns; asset chain horizontal |
| `768-1279px` | Wrapped toolbar; directory reduces to Concept, Type, Version, Lifecycle/Review, Owner/Assets; updated time moves into metadata | Summary actions wrap; all tabs remain; sections single column below `xl`; chain may horizontally scroll until 768px |
| `<768px` | Shell drawer; search full width; primary filters two-column then one-column under 420px; directory rows stack as compact definition lists; table scrolls horizontally | Header stacks; date control full width; tabs horizontal-scroll; chain becomes vertical; action links full width where text would clip |

- No element may overlap the sticky 70px shell header. Detail tabs may be sticky only below it (`top-[70px]`) and must not cover the historical/conflict banner.
- Stable grid tracks/minimum heights prevent badges, loading text, or long values from resizing controls.
- Do not hide governance, candidates, conflict, or current-only labels on mobile. Reflow them.
- At 320px width, the longest Chinese/English label must wrap inside its owner. No horizontal page overflow is allowed except the deliberate table/tab scroll containers.

---

## Accessibility Contract

- Meet WCAG 2.2 AA contrast using the existing token pairs. Color is never the only status signal.
- One `h1` per route. Business Domain groups and detail regions use ordered `h2/h3` headings. Catalog results use a list or table with real semantics.
- Search is a real form. Enter submits once; the Search button has visible text. Filters have programmatic labels and current values.
- Loading regions expose `aria-busy=true`; skeleton decoration is `aria-hidden`. When results finish, announce `{total} 个结果` through a polite live region without moving focus.
- Errors and high-authority conflicts use `role=alert`. Pending-review and historical banners use `role=status`; they do not repeatedly announce on tab changes.
- All icon-only controls have accessible names and visible hover/focus tooltips. Use Lucide icons; do not draw manual SVGs.
- Focus order matches visual order. Focus rings reuse pine. Opening/collapsing advanced filters and version items preserves focus on the trigger.
- Tab keyboard behavior follows the WAI-ARIA tabs pattern. Lazy tab panels receive focus only when explicitly navigated, not after background loading.
- The binding chain has a text/list equivalent in the same tab. Connectors are decorative and hidden from accessibility APIs.
- Dates render as localized visible text with the ISO value available. Inclusive intervals use `2026-01-01 -> 至今`; never rely on an unlabeled dash.
- Respect `prefers-reduced-motion`. No graph motion, animated reordering, or parallax is permitted; existing subtle control transitions may remain.
- Definition/source long text is selectable. Do not put essential meaning only in a tooltip or truncated attribute.

---

## UI Considerations

Applicable state considerations resolved: 8 covered, 0 backstop, 0 unresolved.

| Category | Element(s) | Status | Resolution / Reason |
|----------|------------|--------|---------------------|
| empty | Catalog, bindings, relations, evidence, lineage, versions | Covered | Every list/region has a domain-specific successful-empty state; no-binding, candidate-only, no-formal-version, error, and unauthorized are distinct |
| loading | Catalog, detail summary, tabs, controls | Covered | Stable-dimension skeletons and region-scoped `aria-busy`; Overview loads first and lazy tabs cannot collapse the page |
| error | Catalog, detail summary, every lazy tab | Covered | Retry preserves URL/scope; tab errors remain local and are never rendered as empty |
| populated | Directory, comparison table, detail tabs, timeline | Covered | Typical-volume layouts, server totals, grouped rows, structured lists, and bounded visualizations are specified |
| partial | Detail/read projections | Covered | Render lawful available facts, mark unavailable subsections, use `未提供`, and never backfill formal truth from legacy or AI content |
| overflow | Toolbar, rows, table, tabs, definitions, visualization | Covered | Controls wrap; table/tabs own deliberate scroll; text wraps or explicitly expands; 320px behavior is defined |
| zero-one-many | Groups, results, bindings, relations, evidence, timeline | Covered | Stable footer/layout and Chinese count grammar cover zero, one, and many; bounded visualization reports omitted counts |
| long-text | Names, Codes, definitions, source titles, excerpts, filters | Covered | Definitions wrap to 80ch; narrow Codes break; table ellipsis requires accessible full text; excerpts have expand/collapse |

---

## SUI Test-State Matrix

Every row is required automated coverage. Prefer pure Node tests for view-model/URL/state partitioning plus route/component tests for visible state and interaction. API contract tests cover projection isolation and filtering.

| ID | Route / fixture | Required assertion |
|----|-----------------|--------------------|
| SUI-01 | `/semantics`, selected project, delayed list request | Stable catalog skeleton, `aria-busy`, no false `0`, no empty copy before success |
| SUI-02 | `/semantics`, successful zero total, no filters | Unfiltered empty heading/body and no pagination claim |
| SUI-03 | `/semantics?q=客户&type=metric`, successful zero total | Filtered empty copy, controls hydrate from URL, clear-filter action works |
| SUI-04 | `/semantics`, list request 500 then retry success | Error copy and Retry; URL/controls retained; empty state never flashes |
| SUI-05 | `/semantics`, 403 | Dedicated unauthorized copy; no facet, total, row, cached protected name, or generic empty output |
| SUI-06 | Catalog item lifecycle `draft` plus active review task | Draft lifecycle and Pending Review process indicator both visible as separate dimensions |
| SUI-07 | Confirmed, Draft, AI Suggested, Rejected, Deprecated fixtures | Default catalog may show the first three with explicit state, excludes Rejected/Deprecated and all audit-only counts; `audit=1&status=rejected` exposes only marked audit rows |
| SUI-08 | Catalog URL with all filters, `as_of`, `view=table`, `page=2` | Refresh restores exact valid state; defaults/invalid params canonicalize; explicit search only fires on Enter/action |
| SUI-09 | Server has 700 concepts, current page has 50 | Search/filter is server-side and total remains authoritative; no client-side pretend-global filtering |
| SUI-10 | Switch Project A to B with A request delayed | A request is aborted/ignored; no A concept or count renders in B scope |
| SUI-11 | `/semantics/42`, delayed header then delayed Bindings | Header skeleton first; Overview resolves; Bindings has independent skeleton; tab load does not hide header |
| SUI-12 | Detail header 500 and Bindings-only 500 | Header failure is page-level retry; tab failure is local retry and preserves loaded header/other tabs |
| SUI-13 | `/semantics/42`, 403 or cross-project id | Unauthorized/not-found safe state without leaking concept identity or prior-project cache |
| SUI-14 | Confirmed version, zero confirmed and zero candidate bindings | Exact no-binding copy; no fabricated graph/path/count |
| SUI-15 | Zero confirmed bindings plus two AI/draft bindings | No-confirmed statement and separate `待治理候选`; candidate count excluded from confirmed assets and chain |
| SUI-16 | Two conflicting high-authority facts | Persistent non-dismissible conflict alert in title area, source summaries and review link; no winner or recommendation |
| SUI-17 | AI Suggested version only, no confirmed effective version | Formal area says `暂无正式版本`; AI text appears only in candidate region with exact warning |
| SUI-18 | Confirmed version plus active review workflow | Confirmed lifecycle remains visible; Pending Review appears separately with lawful workflow metadata/link |
| SUI-19 | `/semantics/42?as_of=2025-12-31` with v1 effective, v2 current | v1 canonical definition and historical banner; Bindings/Evidence/Lineage/Governance current-only regions carry exact label; return-current clears date |
| SUI-20 | Inclusive boundary dates equal `effective_from` and `effective_to` | Same confirmed version is displayed on both boundary dates; no client reimplementation changes backend result |
| SUI-21 | Versions include confirmed, draft, AI Suggested, rejected, deprecated | Oldest-to-newest timeline, effective/current markers correct, audit-only states marked non-current, inline expansion updates `version` |
| SUI-22 | One visible restricted binding target | Only translated type and `受限` exist in DOM/accessibility tree; no name, Code, source excerpt, href, title, or serialized render model leak |
| SUI-23 | Confirmed Target/Mart/Source chain exceeds cap | Exactly one root plus at most four nodes per layer; overflow count shown; keyboard/list fallback complete; candidates excluded |
| SUI-24 | Long Chinese name, 150-char Code, 12k definition, long source title | No overlap at 320/768/1440px; definition wraps; code breaks on narrow view; accessible expansion/full value available |
| SUI-25 | Keyboard-only catalog and detail use | Search submit, filter controls, view switch, tabs, version disclosure, retry, links, and horizontal tab access are operable with visible focus |
| SUI-26 | Navigate catalog -> detail -> asset -> return | Catalog `returnTo` restores query; asset link carries `from=semantics&semanticConceptId`; unsafe external `returnTo` is rejected |
| SUI-27 | Resolved and unresolved question fixtures | Overview count/list contains unresolved only; resolved item appears only in Governance/audit history |
| SUI-28 | Historical mode with a truly temporal evidence item and current-only lineage | Temporal item may be labeled for selected date; current-only label remains on lineage and is not globally suppressed |

Minimum viewport checks: 320x720, 768x1024, 1280x800, and 1440x900. Verify no incoherent overlap, no unintended page-level horizontal overflow, no blank visualization, and visible focus. Tests must also assert `mode=trusted`/audit isolation and project/institution scope at the API boundary.

---

## API And Data Integrity Contract

- Existing Phase 8/9 endpoints remain compatible. Additive catalog/detail projections are allowed only to supply server search over aliases/definition, domain/owner/status/date filters, totals/facets, related confirmed counts, review summary, permission-safe asset display references, evidence/knowledge/lineage references, conflict summaries, and canonical destinations.
- `GET .../versions/effective?as_of=` remains the canonical temporal resolver. The frontend does not calculate a winning version from list order.
- Read projections include stable IDs and reference types, not copied/persisted semantic facts. Evidence, Knowledge, Lineage, Mapping, Governance, and ReviewTask remain authoritative in their existing stores.
- Formal definitions, effective versions, trusted counts, bindings, relations, and paths include Confirmed facts only. Catalog discovery may also expose Draft and AI Suggested identities/content in explicitly labeled non-formal regions. Rejected/deprecated stay audit-only in all modes.
- `related_asset_count` means confirmed bindings under the current trusted projection. It is not semantic coverage and cannot include candidates or audit-only rows.
- Conflict objects provide type, concise summaries, lawful source references, and review navigation. They do not provide a recommended winner.
- Permission evaluation occurs server-side. Frontend redaction is defense in depth, not authorization.
- Pagination/facet responses must be derived from the same filtered population to avoid mismatched totals. Stable ordering requires explicit keys and ID tie-breakers.
- Request results are keyed by project, concept, date, tab, and filters. Never reuse cached data across project scope.

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| None | None | Not applicable - established manual Tailwind system; no third-party registry declared |

---

## Source Traceability

| Source | Contract decisions used |
|--------|-------------------------|
| `11-CONTEXT.md` | All 30 locked decisions: catalog model, grouping/view/search/filter/URL, detail tabs/temporal behavior, governance/provenance/conflict, binding navigation/security, and required states |
| `REQUIREMENTS.md` / `ROADMAP.md` | SUI-01, SUI-02, real-data routes, traceability, and complete state coverage |
| Phase 8/9/10 contexts | Project isolation, confirmed-only trust, candidate/audit separation, canonical versions, authority/state separation, and non-duplicated facts |
| `tailwind.config.ts` / `globals.css` | Existing ink/mist/pine/coral/gold tokens and control/button/panel/badge/grid/empty-state vocabulary |
| `AppShell`, `ProjectContext`, `WorkspaceHeader`, `api.ts` | Existing navigation, project scope, header, authentication, timeout, and normalized errors |
| `catalog/page.tsx`, `fields/page.tsx`, `review-tasks/page.tsx`, `LineageGraph.tsx` | Operational density, pagination/row patterns, canonical routes, review navigation, and lineage display vocabulary |
| `backend/app/api/semantic.py` / `schemas/semantic.py` | Real concept/version/binding/relation/graph contracts, enums, effective endpoint, and current query gaps requiring additive projections |

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS
- [ ] Dimension 2 Visuals: PASS
- [ ] Dimension 3 Color: PASS
- [ ] Dimension 4 Typography: PASS
- [ ] Dimension 5 Spacing: PASS
- [ ] Dimension 6 Registry Safety: PASS

**Approval:** pending
