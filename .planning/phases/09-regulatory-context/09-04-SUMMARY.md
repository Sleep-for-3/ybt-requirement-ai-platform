---
phase: 09-regulatory-context
plan: 04
subsystem: api
tags: [fastapi, pydantic, sqlalchemy, alembic, postgresql, sqlite, regulatory-context]

requires:
  - phase: 09-regulatory-context/09-01
    provides: governed semantic versions, shared lifecycle policy, and temporal conflict mapping
  - phase: 09-regulatory-context/09-02
    provides: canonical RegulatoryContext request/response and authority/state contracts
  - phase: 09-regulatory-context/09-03
    provides: project-authorized RegulatoryContextBuilder and batched collectors
provides:
  - secured read-only GET /api/projects/{project_id}/regulatory-context endpoint
  - HTTP isolation, lifecycle, temporal, provenance, gap, bounds, and N+1 regression coverage
  - SQLite lifecycle and direct PostgreSQL-dialect revision 016 qualification
affects: [regulatory-context consumers, semantic APIs, database migration release gates]

actuals:
  tokens: 14138
  tasks: 3
  commits: 4

tech-stack:
  added: []
  patterns:
    - authorize Project before constructing the canonical RegulatoryContextRequest
    - compile a single Alembic revision through offline PostgreSQL Operations
    - classify full-suite failures by stable test identity and exception signature

key-files:
  created:
    - backend/app/api/regulatory_context.py
    - backend/tests/test_regulatory_context_api.py
    - .planning/phases/09-regulatory-context/09-04-POSTGRES-QUALIFICATION.md
  modified:
    - backend/app/main.py
    - backend/tests/test_semantic_migration.py

key-decisions:
  - "The endpoint performs the locked PermissionService -> RegulatoryContextBuilder handoff and derives institution scope only from the authorized Project."
  - "candidate_limit is exposed as the canonical contract's bounded 1..100 query input so HTTP candidate and retrieval work stays bounded."
  - "Existing semantic.py mode propagation was retained unchanged because live code and Phase 8 regression tests already implement the shared trusted/candidate policy."
  - "PostgreSQL live execution remains a release gate because localhost did not answer; only direct revision 016 dialect compilation is qualified locally."

patterns-established:
  - "RegulatoryContext HTTP boundary: project.view first, strict request construction second, canonical builder third."
  - "Migration qualification separates SQLite runtime, direct PostgreSQL offline compilation, historical-chain limitations, and unavailable live staging."

requirements-completed: []

coverage:
  - id: D1
    description: "Authorized callers receive the canonical project/institution-scoped RegulatoryContext over a bounded read/debug API."
    requirement: CTX-01
    verification:
      - kind: integration
        ref: "backend/tests/test_regulatory_context_api.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Trusted/candidate lifecycle, temporal versions, provenance, deterministic gaps, confidentiality, and fixed query cost survive HTTP serialization."
    requirement: CTX-02
    verification:
      - kind: integration
        ref: "python -m pytest -q tests/test_regulatory_context_api.py tests/test_semantic_layer.py -x"
        status: pass
      - kind: integration
        ref: "backend/tests/test_regulatory_context_api.py#test_candidate_limit_and_http_query_budget_do_not_grow_with_rows"
        status: pass
    human_judgment: false
  - id: D3
    description: "Semantic revision 016 is qualified on SQLite and direct PostgreSQL dialect compilation with live staging limits made explicit."
    requirement: CTX-03
    verification:
      - kind: integration
        ref: "backend/tests/test_semantic_migration.py#test_revision_016_compiles_portable_postgresql_upgrade_and_downgrade_sql"
        status: pass
      - kind: manual_procedural
        ref: ".planning/phases/09-regulatory-context/09-04-POSTGRES-QUALIFICATION.md"
        status: pass
    human_judgment: false
  - id: D4
    description: "Phase 8 semantic, knowledge, governance, lineage, and full backend behavior retain their prior failure baseline."
    requirement: CTX-04
    verification:
      - kind: integration
        ref: "python -m pytest -q"
        status: fail
    human_judgment: true
    rationale: "The command exits 1 on the same two documented Windows baseline failures; the Phase 9 verifier must confirm the identity/signature classification."

duration: 35min
completed: 2026-08-23
status: complete
---

# Phase 9 Plan 4: Regulatory Context API and Qualification Summary

**A secured canonical RegulatoryContext endpoint with 22-statement fixed-cost HTTP coverage and honest SQLite/PostgreSQL migration qualification**

## Performance

- **Duration:** 35 min
- **Started:** 2026-08-22T18:05:46Z
- **Completed:** 2026-08-22T18:40:27Z
- **Tasks:** 3
- **Delivery files modified:** 5

## Accomplishments

- Added `GET /api/projects/{project_id}/regulatory-context` behind the shared resource guard and an explicit `project.view` permission check, using the sole canonical request/response DTO and locked authorized-Project builder handoff.
- Qualified every optional scope field, bounds, two-institution isolation, confidential knowledge omission, trusted/candidate lifecycle, inclusive 2026/2027 versions, temporal 409s, deterministic gaps/conflicts, empty projects, long text, 30-item evidence payloads, RetrievalLog provenance, and authoritative-fact immutability over HTTP.
- Locked the HTTP query budget at 22 statements before and after growth from 5 to 65 source candidates and from 2 to 42 knowledge units, proving no row-count-driven N+1 regression.
- Added direct PostgreSQL-dialect upgrade/downgrade compilation for revision 016 while retaining full SQLite lifecycle/bootstrap/index coverage and documenting the unavailable live PostgreSQL gate.
- Ran the complete backend regression and classified the same two Windows-only baseline failures without hiding or rewriting them.

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: RegulatoryContext API tracer contract** — `7899a6f` (test)
2. **Task 1 GREEN: secured canonical API endpoint** — `c81c878` (feat)
3. **Task 2: isolation, temporal, lifecycle, gap, and performance qualification** — `9ba6cf6` (test)
4. **Task 3: SQLite/PostgreSQL migration portability qualification** — `40d1300` (test/docs)

**Plan metadata:** committed separately after state and roadmap updates.

## Files Created/Modified

- `backend/app/api/regulatory_context.py` — bounded read/debug endpoint with explicit permission and canonical builder handoff.
- `backend/app/main.py` — registers the new router behind `guard_project_resource`.
- `backend/tests/test_regulatory_context_api.py` — 13 HTTP integration tests covering authorization, isolation, lifecycle, time, provenance, gaps, payload bounds, and query count.
- `backend/tests/test_semantic_migration.py` — direct offline PostgreSQL compilation assertions for revision 016.
- `.planning/phases/09-regulatory-context/09-04-POSTGRES-QUALIFICATION.md` — reproducible evidence, baseline classification, and live staging checklist.

## Verification Evidence

| Scope | Result |
| --- | --- |
| API + Phase 8 semantic routes | 30 passed in 28.33s |
| Context contract/builder/API + semantic + migration | 89 passed, 4 pre-existing SQLite datetime-adapter warnings |
| Hybrid retrieval + knowledge + governance + lineage | 86 passed in 26.54s |
| SQLite concurrent confirmed interval | 1 passed in 19.36s |
| Migration-focused SQLite/PostgreSQL offline | 4 passed, 4 warnings in 26.79s |
| Full backend at final reviewed HEAD | 337 passed, 2 pre-existing failures, 5 warnings in 220.19s |
| `python -m compileall -q app` | PASS, exit 0 |

The two full-suite failures are unchanged from Phase 8 and 09-01:

- `test_windows_secret_acl_commands_remove_explicit_extra_access_and_are_idempotent`: Windows reports ACL `Protected=None` instead of `True`.
- `test_windows_lifecycle_script_without_action_keeps_control_console_open`: the interactive `项目启停.ps1` process does not exit within the test's 10-second timeout.

No new Phase 9 failure was observed. Phase 8 delivered 255 passing tests with these same two failures; the final reviewed Phase 9 suite has 337 passing tests with the same failure identities and signatures, for 82 additional passing tests.

## PostgreSQL Qualification

- Alembic head is `202608200016`.
- Revision 016 directly compiles for PostgreSQL in both directions with three FKs, the effective-date CHECK, named indexes, and no SQLite-only SQL.
- SQLite empty/head, downgrade/up, populated 015 bootstrap, index preservation, and serialized overlap behavior pass.
- The historical full-chain `--sql` command still stops at `202607070002` because that legacy migration inspects an offline `MockConnection`; this limitation remains explicit.
- Local live PostgreSQL was unavailable: executables exist, but no service/listener answered `127.0.0.1:5432`, no PostgreSQL environment configuration was present, and the application resolved to SQLite.
- Live PostgreSQL upgrade/downgrade, constraints, `SELECT FOR UPDATE` concurrency, isolation, confidentiality, query budget, and response compatibility remain the staging checklist in the qualification document.

## Decisions Made

- Kept the existing `RegulatoryContext` schema and authority mapping as the only public contract; no second DTO or fact store was introduced.
- Mapped builder scope `ValueError` failures to stable HTTP 400 responses, retained PermissionService's 403/404 behavior, and allowed existing temporal `HTTPException` 409 payloads to pass through unchanged.
- Included `candidate_limit` at the API boundary because it is part of the locked request contract and is necessary for the denial-of-service/query-budget mitigation.
- Did not edit `semantic.py`: all graph/path/entity/resolver routes already pass explicit trusted/candidate mode into the shared policy, and the full Phase 8 route matrix passed.
- Treated RetrievalLog persistence as the sole allowed write side effect; authoritative Semantic/Mapping/Lineage/Knowledge snapshot fields remain unchanged in HTTP tests.

## Deviations from Plan

### Consistency Adjustments

**1. `semantic.py` required no code change**
- **Found during:** Task 2
- **Reason:** The live 09-01 implementation already propagates explicit mode through graph, path, entity semantics, and resolver calls.
- **Action:** Added regression coverage and ran the complete semantic route suite instead of creating a redundant edit.
- **Impact:** No API path, response model, or production behavior changed beyond the new RegulatoryContext endpoint.

No Rule 1–3 production auto-fixes were required, and no architectural deviation occurred.

### Auto-fixed Planning State

**2. [Rule 1 - State accounting] Restored the milestone phase total after SDK recalculation**
- **Found during:** Plan metadata update
- **Issue:** `state.update-progress` derived `total_phases: 2` from the currently listed roadmap sections, overwriting the orchestrator-owned milestone value `8`, and retained stale “09-04 next” prose.
- **Fix:** Restored `total_phases: 8`, kept only Phase 8 in `completed_phases`, and set Phase 09 to 4/4 plans executed while awaiting verification.
- **Files modified:** `.planning/STATE.md`, `.planning/ROADMAP.md`
- **Verification:** Phase 09 remains incomplete, requirements remain unchecked, and no Phase 10 state was entered.

## TDD Gate Compliance

- Task 1 has a failing RED commit (`7899a6f`, missing API module) followed by the GREEN implementation commit (`c81c878`).
- Task 2's expanded tests were immediately green after correcting test-fixture expectations. Investigation confirmed that the shared Phase 8/09-03 implementation already supplied the required lifecycle, isolation, temporal, and provenance behavior once Task 1 exposed it; no artificial production change was made.
- Task 3 was a qualification task rather than a behavior-adding TDD task.

## Issues Encountered

- Context7 library lookup reached the configured monthly quota, and the `ctx7` CLI fallback was not installed. Existing repository patterns and the passing local framework tests were used; no dependency was installed.
- Live PostgreSQL was unavailable. The result is recorded as unavailable, not passed, with a mandatory staging checklist.
- Full-chain PostgreSQL offline generation is blocked by the pre-existing `202607070002` MockConnection inspection; direct revision 016 compilation provides bounded dialect evidence without masking that limitation.

## Authentication Gates

None.

## Known Stubs

None. Stub-pattern matches were limited to intentional empty-list/dict test assertions, optional query defaults, and the qualification statement that live PostgreSQL was unavailable.

## User Setup Required

None for local plan completion. A release operator must provide an isolated live PostgreSQL staging database and execute the qualification checklist before production deployment.

## Next Phase Readiness

- Plan 09-04 is implemented and qualified; the Phase 9 orchestrator can now create `09-VERIFICATION.md` and make the final requirement/status decision.
- CTX-01 through CTX-04 intentionally remain unchecked until that final verification passes.
- No frontend, generator, Phase 10, cache, graph database, package, or external-service code was changed.

## Self-Check: PASSED

- All five delivery/qualification files and this summary exist.
- Commits `7899a6f`, `c81c878`, `9ba6cf6`, and `40d1300` are present in history.
- Router registration, endpoint symbol, 22-statement budget assertion, and PostgreSQL dialect test are present.
- No tracked file deletion occurred in the plan commits.

---
*Phase: 09-regulatory-context*
*Completed: 2026-08-23*
