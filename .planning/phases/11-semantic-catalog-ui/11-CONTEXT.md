# Phase 11: Semantic Catalog UI - Context

**Gathered:** 2026-08-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 11 adds a governed, project-scoped Semantic Catalog experience at `/semantics` and `/semantics/{id}` using the existing Next.js shell, Design Tokens, permissions and real backend facts. The catalog must help business and data users understand what a regulatory semantic concept means, whether it is currently effective and trustworthy, why it is trustworthy, which regulatory/data assets it binds to, how it relates to other concepts, and how it changed over time.

This is a read-oriented Data Catalog and governance inspection experience, not a generic `SemanticConcept` CRUD administration page. Phase 11 may add compatible read/query APIs needed by the two routes, but it must not redesign Phase 8 temporal semantics, create competing fact sources, or move governance decisions into the UI. Requirement Workspace V2, dashboard metrics, DataQualityExpectation, Semantic Impact and SQL generation remain outside this phase.

</domain>

<decisions>
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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone and Phase Contracts

- `.planning/PROJECT.md` — Product principles, constraints and milestone scope.
- `.planning/REQUIREMENTS.md` — SUI-01 and SUI-02 acceptance requirements and the Phase 12+ boundary.
- `.planning/ROADMAP.md` — Phase 11 goal and success criteria.
- `.planning/STATE.md` — Current GSD milestone and phase state.

### Locked Semantic and Context Foundations

- `.planning/phases/08-semantic-foundation/08-CONTEXT.md` — Project/institution scope, semantic lifecycle and additive API boundaries.
- `.planning/phases/09-regulatory-context/09-CONTEXT.md` — Confirmed-only policy, canonical temporal versions, authority/provenance and rejected/deprecated isolation.
- `.planning/phases/10-generator-refactor/10-CONTEXT.md` — Sole-fact-source, governance and no-competing-context decisions carried into UI presentation.

### Codebase Assessments

- `.planning/codebase/UI-API-MAPPING.md` — Existing routes and authoritative API/entity mappings that Phase 11 must reuse.
- `.planning/codebase/REGULATORY-SEMANTIC-ASSESSMENT.md` — Semantic models, supported Binding targets, existing routes and frontend integration boundaries.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `frontend/components/AppShell.tsx`: Existing grouped navigation, responsive drawer, project selector and active-route conventions; add Semantic Catalog without rebuilding the shell.
- `frontend/components/ProjectContext.tsx`: Authoritative selected-project state and project isolation boundary for frontend requests.
- `frontend/components/WorkspaceHeader.tsx`: Existing page-title/action layout for catalog and detail headers.
- `frontend/lib/api.ts` and `frontend/lib/http-response.mjs`: Authenticated API requests, 401 handling, timeout and normalized errors.
- `frontend/app/globals.css`: Existing `control`, button, panel, badge, grid-row, empty-state and Design Token vocabulary.
- `frontend/components/LineageGraph.tsx` and existing lineage pages: Reference for bounded relationship display and links to current lineage routes; do not copy the technical lineage model.
- Existing `/fields`, `/mart`, `/knowledge`, `/lineage` and `/review-tasks` routes: Canonical destinations for Binding, Evidence, Lineage and governance navigation.

### Established Patterns

- App Router pages are project-aware client experiences using `ProjectContext` and the shared API client.
- Existing semantic APIs are additive and permission-protected under `/projects/{project_id}`.
- Confirmed semantic versions are canonical; rejected/deprecated objects are audit-only; AI suggestions never become formal truth through display choices.
- Current pages use restrained operational layouts, medium-density rows and explicit empty/error states rather than marketing composition.

### Integration Points

- `backend/app/api/semantic.py` already provides concept CRUD/list/detail, version/effective-version, Binding, Relation, bounded graph and resolver endpoints. Its current catalog list query only covers type/status/basic `q`, so planning must assess compatible query/read-model additions for aliases/definition, domain, Owner, `as_of`, Binding/Relation/review flags, counts and scalable result navigation.
- `backend/app/schemas/semantic.py` exposes Concept, Version, Binding, Relation, graph and provenance-bearing version fields; new frontend DTOs must reflect these real contracts rather than inventing metrics.
- Evidence, Knowledge and Lineage remain authoritative in their existing models/routes. If the detail page needs a consolidated read projection, it must reference those sources and preserve permission boundaries rather than persist a second semantic detail store.
- `frontend/components/AppShell.tsx` needs a Semantic Catalog navigation entry placed consistently with the product information architecture.
- Frontend regression coverage currently relies on TypeScript checks and focused Node tests; Phase 11 needs route/view-model/component coverage for the full SUI state matrix.

</code_context>

<specifics>
## Specific Ideas

- Product hierarchy: `它是什么 -> 当前是否可信/生效 -> 为什么可信 -> 关联哪些监管和数据资产 -> 与其他语义的关系 -> 过去如何变化`.
- Header example: `[语义名称 / Code] [类型] [Confirmed]`, followed by Definition, Domain, Owner and Effective Version.
- Historical banner example: `Viewing as of 2025-12-31` / `当前正在查看历史语义版本`.
- Trust region example: Governance state, Authority (`Regulatory / Business Confirmed`), Source (`《XX监管报送制度》第 X 条`) and Effective interval (`2026-01-01 ->`).
- Empty-state copy: `当前语义尚未绑定数据资产。`
- Candidate-state copy: `发现候选关联，但尚未经过人工确认。`
- Conflict copy must communicate that multiple high-authority facts cannot be automatically adjudicated.

</specifics>

<deferred>
## Deferred Ideas

- Requirement Workspace V2 and document-preview behavior belong to Phase 12.
- Semantic/mapping/lineage coverage dashboard and project readiness belong to Phase 13.
- Structured DataQualityExpectation belongs to Phase 14.
- Semantic Impact propagation belongs to Phase 15.
- SQL Generator remains outside Phase 11.
- A large free-form draggable semantic/knowledge graph is not part of the first Semantic Catalog UI.

</deferred>

---

*Phase: 11-Semantic Catalog UI*
*Context gathered: 2026-08-24*
