---
phase: 10-generator-refactor
plan: 08
qualified_at: 2026-08-24
status: qualified-with-known-baselines
requirements: [GEN-01, GEN-02, GEN-03, GEN-04]
backend_runtime: SQLite
postgresql_live: unavailable
---

# Phase 10 Generator Refactor Qualification

## Qualification Verdict

**QUALIFIED after gap closure, with two exact pre-existing Windows baselines and live PostgreSQL concurrency explicitly UNVERIFIED.**

The earlier verification correctly found three production gaps: Deliverable Source/Mart compilers bypassed Context (`CR-01`), approved double-layer rows remained writable (`CR-02`), and resolved Source questions could reopen (`WR-01`). Gap plans 10-05 through 10-07 closed those paths. This record uses only post-fix executed evidence for completion; `10-VERIFICATION.md` retains the original gap history.

## Reproducible Execution Record

All timestamps are UTC on 2026-08-24. No collect-only result is behavioral evidence.

| Gate | Exact command | Start UTC | End UTC | Exit | Result |
| --- | --- | --- | --- | ---: | --- |
| Compile | `cd backend; python -m compileall -q app` | 13:39:15 | 13:39:15 | 0 | PASS |
| Focused gap matrix | `cd backend; python -m pytest -q tests/test_generator_context_adapters.py tests/test_double_layer_mapping.py tests/test_deliverables.py tests/test_scenario_traceability.py tests/test_legacy_mapping_retirement.py -x` | 13:39:15 | 13:46:35 | 0 | **79 passed** in 435.94s |
| Adjacent Phase 9/runtime/governance/retrieval | `cd backend; python -m pytest -q tests/test_regulatory_context_api.py tests/test_regulatory_context_contract.py tests/test_regulatory_context_builder.py tests/test_semantic_layer.py tests/test_llm_runtime.py tests/test_governance.py tests/test_knowledge_rag.py tests/test_hybrid_retriever.py tests/test_semantic_retrieval_security.py tests/test_deliverables.py -x` | 13:47:02 | 13:48:13 | 0 | **176 passed** in 65.89s |
| Unfiltered Backend Run | `cd backend; python -m pytest -q` | 13:48:52 | 13:59:53 | 1 | **404 passed, 2 failed, 5 warnings** in 656.17s; only exact Windows baselines |
| Maximum Backend Run | `cd backend; python -m pytest -q --deselect=tests/test_productization.py::test_windows_secret_acl_commands_remove_explicit_extra_access_and_are_idempotent --deselect=tests/test_productization.py::test_windows_lifecycle_script_without_action_keeps_control_console_open` | 14:00:18 | 14:11:13 | 0 | **404 passed, 2 deselected, 5 warnings** in 649.49s |

The focused suite enters real direct Source/Mart generation, direct compile, Deliverable queued Source/Mart rows, Scenario direct/queued callers, approved/final/review lifecycle gates, permission revocation, stale snapshots, open/resolved questions, and the retired legacy route.

## Exact Baselines

| Node | Observed signature | Classification |
| --- | --- | --- |
| `tests/test_productization.py::test_windows_secret_acl_commands_remove_explicit_extra_access_and_are_idempotent` | `acl["Protected"]` is `None`, expected `True` | Exact pre-existing Windows ACL baseline in `.planning/WINDOWS.md` |
| `tests/test_productization.py::test_windows_lifecycle_script_without_action_keeps_control_console_open` | `subprocess.TimeoutExpired` after 10 seconds waiting for `项目启停.ps1` | Exact pre-existing Windows console baseline in `.planning/WINDOWS.md` |

No other failure occurred and no broader file, class, or keyword was deselected. The five warnings are the existing temporary development `APP_SECRET_KEY` warning and four Python 3.12 SQLite datetime-adapter deprecations.

## Production Entry-Point Audit

| Entry point | Governed contract | Executed evidence | Verdict |
| --- | --- | --- | --- |
| Source-to-Mart generate-draft | exact Principal + `technical.edit` Project + one candidate Context + Source adapter/readiness + fresh lifecycle/snapshot write | double-layer route/service/lifecycle/race tests | PASS |
| Mart-to-YBT generate-draft | same boundary with distinct Mart adapter/output and approved upstream Context facts | double-layer route/service/lifecycle/race tests | PASS |
| Scenario business/technical direct and batch | distinct adapters/outputs, active queued User, task permission, fresh snapshot | Scenario traceability matrix | PASS |
| Direct Source/Mart compile | optional `as_of`, exact Principal, `technical.edit` Project, canonical generator, four compatibility keys | `test_direct_source_and_mart_compile_use_governed_generators_and_keep_response_keys` | PASS |
| Deliverable queued Source/Mart | real rows enter per-item runner; active non-legacy Principal; fresh `technical.edit`; bounded item result | queued context and permission-revocation tests | PASS |
| Legacy `/fields/{id}/generate-mapping` | resource resolution and `technical.edit`, then stable HTTP 410; zero model/fact/write work | `test_legacy_mapping_retirement.py` | RETIRED / PASS |
| Historical FieldMappingDraft read/review | records remain readable/reviewable; no schema/data removal | retirement compatibility test | PASS |

## Gap Closure Evidence

| Finding | Fix | Post-fix evidence | Result |
| --- | --- | --- | --- |
| `CR-01` Deliverable compiler bypass | Deleted both compilers; direct and queued callers use governed Source/Mart generators and per-item `technical.edit` | direct HTTP/function, real queued row, permission-revocation, and static import/call tests | CLOSED |
| `CR-02` approved rows writable | Shared editability policy runs before Context/model and after reauthorization on fresh Project-to-task locks | approved/final/review-locked pre-model and governance-race tests for Source/Mart | CLOSED |
| `WR-01` resolved questions reopen | Source adapter filters `resolution_state == "open"` before sort/cap/projection | mixed-state and resolved-only prompt/merge/trace/readiness tests | CLOSED |
| Competing composite field generator | Authorized 410 facade; deleted `mapping_generator.py` and orphaned prompt key | zero-call/zero-mutation and production reference scan | CLOSED |

## GEN Requirement Evidence

| Requirement | Verdict | Evidence |
| --- | --- | --- |
| GEN-01 | PASS | Source direct, compile, and Deliverable paths use the Source adapter and sole Context seam; lifecycle/permission/stale failures write no draft; response contracts remain compatible. |
| GEN-02 | PASS | Mart direct, compile, and queued paths use the distinct Mart projection; approved upstream information remains attempt-frozen Context data; no compiler peer query remains. |
| GEN-03 | PASS | Scenario business/technical direct, batch, and Deliverable paths retain distinct prompts/outputs and preserve confirmed/final content under success and failure. |
| GEN-04 | PASS | Sparse/missing evidence yields questions and confidence caps; unknown physical/formal state is not persisted; resolved questions remain closed; the legacy constructor is gone. |

## D-01 Through D-22

| Decision | Verdict | Concrete post-fix evidence |
| --- | --- | --- |
| D-01 sole shared-fact seam | PASS | Canonical generators and compile/queued callers delegate to one Context build per attempt; competing services are deleted/retired. |
| D-02 fail closed | PASS | Builder, identity, permission, readiness, lifecycle, stale, and runtime failures have bounded diagnostics and no fallback/draft. |
| D-03 incomplete Context is business state | PASS | Missing evidence/lineage remains questions and confidence caps rather than legacy lookup. |
| D-04 task-local state allowed | PASS | Current mapping rows, lifecycle state, audit, queue state, and writes remain task-local. |
| D-05 zero production fallback | PASS | Legacy files/imports/calls are absent; runtime sentinels prove zero invocation. |
| D-06 optional `as_of` | PASS | Existing calls may omit it; direct compile HTTP passes explicit 2026-06-30. |
| D-07 date priority | PASS | Existing explicit-then-business-date resolver regressions pass. |
| D-08 no new period store | PASS | No model/schema/migration/ReportingPeriod addition. |
| D-09 temporal trace | PASS | Canonical Context/audit metadata retains the resolved date; facades add no second trace. |
| D-10 task-specific adapters | PASS | Source, Mart, Scenario business, and Scenario technical projections remain distinct. |
| D-11 bounded projection | PASS | Authority order, caps, open-only filtering, provenance, and zero adapter SQL tests pass. |
| D-12 no full Context dump | PASS | Prompt/audit privacy passes; compatibility responses contain four bounded fields. |
| D-13 task-specific output | PASS | Four prompt keys/output schemas remain; no universal generator. |
| D-14 typed readiness | PASS | Compile/queued callers reuse generator readiness; legacy evidence inference is deleted. |
| D-15 conservative gaps | PASS | Stable questions/confidence caps remain; no hidden fact query fills gaps. |
| D-16 own mapping gap | PASS | Task-owned missing mapping remains work to generate, not a generic blocker. |
| D-17 blockers | PASS | Core conflict, scope, permission, lifecycle, governance, and stale tests fail closed. |
| D-18 governance finality | PASS | Approved/final/review rows block pre-model and post-lock; only adoption/review changes formal state. |
| D-19 question lifecycle | PASS | Human prefix stays exact; only open Context questions enter tagged merge/trace/pending. |
| D-20 API compatibility | PASS | Generate and compile responses remain; retired field route returns authorized 410 while read/review remains. |
| D-21 duplicate constructors removed | PASS | Both Deliverable compilers and composite legacy generator are deleted. |
| D-22 cross-cutting regression | PASS WITH QUALIFICATION | Focused 79, adjacent 176, maximum 404; two exact Windows baselines and PostgreSQL limit remain. |

## Concurrency And Governance

Canonical services perform Context/model work without a task lock, then enter a fresh transaction. They validate the actor, repeat permission authorization, lock Project before task, apply the same lifecycle policy, compare the full local snapshot, and atomically apply a whitelisted draft or record a bounded non-success.

Source and Mart barrier tests cover concurrent approval, final adoption, review start, permission revocation, Project/task changes, and model interruption. SQLite evidence shows at-most-one application-allowed draft state and zero partial writes. Deliverable items reuse that generator boundary and commit their own bounded item result, so one blocked/failed item does not roll back completed siblings.

## Authority, Provenance, Performance, And Privacy

- RegulatoryContextBuilder is the only shared-fact seam. Task enumeration identifies work but does not build prompt facts.
- Direct compile and queued callers do not query peer Scenario/Mapping/RAG/template/evidence sources to build another context.
- Facts retain authority, state, source/evidence/version/confidentiality provenance; retrieved knowledge is never promoted to confirmed truth.
- Adapter sorting/caps remain deterministic. Query-growth tests pass with fixed positive post-warm-up counts; Phase 9's `21 -> 21` builder evidence remains non-linear and catalog enrichment remains exact `+1`.
- Durable diagnostics contain bounded IDs, codes, counts, dates, hashes, and field names. Raw Context, prompts, evidence, confidential content, final text, and model drafts are excluded.

## Flagged Assumptions

| Original assumption | Result | Boundary |
| --- | --- | --- |
| GEN-01 concurrency | PASS on SQLite | Source lifecycle/permission/stale/interruption tests; PostgreSQL driver semantics UNVERIFIED. |
| GEN-02 concurrency | PASS on SQLite | Symmetric Mart tests and frozen upstream Context; PostgreSQL driver semantics UNVERIFIED. |
| GEN-03 final preservation | PASS | Direct, batch, and Deliverable Scenario regressions preserve final/confirmed content. |
| GEN-04 no invented fact/state | PASS | Sparse/physical/question and retired legacy route tests. |

## ASVS L1 Threat Register

| Threat | Result |
| --- | --- |
| Scope/Principal spoofing | PASS: exact Principal, active queued User, falsey/disabled denial, project/institution isolation. |
| Authorization elevation | PASS: `deliverable.generate` never substitutes for `technical.edit`; revocation blocks items. |
| Competing fact construction | PASS: old compilers/service removed; no fallback. |
| Post-approval/stale mutation | PASS on SQLite: lifecycle before model and after lock; full snapshot; zero partial write. |
| Diagnostic disclosure | PASS: bounded codes/fields only; no raw Context/prompt/evidence. |
| Qualification tampering | PASS: unfiltered first, exact signature classification, exactly two deselections. |

## PostgreSQL UNVERIFIED Boundary

Read-only probes after the maximum run reported:

- `DATABASE_URL`, `TEST_DATABASE_URL`, `POSTGRES_URL`, `PGHOST`, `PGPORT`, and `PGDATABASE`: unset;
- TCP 5432 listener: none;
- Windows PostgreSQL service: none;
- `pg_isready -h 127.0.0.1 -p 5432 -t 2`: no response, exit 2;
- application database scheme: `sqlite`.

No real PostgreSQL migration/runtime/concurrent transaction was executed. Live PostgreSQL `SELECT ... FOR UPDATE` order and concurrent commit behavior remain **UNVERIFIED** and mandatory for staging. SQLite proves application ordering, deterministic reload/comparison, and atomic writes only; it is not PostgreSQL parity.

## Scope Fence

Gap closure changed only Phase 10 planning/summary/qualification artifacts, double-layer lifecycle and generator caller services, one exact resource-guard permission mapping, and backend tests. It deleted three obsolete generator/compiler modules. It added no frontend, SQL Generator, DataQualityExpectation, Semantic Impact, generator unification, ReportingPeriod, schema, migration, Phase 9 Contract redesign, package, external service, or fact store.

Existing user frontend modifications, `.planning/config.json`, and unrelated untracked assets remained untouched and uncommitted. No reset, cleanup, stash, destructive command, or push occurred.

## Artifact Inventory

Added: `double_layer_review.py`, `test_legacy_mapping_retirement.py`, and plans/summaries 10-05 through 10-08. Modified: Source/Mart generators, adapters, mapping/deliverable/field APIs, resource guard, prompt runtime, and focused tests. Removed: `source_to_mart_compiler.py`, `mart_to_ybt_compiler.py`, and `mapping_generator.py`. No persisted model/schema artifact was removed.

## Remaining Risks

1. The two exact Windows productization nodes remain open host-specific baselines; unfiltered pytest is not exit-zero on this machine.
2. Live PostgreSQL row-lock and concurrent-commit behavior is UNVERIFIED.
3. Candidate profile summaries must remain draft provenance and never suppress missing-evidence questions.

## Conclusion

GEN-01 through GEN-04 and D-01 through D-22 have concrete post-gap evidence. `CR-01`, `CR-02`, `WR-01`, and the competing field generator are closed. Phase 10 is qualified for its SQLite backend scope, subject to the exact Windows host baselines and explicit PostgreSQL staging gate.
