# Phase 11 — UI Review

**Audited:** 2026-08-26  
**Baseline:** Approved `11-UI-SPEC.md` design contract  
**Scope:** `/semantics` and `/semantics/{id}` only  
**Screenshots:** Captured. The current server's no-project state was sampled at 320×720, 768×1024, 1280×800, and 1440×900 in `.planning/ui-reviews/11-live-probe/`. Production routes with intercepted representative API fixtures were sampled at 320×720 and 1440×900 in `.planning/ui-reviews/11-fixtures/`. The complete stateful four-viewport matrix was not captured.  
**Live interaction gate:** `node --test frontend/tests/semantic-catalog-browser.test.mjs` — 12/12 passed on 2026-08-26 (66.7s).  
**Qualification:** `needs_human_review: true` for populated 768×1024 and 1280×800 layouts, comparison-table geometry, conflict/historical/candidate/restricted/chain states at every viewport, color contrast in alert states, and visible keyboard-focus treatment.

---

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 2/4 | Catalog copy is strong, but multiple governed detail strings diverge from the approved exact copy and region errors expose English implementation labels. |
| 2. Visuals | 3/4 | Directory and Overview have a restrained, scannable hierarchy at sampled widths; lifecycle text wraps awkwardly in the desktop row and most exceptional/tab visuals remain unobserved. |
| 3. Color | 3/4 | The semantic UI uses only the approved token palette with a credible mist/white/pine balance; alert-state contrast and distribution were not live-verified. |
| 4. Typography | 2/4 | The four declared sizes are respected in TSX, but shared button/badge styles introduce forbidden 500 weight and the formal definition is not capped at 80ch. |
| 5. Spacing | 2/4 | Major gaps and row heights follow the scale, but toolbar controls remain 40px on mobile instead of the required 44px targets. |
| 6. Experience Design | 3/4 | State isolation, retries, redaction, disclosures, and keyboard tab behavior pass real-route tests; the historical-date interaction does not implement the explicit submit/validation contract. |

**Overall: 15/24**

No shipping **BLOCKER** was proven in the sampled routes. All implementation findings below are **WARNING** severity; unresolved visual judgments are separately marked `needs_human_review`.

---

## Top 3 Priority Fixes

1. **Restore the governed copy contract** — inconsistent conflict, error, empty, and review wording weakens the catalog's trust model — use the exact approved title/body/CTA and localized region names from `11-UI-SPEC.md`, including `存在无法自动裁决的高权威冲突`, `前往评审任务`, and the dedicated relation/evidence/lineage empty copy.
2. **Restore the historical-date interaction contract** — changing the native date currently starts navigation immediately and an arbitrary `9999-12-31` maximum is imposed — keep a local draft, add the visible `查看指定日期` action, validate before requesting, and derive any maximum only from the backend.
3. **Close the typography and mobile-target token gaps** — 500-weight buttons/badges, a `max-w-5xl` formal definition, and 40px toolbar controls diverge from the approved system — use 400/600 weights, `max-w-[80ch]`, and at least 44px targets below 768px, then rerun the four-viewport focus matrix.

---

## Detailed Findings

### Pillar 1: Copywriting (2/4)

- **WARNING — conflict language is materially different from the locked governance copy.** `SemanticDetailHeader.tsx:54-57` renders `高权威事实存在冲突`, a generated summary, `多个高权威事实无法由系统自动裁决，未选择任何胜出方。`, and `前往人工评审`. The contract requires the exact title `存在无法自动裁决的高权威冲突`, the exact explanatory body, and CTA `前往评审任务`. This is not cosmetic: it is the user's assurance that the system has not adjudicated a winner.
- **WARNING — lazy-region copy leaks English implementation names.** `app/semantics/[id]/page.tsx:52-59` defines `Bindings`, `Relations`, `Evidence`, `Lineage`, `Governance`, and `Versions`; `AsyncRegion.tsx:20-21` injects these into permission, error, and retry text. The result is mixed copy such as `Bindings加载失败`, rather than a localized object-specific message matching `{区域名称}加载失败。其他区域仍可查看。` and `重新加载{区域名称}`.
- **WARNING — dedicated successful-empty copy drifts.** `app/semantics/[id]/page.tsx:198`, `RelationList.tsx:8`, and `app/semantics/[id]/page.tsx:180,183` shorten the approved no-relation, no-evidence, and no-lineage messages. The distinctions between “no confirmed relation,” “no viewable evidence/knowledge source,” and “no verified lineage path” should remain explicit.
- **WARNING — Overview uses implementation-oriented prose.** `app/semantics/[id]/page.tsx:165` tells users that regions “独立加载” and mixes six English component names into Chinese prose. Replace it with task-focused orientation or omit it; loading boundaries already communicate themselves.
- **Positive evidence:** catalog title, search placeholder/action, both catalog empty variants, unauthorized body, catalog error body/reload, AI-only formal state, AI candidate label, and current-only historical label match the contract in `app/semantics/page.tsx:95-134`, `SemanticDetailHeader.tsx:46-49,66,77`, and the current-only notices.

### Pillar 2: Visuals (3/4)

- **WARNING — the lifecycle column does not keep its intended stable rhythm.** The 1440×900 populated catalog screenshot shows `已确认 / Confirmed` wrapping onto two lines inside the 120px lifecycle track. `GroupedSemanticDirectory.tsx:31` fixes that track to 120px while `SemanticStatus.tsx:8-14` deliberately carries the bilingual label. Increase the lifecycle/review track or allow the row grid to redistribute space without compressing the trust label.
- **WARNING — the row arrow does not implement the specified secondary icon affordance.** `GroupedSemanticDirectory.tsx:33-35` places `ArrowUpRight` inside the name link and supplies an SVG accessible label, but no separate icon-only link or visible tooltip. Either implement the contracted secondary link with tooltip `查看语义详情`, or remove the redundant icon semantics and keep one clearly named link.
- **Positive evidence:** sampled 320×720 and 1440×900 populated screenshots show a clear catalog focal point, restrained toolbar, full-width grouped row collection, non-card detail header, visible trust hierarchy, horizontally scrollable mobile tabs, and no marketing/hero/gradient content within the Phase 11 surfaces. `BindingChain.tsx:12-15` also keeps the visualization bounded and provides a text equivalent.
- `needs_human_review: true` — populated comparison table at 320/768/1280/1440; conflict, historical, candidate, restricted, bindings, relations, evidence, lineage, governance, versions, and bounded-chain visual states were not all captured. The direct current-server screenshots had no selected project; intercepted fixture screenshots covered catalog populated and detail Overview only at 320 and 1440.

### Pillar 3: Color (3/4)

- **WARNING / qualification — alert-state contrast is not fully visually proven.** Static analysis found 23 pine, 43 gold, and 30 coral token-class occurrences across the 15 semantic TSX files, with zero hardcoded hex/RGB colors. Pine is used for navigation, search, selected view/tab, focus, trusted badges, and semantic links; gold/coral are confined to candidate/history/error/conflict surfaces in code. However, the live captured populated state contained no coral conflict/error banner and only a compact gold review label.
- **Positive evidence:** `tailwind.config.ts:7-48` supplies the approved mist/line/pine/coral/gold values; semantic route/component scanning found no hardcoded colors. Captured catalog and Overview screens maintain a credible dominant mist, secondary white/line, and restrained pine accent distribution rather than filling rows or large regions with accent.
- `needs_human_review: true` — verify WCAG 2.2 AA for coral/gold text and borders, focus rings, disabled controls, table sticky cells, and status combinations in the actual rendered browser.

### Pillar 4: Typography (2/4)

- **WARNING — shared component styles introduce a prohibited third weight.** Semantic TSX uses exactly `text-xs` (48 occurrences), `text-sm` (55), `text-base` (22), and `text-xl` (1), and explicitly uses only regular/semibold. But `globals.css:49-50,81-82` composes `font-medium` into every `.button` and `.badge`, so Phase 11 buttons and lifecycle badges render at 500 despite the contract's exact 400/600 vocabulary.
- **WARNING — the formal definition is wider than the approved reading measure.** `SemanticDetailHeader.tsx:66` uses `max-w-5xl`; the contract requires `max-w-[80ch]`. Long-definition automation proves content remains selectable (`semantic-catalog-browser.test.mjs:365-383`), but it does not prove comfortable line length.
- **Positive evidence:** concept code, versions, intervals, and dates consistently use `font-mono`/tabular treatment, and the sampled screens show a clear 20px title, 16px section heading, 14px body, and 12px metadata hierarchy.

### Pillar 5: Spacing (2/4)

- **WARNING — mobile targets miss the 44px contract.** `CatalogToolbar.tsx:46-66,92-98` fixes search, primary action, selects, and the segmented view control at 40px (`h-10`). These are the main mobile interactions, while the contract requires mobile tap targets of at least 44×44. Apply `min-h-11` below 768px while preserving the 40px desktop toolbar density if desired.
- **WARNING — minimum-width control tracks need an explicit narrow-screen rule.** `CatalogToolbar.tsx:46,53,92,98` introduces 240/112/144/76px minimums outside the declared spacing exceptions. The fixture-driven 320px screenshot reflowed successfully, but the control strategy is brittle; use `w-full min-w-0` on the narrow breakpoint and reintroduce minima at `sm`/`md`.
- **Positive evidence:** page padding (`p-4 lg:p-6`), 16/24/32px vertical rhythm, 68px directory rows, 56px table rows, 1120px intentional table overflow, 44px detail actions, and the 8px bounded-tool radii follow the contract. Sampled 320 and 1440 populated layouts showed no unintended page-level horizontal overflow.
- `needs_human_review: true` — populated 768×1024 and 1280×800 screenshots, 320px table/sticky-column behavior, 320px long 150-character Code, and every lazy-region skeleton need geometry inspection.

### Pillar 6: Experience Design (3/4)

- **WARNING — date selection bypasses the approved commit/validation step.** `SemanticDetailHeader.tsx:39-41` calls `onAsOf` directly from the date input's `onChange`, exposes no `查看指定日期` action, and hardcodes `max="9999-12-31"`. The contract requires a labeled draft date plus explicit action, an inline invalid-date message with no request, and a maximum only when provided by the backend.
- **WARNING — visible focus quality is not established by state-only automation.** The current real-route suite passed 12/12, including Arrow-key tab focus (`semantic-catalog-browser.test.mjs:261-289`), restricted DOM/AX redaction (`:291-303`), conflict disclosure (`:305-330`), independent evidence disclosures (`:332-363`), and selectable 12k text (`:365-383`). These prove operation and focus ownership, not focus-ring visibility/contrast at every viewport.
- **Positive evidence:** catalog and detail have distinct idle/loading/empty/forbidden/error/populated models, stable skeletons with `aria-busy`, local object-specific retry, stale request rejection, safe project switching, no destructive commands, candidate/audit/current-only separation, bounded chain output, lawful route validation, independent disclosures, and WAI-ARIA tab keyboard behavior. The 12 current browser tests passed with zero failures/skips.
- `needs_human_review: true` — traverse search, filters, view mode, pagination, tabs, date control, disclosures, retries, and links with keyboard only at 320×720, 768×1024, 1280×800, and 1440×900 while observing the actual focus ring and scroll-into-view behavior.

---

## Finding Classification

- **BLOCKER:** 0 proven.
- **WARNING:** 12 concrete implementation/contract deviations across copy, visuals, typography, spacing, and date interaction.
- **needs_human_review:** 5 grouped qualifications covering the incomplete stateful viewport matrix, alert contrast, populated intermediate widths, long-content/table/chain geometry, and visible keyboard focus.

## Registry Audit

Skipped by contract: no `components.json` exists, `shadcn_initialized: false`, and `11-UI-SPEC.md` declares no registry or third-party block.

---

## Files Audited

- `.planning/phases/11-semantic-catalog-ui/11-UI-SPEC.md`
- `.planning/phases/11-semantic-catalog-ui/11-CONTEXT.md`
- `.planning/phases/11-semantic-catalog-ui/11-01-PLAN.md` through `11-09-PLAN.md`
- `.planning/phases/11-semantic-catalog-ui/11-01-SUMMARY.md` through `11-09-SUMMARY.md`
- `.planning/phases/11-semantic-catalog-ui/11-GAP-QUALIFICATION.md`
- `.planning/phases/11-semantic-catalog-ui/11-VERIFICATION.md`
- `frontend/app/semantics/page.tsx`
- `frontend/app/semantics/[id]/page.tsx`
- All 13 files under `frontend/components/semantic-catalog/`
- `frontend/lib/semantic-catalog-controller.mjs`
- `frontend/lib/semantic-catalog-view-model.mjs`
- `frontend/lib/semantic-catalog-dom-contract.mjs`
- `frontend/lib/semantic-detail-contract.mjs`
- `frontend/lib/semantic-entity-types.mjs`
- `frontend/tests/semantic-catalog-view-model.test.mjs`
- `frontend/tests/semantic-catalog-dom.test.mjs`
- `frontend/tests/semantic-detail-contract.test.mjs`
- `frontend/tests/semantic-catalog-browser.test.mjs`
- `frontend/app/globals.css`
- `frontend/tailwind.config.ts`
- `frontend/components/AppShell.tsx`
- `frontend/components/WorkspaceHeader.tsx`
- `frontend/components/ProjectContext.tsx`

## Screenshot Evidence

- `.planning/ui-reviews/11-live-probe/` — current localhost:3000, no selected project, catalog/detail at 320×720, 768×1024, 1280×800, and 1440×900.
- `.planning/ui-reviews/11-fixtures/` — real production routes/components with intercepted representative API data, populated catalog/detail Overview at 320×720 and 1440×900.
- Screenshot files are covered by `.planning/ui-reviews/.gitignore`; they are evidence only and are not part of this review artifact.
