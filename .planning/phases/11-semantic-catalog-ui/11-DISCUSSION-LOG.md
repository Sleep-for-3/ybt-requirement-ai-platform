# Phase 11: Semantic Catalog UI - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md; this log preserves the alternatives considered.

**Date:** 2026-08-24
**Phase:** 11-Semantic Catalog UI
**Areas discussed:** 目录浏览与筛选, 详情页与时间版本, 治理状态展示, 关联追溯与异常状态

---

## 目录浏览与筛选

The user established the enterprise Data Catalog model, fields, search surface, filters and audit-only visibility before the focused questions.

| Decision point | Options considered | Selected |
|---|---|---|
| Default grouping | Business Domain; Concept Type; flat list | Business Domain, with `未分类` group |
| View modes | Grouped directory + medium table; grouped directory + compact list; grouped only | Grouped directory + medium table |
| Durable state | All in URL; only core filters/`as_of`; page state only | All search/filter/view/`as_of` state in URL |
| Search update | Explicit submit; debounced live search; local filtering | Explicit submit; enum filters update immediately |

**Notes:** Rejected/deprecated are hidden by default and only enter through explicit audit/history filters. Search must be server-authoritative across name, code, alias and definition.

---

## 详情页与时间版本

The user established top summary plus tabs, Overview priorities, version timeline and a whole-page historical snapshot state before the focused questions.

| Decision point | Options considered | Selected |
|---|---|---|
| Non-temporal sections in history mode | Show with current-state label; hide; show without distinction | Show with `当前状态，不代表该历史日期` label |
| `as_of` entry | Detail header; Versions tab; separate modal entry | Detail header plus current-version return action |
| Tab loading | Overview first/lazy tabs; load all; preload summaries | Overview first, other tabs on demand |
| Version detail | Inline timeline expansion; side drawer; separate route | Inline timeline expansion |

**Notes:** The effective SemanticConceptVersion is canonical. Historical mode must be unmistakable and may not imply current-only relationships are historical facts.

---

## 治理状态展示

The user established Confirmed-first visual priority, restrained badges, consolidated trust/source presentation, AI non-formality and conflict-to-human-review behavior before the focused questions.

| Decision point | Options considered | Selected |
|---|---|---|
| Pending Review | Separate lifecycle + workflow states; replace primary state; Governance-only | Separate lifecycle and workflow states |
| Governance actions | Read-only with Review Task link; inline review; status only | Read-only with existing Review Task link |
| AI-only Concept | `暂无正式版本` plus candidate area; AI as primary definition; hide AI | `暂无正式版本` plus separate candidate area |
| High-authority conflict | Persistent banner and allow inspection; block page; Governance-only | Persistent non-dismissible banner, no AI winner |

**Notes:** Pending Review never means Confirmed. Rejected/deprecated remain non-current audit/history objects.

---

## 关联追溯与异常状态

The user established Binding as a core capability, structured lists, bounded visualization, existing-route reuse and distinct exceptional states before the focused questions.

| Decision point | Options considered | Selected |
|---|---|---|
| Bounded visualization | Data-asset chain; semantic graph; combined graph | Concept -> Target -> Mart -> Source asset chain |
| Binding status layout | Confirmed/candidate sections; candidates collapsed; mixed list | Separate visible Confirmed and candidate sections |
| Asset navigation | Current-tab existing route; new tab; preview drawer | Current-tab existing route with return context |
| Restricted asset | Redacted placeholder; hide Binding; full summary/no link | Redacted type-only placeholder, no link |

**Notes:** Candidates do not count as confirmed paths. Loading failures receive retry and never appear as empty. Resolved questions are omitted from current open-question presentation.

---

## the agent's Discretion

- Component boundaries, query/cache approach and additive read API shape.
- Pagination mechanics, bounded visualization limits and exact responsive adaptations.
- Exact restrained token/color assignments and copy refinements consistent with the locked semantics.

## Deferred Ideas

- Requirement Workspace V2 (Phase 12)
- Intelligence Dashboard (Phase 13)
- DataQualityExpectation (Phase 14)
- Semantic Impact (Phase 15)
- SQL Generator
- Large draggable semantic/knowledge graph
