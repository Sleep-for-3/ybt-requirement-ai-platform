---
phase: 10-generator-refactor
plan: 04
qualified_at: 2026-08-23
status: qualified-with-known-baselines
requirements: [GEN-01, GEN-02, GEN-03, GEN-04]
backend_runtime: SQLite
postgresql_live: unavailable
---

# Phase 10 Generator Refactor Qualification

## Verdict

**QUALIFIED WITH TWO EXACT PRE-EXISTING WINDOWS BASELINES AND AN EXPLICIT LIVE-POSTGRESQL LIMIT.**

- All four generator families, direct routes, batch callers, and Deliverable callers use the authorized `RegulatoryContextBuilder`/typed-projection seam for shared facts. The final focused suite passed **51 tests**.
- The final unfiltered backend run executed every collected test and reported **386 passed, 2 failed, 0 skipped, 5 warnings**. Both failures match the only two previously documented Windows nodes and signatures exactly; there are no new backend regressions.
- The maximum must-pass run deselected exactly those two nodes—no file or class was excluded—and passed **386 tests** with exit code 0.
- A first unfiltered run exposed one genuine `metadata_catalog` compatibility regression. It was classified as **NEW REGRESSION**, fixed through the existing Context-only candidate-projection seam in commit `bca2ed7`, and then passed in the final unfiltered and maximum suites. No ORM, RAG, evidence, history, lineage, catalog, peer, or old-generator fallback was restored.
- SQLite exercises deterministic behavior, no-long-lock boundaries, stale-write rejection, isolation, confidentiality, audit privacy, and fixed post-warm-up query growth. Live PostgreSQL was not available locally, so real row-lock/concurrency behavior remains a staging qualification item and is not represented as passed.

## Reproducible Execution Record

All commands below were real executions; no collect-only result is used as evidence. Times are UTC on 2026-08-23. “Skipped” is pytest's skipped-test count; the two intentional exclusions in the maximum suite are reported separately as deselections.

| Command | Start UTC | End UTC | Exit code | Passed | Failed | Skipped | Warnings | Classification |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `cd backend; python -m compileall -q app` (preliminary) | 10:35:44.856 | 10:35:45.371 | 0 | N/A | 0 | N/A | 0 | PASS; 0.505s wall |
| `cd backend; python -m pytest -q tests/test_generator_context_adapters.py tests/test_double_layer_mapping.py tests/test_scenario_traceability.py -x` (preliminary) | 10:35:53.857 | 10:41:59.589 | 0 | 50 | 0 | 0 | 0 | PASS; 360.52s pytest, 365.732s wall |
| `cd backend; python -m pytest -q tests/test_regulatory_context_api.py tests/test_regulatory_context_contract.py tests/test_regulatory_context_builder.py tests/test_semantic_layer.py tests/test_llm_runtime.py tests/test_governance.py tests/test_knowledge_rag.py tests/test_hybrid_retriever.py tests/test_semantic_retrieval_security.py tests/test_deliverables.py -x` (preliminary) | 10:42:10.975 | 10:43:19.607 | 0 | 173 | 0 | 0 | 0 | PASS; 63.61s pytest, 68.632s wall |
| `cd backend; python -m pytest -q` (first unfiltered discovery run) | 10:43:29.623 | 10:52:24.252 | 1 | 384 | 3 | 0 | 5 | **NEW REGRESSION**: metadata catalog compatibility; plus two exact **PRE-EXISTING** Windows baselines. 529.06s pytest, 534.621s wall |
| `cd backend; python -m compileall -q app` (final) | 10:58:56.458 | 10:58:56.973 | 0 | N/A | 0 | N/A | 0 | PASS; 0.505s wall |
| `cd backend; python -m pytest -q tests/test_generator_context_adapters.py tests/test_double_layer_mapping.py tests/test_scenario_traceability.py -x` (final focused) | 10:59:06.471 | 11:05:23.664 | 0 | 51 | 0 | 0 | 0 | PASS; 373.23s pytest, 377.176s wall |
| `cd backend; python -m pytest -q tests/test_regulatory_context_api.py tests/test_regulatory_context_contract.py tests/test_regulatory_context_builder.py tests/test_semantic_layer.py tests/test_llm_runtime.py tests/test_governance.py tests/test_knowledge_rag.py tests/test_hybrid_retriever.py tests/test_semantic_retrieval_security.py tests/test_deliverables.py -x` (final adjacent) | 11:05:40.205 | 11:06:49.413 | 0 | 173 | 0 | 0 | 0 | PASS; 63.85s pytest, 69.201s wall |
| `cd backend; python -m pytest -q` (final unfiltered) | 11:07:00.250 | 11:16:04.736 | 1 | 386 | 2 | 0 | 5 | **PRE-EXISTING ONLY**: the two exact Windows baselines below; no new regression. 539.11s pytest, 544.479s wall |
| `cd backend; python -m pytest -q --deselect=tests/test_productization.py::test_windows_secret_acl_commands_remove_explicit_extra_access_and_are_idempotent --deselect=tests/test_productization.py::test_windows_lifecycle_script_without_action_keeps_control_console_open` | 11:16:17.038 | 11:25:13.808 | 0 | 386 | 0 | 0 | 5 | PASS; exactly 2 deselected, 531.30s pytest, 536.761s wall |
| `cd backend; python -m pytest -q tests/test_generator_context_adapters.py tests/test_regulatory_context_builder.py tests/test_regulatory_context_api.py -k "sql or query or isolation or confidential or fallback or audit" -x` | 11:25:37.862 | 11:25:53.126 | 0 | 25 | 0 | 0 | 0 | PASS; 49 deselected by the planned keyword selection, 11.42s pytest, 15.257s wall |

### Exact Windows Baseline Classification

| Node | Final signature | Classification |
| --- | --- | --- |
| `tests/test_productization.py::test_windows_secret_acl_commands_remove_explicit_extra_access_and_are_idempotent` | `acl["Protected"]` is `None`; assertion expected `True` | **PRE-EXISTING** Windows ACL baseline; exact node and signature match the Phase 9/earlier Phase 10 record |
| `tests/test_productization.py::test_windows_lifecycle_script_without_action_keeps_control_console_open` | `subprocess.TimeoutExpired` after 10 seconds while invoking `项目启停.ps1` | **PRE-EXISTING** Windows lifecycle-console baseline; exact node and signature match the Phase 9/earlier Phase 10 record |

No unknown failure was deselected. The unfiltered run executed both baseline nodes before the maximum run excluded those two exact node IDs.

### Warning Qualification

The unfiltered and maximum suites each emitted the same five non-failing warnings:

- one `RuntimeWarning` from `tests/test_datasources.py::test_datasource_name_must_be_unique_within_project` because its isolated test process uses the temporary `APP_SECRET_KEY` fallback;
- four Python 3.12 SQLAlchemy SQLite datetime-adapter `DeprecationWarning` instances from the semantic migration regression.

No warning was promoted, hidden, or removed from the command counts.

## New Regression Found and Closed

The first unfiltered suite failed `tests/test_metadata_catalog.py::test_sqlite_metadata_sync_search_pagination_and_import` because the generated Scenario technical draft no longer retained the governed candidate profile marker `安全探查摘要` / `distinct=2`.

- **Root cause:** Phase 9 correctly kept draft Scenario technical candidate evidence outside trusted `knowledge_evidence`, but the candidate `evidence_excerpt` exposed only the processing rule and the technical projection did not carry the bounded current-task profile summary.
- **Fix:** `context_collectors.py` stores the bounded summary in the existing candidate `evidence_excerpt`; `ScenarioContextAdapter` selects only the current lineage's frozen summary into `ScenarioTechnicalProjection.supporting_evidence_summaries`; `scenario_draft_generator.py` appends only that projection value to the AI draft.
- **Trust result:** the value remains `resolver_candidate`/draft, never becomes trusted evidence, never suppresses `MISSING_EVIDENCE`, and never creates a second builder or ORM/RAG/catalog read. Final/confirmed state and audit-body privacy remain unchanged.
- **Targeted proof:** metadata catalog regression, candidate-evidence-gap regression, and frozen-summary/audit regression passed together (**3 passed in 11.80s**); `compileall` passed. The final focused run grew from 50 to 51 tests, and both the final unfiltered and maximum suites passed the metadata node.
- **Commit:** `bca2ed7` (`fix(10-04): preserve governed profile evidence`).

## GEN Requirement Evidence

| Requirement | Result | Executed evidence |
| --- | --- | --- |
| GEN-01 | PASS | `test_source_to_mart_route_passes_exact_authorized_boundary`, `test_source_to_mart_service_uses_one_context_and_governed_output_policy`, `test_source_to_mart_rejects_every_local_snapshot_category`, `test_source_to_mart_rechecks_permission_after_model_without_draft`, and final focused/full suites prove one candidate Context, the unchanged Source contract, conservative questions/caps, final-state preservation, and stale/permission rejection. |
| GEN-02 | PASS | `test_mart_to_ybt_route_passes_exact_authorized_boundary`, `test_mart_to_ybt_service_uses_frozen_context_upstream_and_output_policy`, `test_mart_to_ybt_blocked_readiness_never_calls_model_or_mutates_task`, and the cross-family/static contract test prove one immutable provenance-stamped Context projection, no second build/query, unchanged Mart response/adoption contract, and next-attempt visibility of newly approved upstream facts. |
| GEN-03 | PASS | Business direct tests plus `test_batch_queued_handlers_recover_exact_nonlegacy_actor_and_project`, invalid/disabled queued-actor tests, runtime isolation, and Deliverable tests prove the distinct Scenario business contract, active-User recovery, fresh permission checks, bounded queue failures, and immutable confirmed/final content. |
| GEN-04 | PASS | Technical direct/queued tests, `test_technical_generate_accepts_exact_context_physical_tuple`, `test_technical_generate_skips_unknown_physical_tuple_but_keeps_safe_output`, frozen-evidence-summary test, physical-change stale test, and `test_sparse_output_policy_caps_confidence_and_omits_unknown_physical_and_governance_fields` prove exact physical allow-listing, deterministic questions/low confidence, and no invented physical/formal state. |

## D-01 through D-22 Evidence

| Decision | Result | Concrete evidence |
| --- | --- | --- |
| D-01 — sole shared-fact seam | PASS | `test_all_four_generators_share_one_context_seam_and_distinct_runtime_contracts`, route-boundary tests, and one-build spies show `RegulatoryContextBuilder` plus typed projections are the only shared-fact seam. |
| D-02 — fail closed on construction failure | PASS | `test_builder_failure_propagates_before_adapter_or_legacy_fallback_and_preserves_snapshot`, Context-route error bounding, and generator failure matrix show no model, draft, final, or fallback after builder failure. |
| D-03 — incomplete Context is governed business state | PASS | Cross-family readiness tests, stable questions, and confidence-cap tests allow only conservative drafts or stable blocks. |
| D-04 — task-local reads/writes remain allowed | PASS | Service tests and `test_double_layer_write_order_and_no_fallback_are_static_contracts` constrain the post-model boundary to actor/permission checks, Project/task locks, task snapshots, whitelisted apply, audit, and commit/refresh. |
| D-05 — no shadow/legacy fallback | PASS | Static forbidden-import/call assertions plus `test_double_layer_generation_failures_never_fallback_or_partially_write` and queued invalid-identity sentinels prove zero production fallback. |
| D-06 — optional backward-compatible `as_of` | PASS | All direct route boundary tests retain optional `as_of`; old end-to-end API calls still pass. |
| D-07 — effective-date priority | PASS | `test_as_of_resolution_prefers_explicit_then_injected_current_business_date` proves explicit date first and injected current date otherwise. |
| D-08 — reuse time concepts; no reporting-period persistence | PASS | Temporal tests pass and the Phase 10 committed-file scope contains no model, schema, migration, or ReportingPeriod addition. |
| D-09 — redacted resolved date trace | PASS | Source tracer, temporal HTTP, audit-redaction, and projection metadata checks retain `resolved_as_of` without raw bodies. |
| D-10 — three adapter families/four projections | PASS | `test_all_four_task_projections_are_distinct_and_mart_uses_approved_context_rule_only` covers Source, Mart, Scenario business, and Scenario technical projections. |
| D-11 — typed deterministic bounds/provenance | PASS | Adapter order/cap/hash assertions and Phase 9 builder deterministic-bound/provenance regressions pass in focused/adjacent/full suites. |
| D-12 — no full Context prompt dump | PASS | Four-projection confidentiality matrix denies restricted external execution before model call and confirms redacted AuditLog with no ModelCallLog; audit raw-marker negatives pass. |
| D-13 — task-specific differences | PASS | Cross-family matrix asserts four prompt keys, structured schemas, renderers, outputs, and unchanged response contracts. |
| D-14 — typed task-aware readiness | PASS | Source/Mart blocked-readiness tests and Scenario business/technical failure matrices exercise task-specific blockers. |
| D-15 — non-blocking gaps yield conservative drafts | PASS | Readiness, question merge, sparse output, and unknown-physical tests retain pending output only with stable questions and capped confidence. |
| D-16 — mapping-gap exceptions | PASS | `test_source_to_mart_readiness_treats_own_mapping_gap_as_non_blocking_but_blocks_core_conflict` and Mart cross-family assertions keep the two task-owned mapping gaps non-blocking only for their intended task. |
| D-17 — core/identity/governance conflicts block | PASS | Core-conflict, disabled-user, permission-revocation, stale-snapshot, and physical-change tests produce stable non-success with no draft/success audit. |
| D-18 — governance remains final | PASS | Source/Mart output policy, Scenario direct/queued, end-to-end adoption, and concurrency tests prove generation changes only AI draft; adoption/review alone changes final/confirmed/approved content. |
| D-19 — stable question merge | PASS | `test_question_merge_preserves_human_bytes_and_is_stable_deduplicated_and_idempotent` verifies byte-exact human text first, `[CTX:<code>]`, `[AI]`, normalized first-seen deduplication, and idempotence. |
| D-20 — API compatibility | PASS | `test_double_layer_mapping_end_to_end_api`, Scenario CRUD/adopt tests, direct route schemas, and Deliverable lifecycle pass; `as_of`/diagnostics remain additive. |
| D-21 — duplicated shared-context construction removed | PASS | Cross-family AST/static contracts find no generator-side shared-fact ORM/RAG/evidence/history/lineage/catalog/peer helper or import; the metadata compatibility fix consumes only an existing projection. |
| D-22 — cross-cutting regression | PASS WITH QUALIFICATION | Isolation/confidentiality/query/audit selection passed 25 tests; adjacent passed 173; final unfiltered had only two exact Windows baselines; maximum suite passed 386. Live PostgreSQL remains explicitly unavailable. |

## Four Flagged Assumptions

The original plan-time records remain visible in `10-04-PLAN.md` with their original classifications and `flagged-unverified` metadata; they were not deleted or silently reclassified. Execution adds the following acceptance result:

| Original record | Execution result | Acceptance evidence |
| --- | --- | --- |
| GEN-01 `concurrency`, unresolved at plan time | **PASS by executed evidence** | Source full-snapshot barrier tests mutate every local category, reauthorize, lock Project→task, reject stale output, preserve concurrent/final data, and omit success audit/draft. |
| GEN-02 `concurrency`, unresolved at plan time | **PASS by executed evidence** | Mart current attempt freezes one complete governed projection; upstream mutation changes neither prompt nor local result and performs no second build/query, while the next generation observes the new approved fact. Failure/partial-write and final/adoption tests preserve the governed row boundary. |
| GEN-03 `unclassified`, unresolved at plan time | **PASS by executed evidence** | Business and technical direct, batch, and Deliverable attempts preserve confirmed/final content across success, blocked, runtime-failure, stale, disabled-actor, and revoked-permission paths. |
| GEN-04 `unclassified`, unresolved at plan time | **PASS by executed evidence** | Missing evidence/knowledge/lineage yields deterministic questions and capped confidence; an unknown physical tuple is not persisted, and model output cannot manufacture confirmed/approved state. |

## Identity, Authorization, and Caller Qualification

- **Direct callers:** Source, Mart, Scenario business, and Scenario technical route tests compare the complete frozen `CurrentPrincipal` fields and authorized Project passed to the generator. Explicit legacy works only when `is_legacy_system=True` on that request.
- **Queued callers:** batch and Deliverable handlers reload a positive `created_by` as an active persisted User and reconstruct an explicitly non-legacy Principal. `None`, `0`, missing, and disabled identities fail closed; none can spoof legacy.
- **Post-model boundary:** runtime-barrier tests disable the User, revoke/change membership status or role, and mutate task/Project snapshots. The fresh write transaction validates the actor, repeats `PermissionService.require_project_permission`, then locks Project before task and compares the snapshot. No identity/permission/stale failure creates a usable draft or success audit.
- **Isolation:** two-project/two-institution tests with identical identifiers retain Context, candidate, evidence, RetrievalLog, ModelCallLog, and AuditLog scope. Restricted projections deny external runtime before model execution while local runtime remains allowed.

## Temporal, Provenance, Questions, and Governance Qualification

- Explicit `as_of` wins; otherwise the injected current business date is frozen. Inclusive temporal selection, overlap handling, and trace `resolved_as_of` pass at builder and HTTP boundaries. No reporting-date persistence was added.
- Facts retain authority/state/source/evidence/version/confidentiality provenance. Mart upstream content is projection-frozen for the attempt and refreshes only on the next attempt.
- Human question text remains byte-for-byte first; Context additions are tagged `[CTX:<question_code>]`; model-only additions use `[AI]`; normalized first-seen deduplication is stable and idempotent.
- Missing evidence, knowledge, or lineage caps confidence. Exact task-owned mapping gaps remain non-blocking; high-authority core conflicts remain blocking.
- Exact physical database/schema/table/column tuples must occur in current task state or the same governed Context projection. Unknown tuples remain unchanged and questioned. Generation never writes confirmed, approved, or human `final_content`; only explicit adoption/review may do so.

## Query and Performance Qualification

| Boundary | Executed assertion | Result |
| --- | --- | --- |
| Pure adapters | SQL event counter around physical whitelist/projection work | exactly zero adapter SQL |
| Builder warm baseline | one warm-up build is excluded; the next measured count must be positive | PASS; runtime-measured, not hard-coded |
| Catalog enrichment | `enriched_count - pre_enrichment_count == CATALOG_ENRICHMENT_QUERY_DELTA` | PASS; exact fixed delta is **+1** |
| Builder row growth | add mapping, knowledge, lineage, Mart, Catalog, and evidence rows | PASS; growth count equals the corresponding post-warm-up baseline/enriched count |
| HTTP row growth | warm request, measured baseline, then 60 candidate and 40 knowledge rows | PASS; positive baseline and identical growth count |
| Generator row growth | warm Source generation, measured baseline, then 40 unrelated mappings | PASS; positive baseline and identical growth count |
| Build/retrieval seam | spies/sentinels across all four generators | one builder call per generation, no second Mart build/query, no generator shared-fact fallback |

The historical SQLite counts of 21 builder statements and 22 HTTP statements are retained only as Phase 9 comparison data. Phase 10 deliberately asserts measured equality after warm-up and the explicit `+1` enrichment delta; **21/22 are not new unconditional ceilings**.

## Audit and Confidentiality Qualification

- Allowed durable fields are bounded IDs, counts, codes, date/readiness state, projection/output hashes, and output field names.
- Unique raw markers for full Context, prompt, evidence/regulatory/knowledge bodies, human final text, and AI draft are absent from AuditLog summaries.
- Restricted external execution produces a redacted `external_model_data_denied` audit and no ModelCallLog/model invocation.
- Attempt/stale/blocked records remain distinguishable from success; stale, identity, permission, readiness, confidentiality, and runtime failures have no success audit or usable draft.

## ASVS L1 Threat Register

| Threat | Disposition | Result and evidence |
| --- | --- | --- |
| T-10-04-01 — Principal/scope spoofing or disclosure | mitigate | PASS: exact direct Principal handoff, active-User queued recovery, post-model reauthorization, disable/revoke/role-change tests, foreign-scope rejection, explicit-only legacy, and falsey queued-ID rejection. |
| T-10-04-02 — Context/prompt tampering or disclosure | mitigate | PASS: typed bounded projections, data-only rendering, confidentiality aggregation, restricted external denial before model call, raw-marker audit negatives. |
| T-10-04-03 — legacy fallback/blocked-generation tampering | mitigate | PASS: static/import and dynamic sentinels show zero fallback; builder/readiness/confidentiality failures produce no usable draft. |
| T-10-04-04 — stale final/confirmed/physical write or elevation | mitigate | PASS on SQLite: no lock during Context/model work; fresh actor/permission check; Project→task locks; full snapshot compare; atomic whitelisted apply. Live PostgreSQL remains open below. |
| T-10-04-05 — audit/model/qualification repudiation or disclosure | mitigate | PASS: redacted trace fields and negative raw-marker searches; this record contains command/count evidence but no sensitive body. |
| T-10-04-06 — query/prompt denial of service | mitigate | PASS: deterministic caps, one build/retrieval, zero adapter SQL, post-warm-up fixed counts, exact +1 Catalog delta, and invariant growth tests. |

No unplanned endpoint, authentication path, file-access boundary, database schema, migration, external service, or new fact store was introduced by Plan 10-04.

## SQLite and PostgreSQL Boundary

The regression suites ran against the repository's existing SQLite test/runtime configuration. Current read-only PostgreSQL readiness checks produced:

| Check | UTC | Exit/result |
| --- | --- | --- |
| `pg_isready -h 127.0.0.1 -p 5432 -t 2` | 11:26:21.288–11:26:27.191 | exit 2, `127.0.0.1:5432 - no response` |
| Windows PostgreSQL service inventory | same probe | no PostgreSQL service |
| local TCP 5432 listener inventory | same probe | `PORT_5432_LISTENERS=0` |
| process/environment connection inputs | same probe | `DATABASE_URL`, `PGHOST`, and `PGPORT` absent; repository and backend `.env` files absent |
| application database scheme | 11:28:37.092–11:28:37.883 | exit 0, `sqlite` |
| local tooling | 11:26 probe | `psql` installed; client availability does not imply a live server |

Therefore no live PostgreSQL claim is made. SQLite proves application-level ordering, fixed query growth, stale rejection, and transaction isolation behavior. A PostgreSQL staging run is still required to confirm real `SELECT ... FOR UPDATE` blocking/order and concurrent commit behavior under the production driver.

## Scope Fence

The Phase 10 committed range from base `30f53f8` through the Plan 10-04 implementation commits contains only:

- Phase 10 planning/summary/state artifacts;
- generator Context adapters/readiness and Source/Mart/Scenario generator services;
- mapping, Scenario, batch, and Deliverable caller APIs;
- the existing semantic Context collector needed for the Context-only compatibility fix;
- focused generator, Context, governance, and Deliverable tests.

Plan 10-04 itself changed only the three Context-only service files involved in the compatibility fix, five backend qualification test files, and this qualification artifact. It added no frontend, SQL Generator, Semantic Impact, DataQualityExpectation, ReportingPeriod system, package, external service, migration, schema, or Phase 9 Contract redesign.

Existing unrelated modified frontend files and untracked learning/demo/runtime assets were left untouched, unstaged, and uncommitted. No stash, cleanup, reset, push, or destructive command was used.

## Remaining Risks

1. The two exact Windows productization nodes remain open host-specific baselines; they are not generator regressions, but the unfiltered suite is not exit-zero on this machine.
2. Live PostgreSQL was unavailable. Production-driver row-lock/concurrency qualification remains mandatory before claiming PostgreSQL parity.
3. The metadata profile summary is intentionally candidate/draft provenance, not trusted `knowledge_evidence`; future changes must preserve that boundary and the `MISSING_EVIDENCE` behavior.

## Qualification Conclusion

GEN-01 through GEN-04, D-01 through D-22, all four flagged acceptance assumptions, and T-10-04-01 through T-10-04-06 have concrete passing test evidence. Phase 10's generator refactor is qualified for its SQLite-backed backend scope with no new backend regression, while the two exact Windows baselines and unavailable live PostgreSQL staging check remain explicitly visible.
