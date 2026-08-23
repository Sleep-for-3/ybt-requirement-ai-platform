---
phase: 10-generator-refactor
plan: 03
subsystem: ai-generation
tags: [regulatory-context, scenario-mapping, authorization, queued-jobs, deliverables, physical-whitelist, tdd]

requires:
  - phase: 10-generator-refactor/10-01
    provides: frozen Principal validation, task/Project snapshots, typed Context adapters, readiness policy, question merge, confidence caps, and bounded trace helpers
  - phase: 10-generator-refactor/10-02
    provides: proven no-long-lock generator protocol with fresh actor/permission checks, fixed Project-to-task locks, and Context-only shared-fact consumption
  - phase: 09-regulatory-context
    provides: authorized temporal RegulatoryContext, provenance, conflicts, governed questions, and confidentiality controls
provides:
  - Context-only Scenario business and technical generators with distinct prompts, structured outputs, renderers, and task-local snapshots
  - exact Context/current-value physical tuple allow-listing that refuses hallucinated source identifiers without discarding safe processing output
  - direct-route exact Principal handoff plus active-persisted-User recovery for batch and Deliverable queued callers
  - fresh post-model actor and permission reauthorization, fixed Project-to-task locks, stale rejection, bounded blocked accounting, and AI-draft-only mutation
affects: [10-04 generator qualification, Scenario mapping APIs, background jobs, Deliverable generation]

actuals:
  tokens: 29642
  tasks: 3
  commits: 8

tech-stack:
  added: []
  patterns:
    - share one authorized RegulatoryContext seam while retaining task-family-specific projections, prompts, outputs, and renderers
    - recover queued authority only from an active persisted User and never infer legacy from a missing or falsey identity
    - build Context and call the model without row locks, then reauthorize and lock Project before task in a fresh write transaction
    - classify queued identity, permission, readiness, governance, and stale outcomes with bounded blocked codes rather than content-bearing errors

key-files:
  created: []
  modified:
    - backend/app/services/mapping/scenario_draft_generator.py
    - backend/app/api/scenario_mappings.py
    - backend/app/api/jobs.py
    - backend/app/api/deliverables.py
    - backend/tests/test_scenario_traceability.py
    - backend/tests/test_governance.py
    - backend/tests/test_deliverables.py

key-decisions:
  - "Scenario business and technical generation share only the authorized RegulatoryContext seam; each keeps its own local snapshot, prompt key, structured output, renderer, audit fields, and apply policy."
  - "Queued work reconstructs authority only as Principal(user.id, user.username, user.display_name, False) from an existing active User; None, zero, missing, disabled, and revoked identities fail closed and never become legacy."
  - "Context/model work holds no row lock; a fresh transaction validates the actor, repeats PermissionService authorization, locks Project then task, and compares the complete task-local snapshot before any draft write."
  - "Technical physical identifiers are persisted only when the exact proposed tuple is already current or appears in the same governed Context projection; rejected tuples add a stable question while safe non-physical output may remain eligible."
  - "Queued failures use bounded blocked/failed result codes and per-item commits so one blocked Scenario cannot create a draft, success audit, sensitive diagnostic, or rollback of resumable queue state."

patterns-established:
  - "Scenario optimistic write boundary: Context projection -> model attempt -> expire_all -> fresh actor -> PermissionService -> Project FOR UPDATE -> task FOR UPDATE -> snapshot compare -> policy/apply/audit."
  - "Queued identity boundary: created_by must be a positive id resolving to an active User; reconstructed Principal is always explicitly non-legacy."
  - "Physical-source safety: exact four-part source tuple allow-list from Context/current state, with stable question merge and confidence cap for refused proposals."

requirements-completed: [GEN-03, GEN-04]

coverage:
  - id: D1
    description: "Scenario business generation uses one authorized Context projection, preserves its distinct API/prompt/output contract, and mutates only AI draft fields after fresh authorization and snapshot validation."
    requirement: GEN-03
    verification:
      - kind: integration
        ref: "backend/tests/test_scenario_traceability.py#business Context, final-content, questions, concurrency, and actor tests"
        status: pass
      - kind: integration
        ref: "python -m pytest -q tests/test_generator_context_adapters.py tests/test_scenario_traceability.py -x"
        status: pass
    human_judgment: false
  - id: D2
    description: "Scenario technical generation keeps its task-specific output and renderer while accepting only exact governed physical tuples and preserving safe non-physical processing output."
    requirement: GEN-04
    verification:
      - kind: integration
        ref: "backend/tests/test_scenario_traceability.py#technical Context, physical allow-list, confidence, and stale tests"
        status: pass
      - kind: unit
        ref: "backend/tests/test_generator_context_adapters.py#Scenario business/technical projection separation"
        status: pass
    human_judgment: false
  - id: D3
    description: "Batch and Deliverable callers recover only active persisted users, pass explicit Project/Principal/date scope, isolate each item, and report bounded blocked outcomes without draft or success audit."
    requirement: GEN-03
    verification:
      - kind: integration
        ref: "backend/tests/test_scenario_traceability.py#batch, background, queued, and deliverable caller tests"
        status: pass
      - kind: integration
        ref: "backend/tests/test_deliverables.py#test_template_version_render_history_reuse_and_delivery_lifecycle"
        status: pass
    human_judgment: false
  - id: D4
    description: "Direct and queued generation rejects disabled users, revoked permissions, stale concurrent changes, governance blocks, and Context/runtime failures before human-final, confirmed, physical, or draft mutation."
    requirement: GEN-04
    verification:
      - kind: integration
        ref: "backend/tests/test_scenario_traceability.py#actor disablement, membership revocation, stale barrier, audit privacy, and no-fallback tests"
        status: pass
    human_judgment: false

duration: 1h 22m
completed: 2026-08-23
status: complete
---

# Phase 10 Plan 3: Scenario Generator and Caller Cutover Summary

**Scenario business and technical drafts now flow through one governed RegulatoryContext seam across direct, batch, and Deliverable entry points, with task-distinct outputs, exact physical-source allow-listing, frozen authority, and fresh optimistic writes that preserve every human-final field.**

## Performance

- **Duration:** 1h 22m
- **Started:** 2026-08-23T08:32:50Z
- **Completed:** 2026-08-23T09:55:04Z
- **Tasks:** 3
- **Delivery files modified:** 7

## Accomplishments

- Replaced Scenario business and technical generator-side Target/Scenario/peer/evidence/RAG/catalog shared-fact reads with one authorized `RegulatoryContextBuilder` result and separate `ScenarioContextAdapter` projections.
- Preserved `scenario_business_mapping` versus `scenario_technical_lineage` prompt keys, structured outputs, renderers, response schemas, optional `as_of`, editability rules, explicit adoption, human `final_content`, confirmation state, and AI-draft-only mutation.
- Added exact technical physical tuple validation from current values or same-task governed Context; unproved database/schema/table/column proposals remain unchanged, add a deterministic merged question, and cannot promote formal governance state.
- Moved every direct Scenario route, batch job, and Deliverable queued generator call to the explicit authorized Project/frozen Principal/date signature with no legacy overload or fallback.
- Made queued identities fail closed unless `created_by` resolves to an active persisted User, and repeated actor plus business/technical permission validation after model return before Project-to-task locks.
- Isolated queued item transactions and added stable `blocked_count`/bounded reason codes so identity loss, permission revocation, readiness, governance, stale output, or runtime failure writes neither draft nor success audit and does not erase resumable work items.

## Task Commits

Each TDD task was committed atomically:

1. **Task 1 RED: Scenario business Context contracts** — `6e55197` (test)
2. **Task 1 RED refinement: generator-local no-fallback boundary** — `3656c3a` (test)
3. **Task 1 GREEN: governed Scenario business cutover** — `653ecb7` (feat)
4. **Task 2 RED: Scenario technical Context and physical-safety contracts** — `d6f25b5` (test)
5. **Task 2 GREEN: governed Scenario technical generation** — `d42ca7f` (feat)
6. **Task 3 RED: queued Scenario caller contracts** — `c0c11f7` (test)
7. **Task 3 GREEN: batch and Deliverable caller migration** — `f2b41d0` (feat)
8. **Task 3 fixture compatibility: authenticated Deliverable lifecycle queue** — `efd7fd7` (test)

**Plan metadata:** committed separately before the sequential STATE/ROADMAP progress update.

## Files Created/Modified

- `backend/app/services/mapping/scenario_draft_generator.py` — Context-only business/technical generation, distinct task projections/output policies, exact physical tuple safety, attempt persistence, fresh authorization/locking, and atomic AI-draft apply.
- `backend/app/api/scenario_mappings.py` — unchanged response contracts with exact current-request Principal, authorized Project, optional `as_of`, editability checks, and bounded generation errors.
- `backend/app/api/jobs.py` — active persisted queue-actor recovery, per-family permission checks, explicit generator handoff, per-item rollback/reload, cancellation/resume preservation, and additive blocked accounting.
- `backend/app/api/deliverables.py` — package/job scope validation, active actor recovery, governed-content skips, per-generator permission checks, isolated field-item outcomes, bounded diagnostics, and non-success audit classification for blocked packages.
- `backend/tests/test_scenario_traceability.py` — direct and queued Context, physical allow-list, confidentiality, final-content, concurrency, actor/permission revocation, error privacy, and compatibility coverage.
- `backend/tests/test_governance.py` — cancellation fixture upgraded to a persisted active queue actor and membership so it exercises the new secure queued boundary.
- `backend/tests/test_deliverables.py` — lifecycle fixture upgraded to an exact active Principal/project membership while retaining production rejection of legacy/zero queue identities.

## Verification Evidence

| Scope | Result |
| --- | --- |
| Task 1 tracer selection | 5 passed, 3 deselected in 81.34s; user approved tracer gate |
| Full Scenario traceability after Task 1 | 8 passed in 69.91s |
| Task 2 technical selection | 5 passed, 8 deselected in 53.09s |
| Full Scenario traceability after Task 2 | 13 passed in 111.10s |
| Task 3 queued selection | 8 passed, 13 deselected in 66.67s |
| Existing cancellation regression | 1 passed, 29 deselected in 2.40s |
| Context adapters + full Scenario plan verification | 30 passed in 224.28s |
| Complete Deliverable test file after secure fixture update | 10 passed in 7.56s |
| LLM/governance/Deliverable/productization group excluding two existing Windows-host failures | 75 passed, 2 deselected in 34.39s |
| `python -m compileall -q app` | PASS, exit 0 |
| Production forbidden-import/helper and caller static review | PASS |

The exact second plan command was also run without exclusions. It reached 66 passing tests before the existing Windows ACL assertion failed; the ACL case failed again in isolation. After deselecting only that case, the same group again reached 66 passing tests before the existing interactive lifecycle-script timeout failed. Neither failing file was changed from the 10-03 starting commit; both are recorded in `deferred-items.md` rather than being modified outside this plan.

## Decisions Made

- Kept `RegulatoryContextBuilder` as the only production shared-fact authority. Scenario generators read only their own task row and authorized Project at the optimistic write boundary; they do not query catalog, evidence, retrieval, lineage, peer Scenario, or other ORM prompt facts.
- Passed direct `CurrentPrincipal` values byte-for-byte and reconstructed queued authority only from an existing active User as an explicitly non-legacy frozen `Principal`. A missing, zero, disabled, or revoked identity cannot inherit development legacy authority.
- Used one no-lock Context/model attempt followed by a fresh transaction whose order is actor validation, `PermissionService` authorization, Project lock, task lock, and full local snapshot comparison.
- Applied model output only to allowed AI-draft/task-local fields. Human `final_content`, confirmed status, formal governance state, and explicit adoption/review authority remain outside model control.
- Treated physical-source tuples as indivisible exact identifiers. Context proof is required for a changed tuple; safe processing logic can survive a refused tuple only when readiness policy permits it.
- Classified expected queued security/governance/readiness/stale outcomes as bounded blocked items, not success and not content-bearing retry errors.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Preserved Deliverable field work items across per-generator rollback**
- **Found during:** Task 3 queued/Deliverable verification
- **Issue:** A generator failure could roll back newly created `DeliverableFieldItem` rows, leaving no stable item to mark blocked/failed and breaking resumability.
- **Fix:** Committed the ensured work-item set before per-generator execution, then reloaded package/job/item after an isolated rollback and recorded one bounded outcome.
- **Files modified:** `backend/app/api/deliverables.py`
- **Verification:** Task 3 queued selection passed 8 tests; the complete Deliverable file passed 10 tests.
- **Committed in:** `f2b41d0`

**2. [Rule 3 - Blocking] Updated the existing governance cancellation fixture to the secure queued identity contract**
- **Found during:** Task 3 cancellation regression
- **Issue:** The old fixture queued a legacy/zero creator, which must now be rejected and therefore could no longer reach the cancellation behavior it intended to test.
- **Fix:** Added a persisted active User and active project membership to the fixture without weakening production fail-closed behavior.
- **Files modified:** `backend/tests/test_governance.py`
- **Verification:** The targeted cancellation test passed (`1 passed, 29 deselected`).
- **Committed in:** `f2b41d0`

**3. [Rule 3 - Blocking] Updated the existing Deliverable lifecycle fixture to an exact persisted Principal**
- **Found during:** plan-level LLM/governance/Deliverable/productization regression
- **Issue:** The lifecycle test still invoked queued generation through optional-auth legacy mode, producing `created_by=0`; the new handler correctly blocked it before synchronizing evidence rows.
- **Fix:** Created an active persisted User with active `project_manager` membership and overrode the request dependency with its exact non-legacy Principal for queued generation and subsequent lifecycle operations.
- **Files modified:** `backend/tests/test_deliverables.py`
- **Verification:** The failing case passed in isolation and `tests/test_deliverables.py` passed all 10 tests.
- **Committed in:** `efd7fd7`

---

**Total deviations:** 3 auto-fixed (1 bug, 2 blocking fixture updates)
**Impact on plan:** All changes were required to preserve resumable queue correctness and verify the planned fail-closed identity boundary; no production legacy fallback or scope expansion was introduced.

## TDD Gate Compliance

- Task 1 RED commits `6e55197` and `3656c3a` established the missing business Context/route/no-fallback contracts; GREEN `653ecb7` passed the tracer selection, and the user approved the tracer checkpoint before expansion.
- Task 2 RED `d6f25b5` established the missing technical Context and exact physical-source safety contracts; GREEN `d42ca7f` passed the technical selection and full Scenario suite.
- Task 3 RED `c0c11f7` established missing active-user recovery, bounded blocked accounting, and queued caller handoff contracts; GREEN `f2b41d0` plus fixture commit `efd7fd7` passed queued, cancellation, and Deliverable regressions.

## Issues Encountered

- The required productization regression group contains two Windows-host-specific failures unrelated to Plan 10-03: `Get-Acl` reports a null protection flag after successful `icacls`, and the interactive lifecycle script does not exit within its 10-second test timeout after input `0`. Both were reproduced, left unmodified, and logged in `deferred-items.md`; the other 75 tests in that group pass.
- `python -m ruff` was unavailable in the existing environment. No package was installed; the plan's required pytest, compile, and static checks were used.

## Authentication Gates

None. The interactive tracer verification checkpoint was approved after its production slice and selected tests passed.

## Known Stubs

None. Modified production/test files contain no TODO/FIXME/placeholder or skipped-test markers, and no legacy generator fallback remains.

## User Setup Required

None.

## Remaining Risks / Next Phase Readiness

- The exact second plan verification command is not fully green on this Windows host because of the two pre-existing productization failures documented above. This is an explicit qualification risk, not a Scenario generator regression; all remaining 75 tests pass when only those two cases are deselected.
- SQLite coverage proves no long-held row lock, stale snapshot rejection, per-item isolation, and atomic task mutation. Real PostgreSQL lock/isolation and query-growth qualification remain Plan 10-04 work and were intentionally not performed early.
- Existing unrelated frontend working-tree changes and untracked learning/demo/runtime assets remain untouched and uncommitted.

## Self-Check: PASSED

- All seven delivery files, this summary, and the Phase 10 deferred-items record exist on disk.
- Commits `6e55197`, `3656c3a`, `653ecb7`, `d6f25b5`, `d42ca7f`, `c0c11f7`, `f2b41d0`, and `efd7fd7` are present in history.
- Frontmatter includes `status: complete`, exact requirements `[GEN-03, GEN-04]`, and realized diff-scale actuals.
- No task commit deleted a tracked file or absorbed unrelated frontend/untracked material.

---
*Phase: 10-generator-refactor*
*Completed: 2026-08-23*
