---
phase: 10-generator-refactor
verified: 2026-08-23T12:14:21Z
status: gaps_found
score: 3/11 must-haves verified
behavior_unverified: 1
overrides_applied: 0
gaps:
  - truth: "Every Source-to-Mart, Mart-to-YBT, Scenario, and Deliverable generation entry point uses one authorized candidate RegulatoryContext as its sole shared-fact input."
    status: failed
    reason: "Deliverable queued and direct compile paths still call legacy Source-to-Mart and Mart-to-YBT compiler functions. Those compilers query peer ORM rows directly, do not build RegulatoryContext, do not evaluate readiness, have no as_of trace, and mutate mapping draft fields. The Deliverable handler authorizes only deliverable.generate before these technical mapping writes. In addition, the active /fields/{field_id}/generate-mapping endpoint still calls legacy_field_mapping, constructs one composite Source-to-Mart/Mart-to-YBT draft from RAG, SQL parse, template, and database-probe sources, and never uses RegulatoryContextBuilder."
    artifacts:
      - path: "backend/app/api/deliverables.py"
        issue: "Lines 538-556 and 790-797 invoke legacy compilers instead of governed generators; queued compilation has no per-mapping technical.edit check."
      - path: "backend/app/services/deliverables/source_to_mart_compiler.py"
        issue: "Lines 6-20 query ScenarioBusinessMapping and ScenarioTechnicalLineage directly and write SourceToMartMapping.ai_generated_content and summaries."
      - path: "backend/app/services/deliverables/mart_to_ybt_compiler.py"
        issue: "Lines 6-18 query TargetField, MartField, MartTable, and SourceToMartMapping directly and write MartToYbtMapping.ai_generated_content."
      - path: "backend/app/services/mapping_generator.py"
        issue: "Lines 35-191 implement the active legacy_field_mapping generator with direct RAG, SQL/template/NL-task shared-fact construction and FieldMappingDraft writes."
      - path: "backend/app/api/target_fields.py"
        issue: "Lines 42-47 expose the legacy composite mapping generator as a production route."
    missing:
      - "Route queued and direct Source-to-Mart/Mart-to-YBT Deliverable work through the frozen Principal, technical.edit-authorized Project, optional/resolved as_of, one Context build, typed adapter, readiness, and optimistic write boundary."
      - "Migrate, explicitly retire, or isolate the active legacy /fields/{field_id}/generate-mapping path so it cannot remain a competing production shared-fact constructor for Source-to-Mart/Mart-to-YBT drafts."
      - "Add direct compile and Deliverable-job tests that create actual Source-to-Mart and Mart-to-YBT rows and assert one builder call, technical.edit enforcement, lifecycle filtering, and zero legacy peer reads."
  - truth: "Generation never mutates an approved/final/confirmed mapping outside explicit human adoption or review."
    status: failed
    reason: "Source-to-Mart and Mart-to-YBT generate-draft services have no editability/status guard before Context/model execution or after locking. An unchanged approved row therefore passes snapshot comparison and _apply_output rewrites its governed draft fields while mapping_status remains approved. Direct compiler endpoints also have no status guard."
    artifacts:
      - path: "backend/app/services/mapping/source_to_mart_generator.py"
        issue: "Lines 64-80 and 128-182 snapshot, generate, lock, compare, and apply without rejecting mapping_status=approved."
      - path: "backend/app/services/mapping/mart_to_ybt_generator.py"
        issue: "Lines 57-73 and 121-175 have the same missing lifecycle/editability guard."
      - path: "backend/app/api/deliverables.py"
        issue: "Lines 790-797 expose mutating compilers without an approved/final guard."
    missing:
      - "Define and enforce double-layer mapping editability before Context/model work and again after the fresh task lock."
      - "Add direct-service and API regressions starting from approved/review-locked rows; assert zero model call, zero field mutation, and a stable governed non-success response."
  - truth: "Only unresolved Context questions are projected and merged as open generation questions."
    status: partial
    reason: "SourceToMartContextAdapter copies all context.open_questions without filtering resolution_state, unlike the shared projection path used by the other adapters. Resolved questions are converted to constraints without resolution state and can be re-appended as open questions."
    artifacts:
      - path: "backend/app/services/mapping/context_adapters.py"
        issue: "Lines 155-168 omit the resolution_state == open filter present at lines 645-670."
    missing:
      - "Filter Source-to-Mart Context questions to resolution_state=open before projection, or preserve and enforce resolution state through merge."
      - "Add a regression with one open and one resolved Context question and assert only the open item reaches prompt, merge, trace, and pending-confirmation state."
  - truth: "Qualification evidence covers all production generation and compiler paths strongly enough to support the complete no-fallback and governance claims."
    status: failed
    reason: "The passing focused/full suites do not exercise the failing Deliverable Source/Mart compiler loops, direct compile permission boundary, or generation starting from an already-approved double-layer row. The 10-QUALIFICATION claim that every entry point uses the Context seam is therefore contradicted by current production code."
    artifacts:
      - path: "backend/tests/test_scenario_traceability.py"
        issue: "The Deliverable Context test at lines 986-1029 seeds Scenario rows only, so the Source/Mart compiler loops are not entered."
      - path: "backend/tests/test_double_layer_mapping.py"
        issue: "Approved Source rows are used as upstream Context fixtures, but no test invokes generate-draft on an already-approved Source-to-Mart or Mart-to-YBT task."
      - path: ".planning/phases/10-generator-refactor/10-QUALIFICATION.md"
        issue: "GEN/D verdicts overstate complete entry-point coverage despite the untested legacy compiler and approved-row paths."
    missing:
      - "Close the production gaps first, then rerun focused/adjacent/full qualification with explicit compiler and approved-row tests."
behavior_unverified_items:
  - truth: "Fresh Project-to-task row locking and concurrent commit behavior holds under the production PostgreSQL driver."
    test: "Run the direct and queued concurrent-generation barrier cases against a provisioned PostgreSQL staging database, including permission revocation, approved/editability change, and competing task updates."
    expected: "No lock spans Context/model work; the fresh transaction validates actor and permission, locks Project then task, rejects stale/governed changes, and commits at most one allowed draft state."
    why_human: "Local execution and the supplied qualification use SQLite; no live PostgreSQL service was available, so real SELECT FOR UPDATE blocking/order and concurrent commit behavior were not exercised."
---

# Phase 10: Generator Refactor Verification Report

**Phase Goal:** Refactor the existing Mapping/Scenario generators to consume unified RegulatoryContext while preserving old APIs and governance boundaries. For this verification, the submitted contract also requires RegulatoryContextBuilder to be the sole shared-fact entry across Source-to-Mart, Mart-to-YBT, Scenario, and Deliverable generation paths, with task-specific projections, deterministic readiness, temporal traceability, authority/provenance preservation, and no production legacy fallback.

**Verified:** 2026-08-23T12:14:21Z  
**Status:** gaps_found  
**Re-verification:** No — initial verification

## Verdict

Phase 10 is **not achieved** in the current repository state. The canonical four LLM generator services are substantially Context-backed, but production Deliverable compiler paths remain a second legacy shared-fact construction and mutation path. Approved double-layer mappings also remain writable through generate-draft, and Source-to-Mart reopens resolved Context questions.

The two BLOCKERs and one WARNING in `10-REVIEW.md` are all still present:

| Review finding | Current verdict | Current evidence |
| --- | --- | --- |
| CR-01 — Deliverable compilers bypass Context and technical-edit authorization | **OPEN BLOCKER** | `deliverables.py:538-556,790-797`; both compiler modules still perform direct ORM reads and writes. The Deliverable router is included without the shared resource-guard dependency, so its explicit `deliverable.generate` check is the operative endpoint permission. |
| CR-02 — approved double-layer mappings remain writable through generate-draft | **OPEN BLOCKER** | Neither double-layer service calls an editability guard before generation or after locking; unchanged `mapping_status=approved` passes snapshot comparison and reaches `_apply_output`. |
| WR-01 — resolved Source-to-Mart Context questions are reopened | **OPEN WARNING / PARTIAL MUST-HAVE** | `SourceToMartContextAdapter.project` omits the `resolution_state == "open"` filter used by `_projection_inputs`. |

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | All relevant production entry points use one authorized candidate RegulatoryContext and no legacy shared-fact fallback. | **FAILED — BLOCKER** | Canonical generators call `build_generation_context`, but Deliverable queued/direct compiler paths bypass it and call legacy ORM compilers; `/fields/{id}/generate-mapping` also remains an active `legacy_field_mapping` RAG/SQL/template path. |
| 2 | Source-to-Mart direct generation preserves its route, prompt key, structured output, and task-specific projection through Context. | **VERIFIED** | `mapping_rules.py:99-139` passes exact Principal/authorized Project/as_of; `source_to_mart_generator.py:53-119` builds one Context then runs `source_to_mart_mapping` with `SourceToMartOutput`. |
| 3 | Mart-to-YBT direct generation preserves its route/output and approved upstream summary semantics through Context. | **VERIFIED** | `mapping_rules.py:234-274`; `mart_to_ybt_generator.py:46-112`; `_approved_upstream_rules` admits only approved/FactState.APPROVED rule_text. |
| 4 | Scenario business/technical direct, batch, and Deliverable Scenario calls use distinct Context projections and governed physical safety. | **VERIFIED** | Direct routes authorize and pass as_of; Scenario services use separate adapters/outputs and re-check editability; jobs and Deliverable Scenario callers recover an active non-legacy actor and pass authorized Project. |
| 5 | Missing proof is handled by deterministic readiness/questions/caps and authoritative conflicts block before every production mutation. | **FAILED — BLOCKER** | Canonical readiness is substantive, but both Deliverable compilers bypass readiness. Mart compiler calls any upstream row `evidence_supported`; Source compiler consumes unfiltered Scenario rows. |
| 6 | Temporal as_of, authority, provenance, and confidentiality are preserved across every generation path. | **FAILED — BLOCKER** | `GenerationTraceSummary` covers canonical generators, but legacy compilers accept no as_of, retain no Context trace, and perform no authority/confidentiality projection. |
| 7 | AI generation cannot mutate approved/final/confirmed governed state outside explicit human adoption/review. | **FAILED — BLOCKER** | Double-layer generators lack status/editability guards, and direct compile endpoints mutate rows without lifecycle checks. |
| 8 | Every mutating path uses fresh actor/permission validation and optimistic Project-to-task locking before write. | **FAILED — BLOCKER** | Canonical generators implement the protocol; compiler functions write directly in the caller transaction, and queued compiler work has only package-level `deliverable.generate`. |
| 9 | Human/Context/AI question merge is stable and only unresolved Context questions remain open. | **FAILED / PARTIAL** | Stable merge and idempotence tests pass, but Source adapter projects resolved questions as open constraints. |
| 10 | Regression qualification covers the complete production contract and supports the no-fallback claims. | **FAILED — BLOCKER** | 386 passing tests do not cover the compiler loops, direct compile authorization, or approved-row generation. The production code contradicts the qualification narrative. |
| 11 | Production PostgreSQL locking/concurrent-commit semantics are exercised. | **PRESENT_BEHAVIOR_UNVERIFIED** | Application ordering and SQLite tests exist, but live PostgreSQL was unavailable and no production-driver concurrency test ran. |

**Score:** 3/11 truths verified (1 present, behavior-unverified)

### Roadmap Success Criteria

| Criterion | Status | Evidence |
| --- | --- | --- |
| Both Mapping Generators obtain shared facts from ContextBuilder. | **FAILED** | Direct generate-draft services do, but the same Source/Mart rows are generated through Deliverable compiler paths that construct shared facts from ORM peers. |
| Generator-specific task instructions and structured outputs remain. | **VERIFIED** | Four canonical variants retain distinct prompt keys, output models, projections, and renderers. |
| AI draft does not overwrite final/confirmed; missing evidence creates questions rather than hallucinated facts. | **FAILED** | Approved double-layer rows are mutable and compiler paths bypass governed readiness/evidence classification. |

## Production Entry-Point Audit

| Entry point | Shared-fact path | Authorization/write boundary | Status |
| --- | --- | --- | --- |
| `POST /source-to-mart-mappings/{id}/generate-draft` | One RegulatoryContext -> Source adapter | technical.edit, fresh reauthorization/locks | **VERIFIED except approved editability gap** |
| `POST /mart-to-ybt-mappings/{id}/generate-draft` | One RegulatoryContext -> Mart adapter | technical.edit, fresh reauthorization/locks | **VERIFIED except approved editability gap** |
| `POST /scenario-business-mappings/{id}/generate-draft` | One RegulatoryContext -> business adapter | business.edit + editability before/after model | **VERIFIED** |
| `POST /scenario-technical-lineages/{id}/generate-draft` | One RegulatoryContext -> technical adapter | technical.edit + editability before/after model | **VERIFIED** |
| Scenario batch jobs | Same Scenario services | active queued User, family permission, generator fresh boundary | **VERIFIED** |
| Deliverable queued Scenario generation | Same Scenario services | active queued User, per-family permission, generator fresh boundary | **VERIFIED** |
| Deliverable queued Source-to-Mart compilation | Direct peer ORM compiler | package-level deliverable.generate; direct transaction write | **FAILED** |
| Deliverable queued Mart-to-YBT compilation | Direct Target/Mart/upstream ORM compiler | package-level deliverable.generate; direct transaction write | **FAILED** |
| `POST /source-to-mart-mappings/{id}/compile` | Direct peer ORM compiler | deliverable.generate only; no Context/readiness/as_of | **FAILED** |
| `POST /mart-to-ybt-mappings/{id}/compile` | Direct Target/Mart/upstream ORM compiler | deliverable.generate only; no Context/readiness/as_of | **FAILED** |
| `POST /fields/{id}/generate-mapping` | `legacy_field_mapping`: RAG + SQL parse + template + NL-task/DB-probe facts | Active secured production route writing a composite Source/Mart `FieldMappingDraft` | **FAILED** — competing legacy shared-fact generator under the submitted sole-entry goal |

No later milestone phase clearly owns these defects. Phase 12 mentions Deliverable snapshot rendering, but does not specifically replace the mutating Source/Mart compiler paths or add mapping editability; therefore no gap is deferred.

## Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `backend/app/services/mapping/generator_context.py` | one-build orchestration, date/identity/snapshot/trace | **VERIFIED** | Substantive and wired; lines 450-535 validate actors, resolve date, build once, adapt, and emit redacted trace. |
| `backend/app/services/mapping/context_adapters.py` | bounded task-specific projections | **PARTIAL** | Three families/four projections and authority/physical policies exist; Source question filtering is defective. |
| `backend/app/services/mapping/generation_readiness.py` | task-aware deterministic readiness and stable merge | **VERIFIED** | Substantive pure policy; conflict/question/cap handling and idempotent merge are present. |
| `backend/app/services/semantic/context_collectors.py` | bounded Mart/Catalog facts through Context | **VERIFIED** | Exists, substantive, wired to Context; no stub marker reaches generation output. |
| `backend/app/services/mapping/source_to_mart_generator.py` | Context-only governed Source generation | **PARTIAL / BLOCKER** | Context path is wired, but approved/editability enforcement is missing. |
| `backend/app/services/mapping/mart_to_ybt_generator.py` | Context-only governed Mart generation | **PARTIAL / BLOCKER** | Context path is wired, but approved/editability enforcement is missing. |
| `backend/app/services/mapping/scenario_draft_generator.py` | Context-only business/technical generation | **VERIFIED** | Separate adapters/outputs, readiness, editability, fresh locks, and physical policy are wired. |
| `backend/app/api/mapping_rules.py` | compatible authorized Source/Mart APIs | **PARTIAL** | Routes and as_of remain compatible; no lifecycle block is applied before calling the services. |
| `backend/app/api/scenario_mappings.py` | compatible authorized Scenario APIs | **VERIFIED** | Direct routes perform family permission and editability checks and pass Context boundary arguments. |
| `backend/app/api/jobs.py` | authorized Scenario queued callers | **VERIFIED** | Active User recovery and family permission handoff are wired. |
| `backend/app/api/deliverables.py` | all queued/direct generation uses governed Context | **FAILED — BLOCKER** | Scenario segment is correct; Source/Mart compiler and direct compile paths are legacy and mutating. |
| `backend/app/services/deliverables/source_to_mart_compiler.py` | governed Source projection or read-only renderer | **FAILED — LEGACY MUTATOR** | Direct shared-fact queries and mapping writes. |
| `backend/app/services/deliverables/mart_to_ybt_compiler.py` | governed Mart projection or read-only renderer | **FAILED — LEGACY MUTATOR** | Direct shared-fact queries and mapping writes. |
| `backend/app/services/mapping_generator.py` | no competing legacy Mapping generator under the sole-entry goal | **FAILED — LEGACY GENERATOR** | Active `legacy_field_mapping` directly searches knowledge, SQL parse results, templates, and NL/database probe results, then writes a composite Source/Mart draft. |
| `backend/app/api/target_fields.py` | all Mapping generation routes converge on the governed Context seam | **FAILED** | `/fields/{field_id}/generate-mapping` still calls `generate_mapping_draft`. |
| Phase 10 focused test files | behavior and negative-path coverage | **PARTIAL** | Canonical paths are well covered; review blockers and warning are not. |
| `10-QUALIFICATION.md` | accurate complete qualification | **PARTIAL** | Execution ledger is useful, but complete-entry-point PASS claims are disproved by code. |

All PLAN-declared artifacts exist and pass basic substantive checks. Existence does not rescue the phase because the broken wiring and legacy data-flow are in production paths.

## Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `generator_context.py` | `context_builder.py` | one `RegulatoryContextBuilder(db).build(...)` | **WIRED** | Canonical one-build seam is real. |
| Source/Mart generators | Context adapters/runtime | distinct adapters, prompt keys, output models | **WIRED** | Task-specific paths are substantive. |
| Scenario routes/jobs/Deliverable Scenario loop | Scenario generators | authorized Project, Principal, as_of | **WIRED** | Manual inspection confirms the split business/technical adapters; PLAN regex expected a singular class name and produced a false negative. |
| Scenario generators | governance editability | before route call and after locked reload | **WIRED** | `ensure_scenario_mapping_editable` is invoked. |
| Deliverable queued Source/Mart loop | governed Source/Mart generators | expected frozen actor + Context generator call | **NOT WIRED** | Calls `compile_source_to_mart` / `compile_mart_to_ybt` instead. |
| Direct compile routes | technical mapping authority | expected technical.edit + Context/readiness/as_of | **NOT WIRED** | Calls legacy compilers after only `deliverable.generate`. |
| `/fields/{id}/generate-mapping` | RegulatoryContextBuilder/typed projections | expected sole shared-fact seam | **NOT WIRED** | Calls `mapping_generator.generate_mapping_draft`, which performs its own RAG/SQL/template/NL-task construction. |
| Source adapter | question lifecycle | expected `resolution_state == open` filter | **PARTIAL** | Filter absent in Source path, present in shared path. |

## Data-Flow Trace (Level 4)

| Artifact/path | Data source | Flow | Status |
| --- | --- | --- | --- |
| Canonical Source/Mart generation | authorized Project/task -> RegulatoryContextBuilder -> typed adapter -> runtime -> capped/merged output -> fresh task write | Real governed data with trace | **FLOWING, but lifecycle guard incomplete** |
| Canonical Scenario generation | authorized Project/task -> RegulatoryContextBuilder -> business/technical adapter -> runtime -> editability/whitelist -> fresh task write | Real governed data with trace | **FLOWING** |
| Deliverable Source compiler | unfiltered Mart/Scenario peer ORM rows -> concatenated literals -> Source mapping fields | Real data, wrong authority seam | **UNGOVERNED / FAILED** |
| Deliverable Mart compiler | Target/Mart/any upstream Source mapping ORM rows -> concatenated literals -> Mart mapping draft | Real data, wrong authority seam | **UNGOVERNED / FAILED** |
| Legacy field Mapping generator | TargetField -> knowledge search + SQL parse + template + NL/DB probe -> `LegacyFieldDraftOutput` -> `FieldMappingDraft` | Real data, competing legacy RAG/ORM seam | **UNGOVERNED / FAILED** |
| Source question projection | every `context.open_questions` item -> state-less constraint -> merge | Resolved state is lost | **INCORRECT FLOW** |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Backend source compiles | `cd backend; python -m compileall -q app` | exit 0 | **PASS** |
| Distinct four projections and approved upstream selection | exact named pytest node | passed | **PASS** |
| Stable/idempotent question merge | exact named pytest node | passed | **PASS** |
| Deliverable compilers use Context/readiness | static call/data-flow trace | compiler calls and direct ORM writes remain | **FAIL** |
| Approved double-layer row is blocked before model/write | static service trace plus test inventory | no guard and no matching behavior test | **FAIL** |
| PostgreSQL row-lock/concurrent commit semantics | unavailable live service | not executed | **SKIP / BEHAVIOR UNVERIFIED** |

The supplied broader evidence remains recorded: focused/adjacent/maximum backend qualification reached 386 passing tests with two known Windows tests deselected; the unfiltered run reached the same 386 passes and the same two known failures. Those results are useful regression evidence but do not override observable uncovered production paths.

## Probe Execution

No Phase 10 probe scripts are declared and no conventional `scripts/**/probe-*.sh` files exist. **SKIPPED (no probes).**

## Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| GEN-01 | 10-01, 10-02, 10-04 | Source-to-Mart primarily consumes RegulatoryContext while preserving API/output/instruction | **BLOCKED** | Direct generator satisfies the positive contract, but Deliverable Source compiler remains a production legacy path, approved rows remain writable, and the active composite field Mapping generator still builds Source-to-Mart rules from legacy RAG/SQL/template inputs. |
| GEN-02 | 10-01, 10-02, 10-04 | Mart-to-YBT primarily consumes RegulatoryContext and approved Source summary | **BLOCKED** | Direct generator/adaptor satisfy the positive contract, but Deliverable Mart compiler directly queries any upstream row and the active composite field Mapping generator still builds Mart-to-YBT rules outside Context. |
| GEN-03 | 10-01, 10-03, 10-04 | Scenario generators use the same Context and do not overwrite confirmed/final content | **SATISFIED** | Direct, batch, and Deliverable Scenario paths call the governed services; editability is checked before and after model work. |
| GEN-04 | 10-01..10-04 | Missing evidence yields questions; no invented table/field/formal state | **BLOCKED** | Canonical physical/question policy is strong, but compiler paths bypass governed evidence/readiness and Source adapter reopens resolved questions. |

No Phase 10 requirement is orphaned: GEN-01 through GEN-04 appear in PLAN frontmatter and REQUIREMENTS maps exactly those IDs to Phase 10.

## Prohibition Verification

| Prohibition | Verdict | Evidence |
| --- | --- | --- |
| No production fallback to former shared-fact paths | **FAILED / BLOCKER** | Deliverable compiler paths are active production legacy shared-fact constructors. |
| Generation must not overwrite human final/confirmed/approved governed content | **FAILED / BLOCKER** | Approved double-layer tasks can be regenerated and their structured draft fields changed while status remains approved. |
| Model/output path must not create unproved physical or formal state | **FAILED FOR COMPLETE ENTRY-POINT CONTRACT** | Canonical Scenario whitelist is verified; compilers use unfiltered technical/upstream rows and label outputs without Context authority/readiness. |
| No new ReportingPeriod/store/package/migration/Phase 9 Contract redesign | **VERIFIED** | Phase implementation contains no such addition. |

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| `backend/app/api/deliverables.py` | 538-556 | parallel legacy generator path | **BLOCKER** | Bypasses Context, readiness, as_of, trace, and technical permission. |
| `backend/app/services/deliverables/source_to_mart_compiler.py` | 6-20 | direct peer ORM prompt construction + write | **BLOCKER** | Unfiltered Scenario data becomes mapping draft content. |
| `backend/app/services/deliverables/mart_to_ybt_compiler.py` | 6-18 | direct ORM context construction + write | **BLOCKER** | Any upstream row is treated as evidence support. |
| `backend/app/services/mapping_generator.py` | 35-191 | active legacy RAG/SQL/template/NL-task context construction | **BLOCKER** | A production Mapping generation route remains outside RegulatoryContextBuilder. |
| `backend/app/services/mapping/source_to_mart_generator.py` | 64-182 | missing editability/status guard | **BLOCKER** | Approved mapping fields can be regenerated. |
| `backend/app/services/mapping/mart_to_ybt_generator.py` | 57-175 | missing editability/status guard | **BLOCKER** | Approved mapping fields can be regenerated. |
| `backend/app/services/mapping/context_adapters.py` | 155-168 | resolution state discarded | **WARNING** | Resolved questions can reappear as pending. |

No unreferenced `TBD`, `FIXME`, or `XXX` debt marker was found in the Phase 10 production files. Empty-list returns in `context_collectors.py` are ordinary no-result branches, not user-visible stubs.

## Human / Environment Qualification Required

After the blockers are fixed, run PostgreSQL staging concurrency qualification. Trigger concurrent direct and queued attempts while changing permission, lifecycle status, Project/task fields, and physical tuples. Confirm the production driver honors the intended no-long-lock phase followed by actor -> permission -> Project lock -> task lock -> snapshot comparison, with no stale or partially governed write.

## Gaps Summary

The primary root cause is not missing Context infrastructure; it is incomplete cutover. The canonical four generator services are real and well structured, but Deliverable still owns a parallel legacy Source/Mart compilation chain, and the active composite field Mapping endpoint still owns a second legacy RAG/SQL/template construction chain. Those paths defeat the phase's sole-entry, temporal, provenance, readiness, authorization, and no-fallback claims. Independently, double-layer generators do not protect approved tasks, and Source question projection loses resolution state.

The gaps are not explicitly assigned to a later roadmap phase and therefore block progression. Fix the production paths and add the exact negative tests identified above, then rerun Phase 10 qualification and verification.

---

_Verified: 2026-08-23T12:14:21Z_  
_Verifier: the agent (gsd-verifier)_
