---
phase: 09-regulatory-context
verified: 2026-08-22T20:10:45Z
status: passed
score: 11/11 must-haves verified
behavior_unverified: 0
overrides_applied: 0
requirement_statuses:
  CTX-01: satisfied
  CTX-02: satisfied
  CTX-03: satisfied
  CTX-04: satisfied
gaps: []
postgresql_live: unavailable
staging_release_gate: required
---

# Phase 09: Regulatory Context Verification Report

**Phase Goal:** 建立统一、版本明确、带权威等级和 provenance 的 RegulatoryContext Contract。

**Verified:** 2026-08-22T20:10:45Z  
**Status:** PASSED with an explicit live-PostgreSQL staging release gate  
**Re-verification:** No — initial goal-backward verification

## Verdict

Phase 9's goal is achieved in the current codebase. The implementation provides one strict, versioned, project-scoped `RegulatoryContext` projection, a machine-defined authority/state policy, date-effective governed semantic versions, deterministic gaps/conflicts, and a secured read-only build API. The critical behavior is exercised by tests run by this verifier at the current HEAD, not inferred from the four SUMMARY files.

No blocking implementation gap was found. Live PostgreSQL was not available and is **not** marked passed. It remains a mandatory staging release gate for live migration execution, database-enforced constraints, row locking, and concurrent overlap rejection.

## Goal Achievement

### Observable Truths

| # | Observable truth | Status | Code and behavioral evidence |
|---|---|---|---|
| 1 | A stable Pydantic `RegulatoryContext` can be requested by project and every locked optional scope: target table, target field, scenario, mart field, semantic concept, `as_of`, and reporting-period label. | VERIFIED | `backend/app/schemas/regulatory_context.py:31-68,353-404,489-613` defines strict extra-forbid request/output models, all optional scopes, normalized date/period inputs, and schema version `1.0`. `backend/app/api/regulatory_context.py:20-53` exposes the same inputs. `test_all_contract_scope_parameters_and_bounds_are_enforced` passed in the verifier's 89-test run. |
| 2 | Authority ranking is stable and machine-distinguishable while lifecycle state remains independent. | VERIFIED | `backend/app/services/semantic/context_authority.py:14-100` defines formal/human-confirmed, regulatory, semantic, mapping, lineage, metadata, historical, retrieved, and inferred tiers plus a separate `FactState`. Unknown sources fail closed. `ContextFact` enforces source-derived authority and forbids retrieved/inferred promotion at `regulatory_context.py:291-350`. Contract authority/state tests passed. |
| 3 | Context is a projection over existing semantic, mapping, lineage, knowledge/evidence, historical, conflict, and question sources; it is not a second fact store. | VERIFIED | `context_builder.py:42-122` orchestrates typed output; `context_collectors.py:120-365` reads existing ORM models and returns facts; `context_conflicts.py:25-143` derives issues from collected signals. No RegulatoryContext persistence model, cache, snapshot table, authoritative insert/update/delete, or context commit exists. The projection-only snapshot test passed. RetrievalLog writes remain retrieval audit metadata, not copied regulatory truth. |
| 4 | Missing knowledge, missing lineage, missing mappings/evidence, and contradictory facts have deterministic structured output. | VERIFIED | Stable codes are defined and sorted in `context_conflicts.py:13-22,25-143`; the HTTP tests assert `MISSING_KNOWLEDGE`, `MISSING_LINEAGE`, `MISSING_EVIDENCE`, mapping gaps, and `CONFLICTING_AUTHORITATIVE_FACTS`, including repeat-call ordering. Empty projects serialize typed empty sections plus explicit questions, not stubs. |
| 5 | `as_of` selects the inclusive effective confirmed version; confirmed meaning is immutable; overlapping confirmed periods are rejected; rejected/deprecated rows never enter trusted or candidate business output. | VERIFIED | `version_service.py:103-145` rejects inclusive overlap under a stable-concept lock; `:322-354` rejects patching a confirmed latest version; `:357-417` performs batched inclusive confirmed-only resolution and rejects ambiguity. `status_policy.py:13-38` restricts trusted/candidate visibility. The SQLite concurrent-writer, temporal boundary, immutability/projection, and HTTP overlap tests all passed in the core run. |
| 6 | The canonical API is authenticated, project-authorized, institution-isolated, read-only with respect to authoritative facts, and deterministic for invalid/missing/cross-project inputs. | VERIFIED | `regulatory_context.py:20-55` calls `require_project_permission(project_id, "project.view")` before constructing the builder and passes the returned Project as `authorized_project`. `context_collectors.py:370-499` rejects foreign targets/scenarios/concepts and project-qualifies semantic reads. API tests passed for unauthorized non-invocation, 400 cross-project scope, 404 hidden project, identical-code two-institution isolation, 422 missing/invalid parameters, and no authoritative mutation. |
| 7 | Candidate facts are ranked before capping and all response sections have deterministic section/global bounds. | VERIFIED | Seven explicit tiers are defined at `context_collectors.py:63-69`; all candidates are sorted before `candidate_limit` at `:282-301`, with field candidates ranked only after the full project set is examined at `:1318-1467`. `context_builder.py:23-35,125-137` enforces 500-per-section and 1000-global fact caps. Rank-before-cap and 500/1000 boundary tests passed. |
| 8 | Builder and HTTP query budgets stay constant under row growth: 21 -> 21-or-less and 22 -> 22. | VERIFIED | `test_query_count_is_measured_bounded_and_retriever_get_boundary_is_qualified` asserts builder baseline 21 and growth `<=21`; `test_candidate_limit_and_http_query_budget_do_not_grow_with_rows` asserts `(22, 22)` after growth from 5 to 65 candidates and 2 to 42 knowledge rows. Both passed in this verifier's core run. Effective semantic version batching also remained at 14 queries under 24 additional matching concepts plus excluded temporal/status rows. |
| 9 | Phase 9 core and adjacent high-risk behavior passes, with no new backend regression. | VERIFIED | This verifier ran the current HEAD: core **89 passed, 4 warnings**; adjacent knowledge/governance/lineage **86 passed**; `python -m compileall -q app` exited 0. Current collection is 339 tests. The two documented Windows productization nodes were rerun and failed with the same signatures: ACL `Protected is None` and `项目启停.ps1` timeout. The final full-suite qualification records **337 passed, the same 2 failures, 5 warnings** at the reviewed source lineage; the full 3+ minute suite was not redundantly rerun by this verifier. |
| 10 | Revision 016 is locally qualified without overstating PostgreSQL coverage. | VERIFIED | `202608200016_semantic_concept_versions.py:59-119` creates the additive version table, foreign keys, date check, unique/index set; `:122-196` bootstraps exactly one v1 per legacy concept; `:199-211` downgrades only the new table. The core run passed SQLite lifecycle and direct PostgreSQL-dialect upgrade/downgrade compilation. `alembic heads` reports `202608200016`. Current live probe: `127.0.0.1:5432 - no response`, no listener, and no PG connection environment. Live PostgreSQL remains a staging gate. |
| 11 | Phase boundary, review, and security fences hold. | VERIFIED | Phase-managed implementation changes contain no Generator refactor, frontend route, SQL Generator, DataQualityExpectation, Semantic Impact, graph infrastructure, or product multi-agent implementation. Final `09-REVIEW.md` is clean after WR fixes; the current core tests cover those fixes. `09-SECURITY.md` records 20/20 threat dispositions closed, and this verifier independently corroborated the high-risk authorization, lifecycle, confidentiality, bounded-output, and query-growth mitigations in code/tests. |

**Score:** 11/11 truths verified; 0 present-but-behavior-unverified.

## Requirements Coverage

| Requirement | Source plans | Status | Evidence |
|---|---|---|---|
| CTX-01 | 09-02, 09-04 | SATISFIED | Strict versioned request/response contract, all locked optional scopes, normalized `as_of`/reporting period, secured API handoff, and acceptance fixture behavior. |
| CTX-02 | 09-01, 09-02, 09-04 | SATISFIED | Central semantic visibility policy; stable source-derived authority tiers; independent fact state; deterministic adapter/resolver policy; audit-only statuses excluded. |
| CTX-03 | 09-03, 09-04 | SATISFIED | Projection-only builder over existing semantic, mapping, lineage, regulatory knowledge, retrieval/evidence, and historical models; no second fact store/cache/snapshot. |
| CTX-04 | 09-01, 09-02, 09-03, 09-04 | SATISFIED | Typed deterministic conflicts/questions, missing knowledge/lineage/evidence coverage, temporal ambiguity/overlap behavior, stable API output tests. |

No Phase 9 requirement mapped in `REQUIREMENTS.md` is orphaned. `REQUIREMENTS.md` still shows CTX-01..04 as pending because this verifier was explicitly prohibited from editing project state files; the orchestrator may update traceability after accepting this report.

## Required Artifacts

| Artifact | Existence and substance | Wiring | Final status |
|---|---|---|---|
| `backend/app/schemas/regulatory_context.py` | 643-line strict typed contract; no arbitrary ORM/JSON envelope | Imported by authority-aware collectors, builder, API, and tests | VERIFIED |
| `backend/app/services/semantic/context_authority.py` | Stable enum/rank/source policy with fail-closed lookup | Used by `ContextFact` validation and every collector fact constructor | VERIFIED |
| `backend/app/services/semantic/status_policy.py` | One trusted/candidate/audit-only policy | Used by graph, resolver, version service, and Context collectors | VERIFIED |
| `backend/app/services/semantic/entity_adapter.py` | Explicit handlers for all 12 allow-listed binding entity types | Consumed by resolver; adapter coverage passed | VERIFIED |
| `backend/app/models/semantic.py` + `version_service.py` | Canonical temporal model and substantive transactional lifecycle logic | Semantic API and governance workflow delegate creation, transitions, effective reads, and legacy projection | VERIFIED |
| `backend/alembic/versions/202608200016_semantic_concept_versions.py` | Additive, reversible explicit migration and bootstrap | Alembic head; SQLite lifecycle and PostgreSQL dialect compilation tests passed | VERIFIED (live PG excluded) |
| `backend/app/services/semantic/context_collectors.py` | Project-bounded collection, ranking, provenance, confidentiality, and bounded typed facts | Called by builder; reads existing governed source models | VERIFIED |
| `backend/app/services/semantic/context_conflicts.py` | Stable conflict/question catalog and deterministic derivation | Called after collection; serialized by contract/API | VERIFIED |
| `backend/app/services/semantic/context_builder.py` | Projection orchestration and response budgets | Called by canonical API with authorized Project | VERIFIED |
| `backend/app/api/regulatory_context.py` + `backend/app/main.py` | Authenticated GET route and response model | Router registered under the existing API prefix and secured dependencies | VERIFIED |
| Phase 9 contract/builder/API/semantic/migration tests | Substantive behavior suite, not existence-only tests | Collected and executed at current HEAD | VERIFIED |

## Key Link Verification

| From | To | Status | Evidence |
|---|---|---|---|
| `main.py` | `api/regulatory_context.py` | WIRED | Import at `main.py:42`; secured registration at `main.py:184`. |
| Context API | `PermissionService` | WIRED | Authorization occurs at `api/regulatory_context.py:35-38` before builder construction; unauthorized non-invocation test passed. |
| Context API | `RegulatoryContextBuilder` | WIRED | Constructed and invoked with `authorized_project=project` at `api/regulatory_context.py:51-53`. |
| Builder | collectors/conflicts/contract | WIRED | `context_builder.py:58-122` collects, budgets, derives issues, and returns `RegulatoryContext`. |
| Collectors | status/version/authority policies | WIRED | Imports at `context_collectors.py:58-60`; effective version resolution, status predicates, and source-derived authority are used in emitted facts. |
| Collectors | existing ORM facts/retrieval | WIRED | Project-scoped queries flow into typed sections; no static fallback or hollow prop exists. |
| Semantic API/governance | version service | WIRED | Additive version routes and semantic governance finalization delegate to canonical version operations. |
| Resolver/graph | adapter/status policy | WIRED | Resolver uses `SemanticEntityAdapter`; resolver and graph apply shared visibility predicates before ranking/traversal. |

The generic GSD key-link query reported false negatives because it searched for literal target file paths in Python sources. Manual import/call/data-flow inspection above resolves those false negatives.

## Data-Flow Trace (Level 4)

| Output section | Real source | Flow to response | Status |
|---|---|---|---|
| Semantic | `SemanticConcept` + effective `SemanticConceptVersion` + scoped `SemanticBinding` | batched select -> `_semantic_fact` -> builder -> API response | FLOWING |
| Mapping / mapping lineage | four existing mapping families + `MappingEvidenceReference` | project-scoped selects -> typed mapping/lineage facts -> response | FLOWING |
| Technical lineage | `LineageEdge` joined to project-scoped nodes/current script version | verified/observed predicate -> typed lineage fact -> response | FLOWING |
| Regulatory / knowledge evidence | `RegulatoryKnowledgeItem` + `HybridRetriever`/`KnowledgeUnit` + `RetrievalLog` | confidentiality-preserving typed facts -> response metadata/provenance | FLOWING |
| Historical | `HistoricalCaliberItem` | project/target-scoped select -> historical fact -> conflict/question signals | FLOWING |
| Conflicts / questions | deterministic signals computed from the collected real facts | detector -> bounded sorted typed arrays -> response | FLOWING |

## Behavioral and Regression Evidence

| Check | Result | Status |
|---|---|---|
| `python -m pytest -q tests/test_regulatory_context_api.py tests/test_regulatory_context_contract.py tests/test_regulatory_context_builder.py tests/test_semantic_layer.py tests/test_semantic_migration.py` | 89 passed, 4 SQLite datetime-adapter warnings, 67.11s | PASS |
| Adjacent knowledge/governance/lineage command from `09-04-POSTGRES-QUALIFICATION.md` | 86 passed, 25.50s | PASS |
| `python -m compileall -q app` | exit 0, no output | PASS |
| `python -m pytest --collect-only -q` | 339 tests collected | PASS |
| Exact two Windows productization tests | same ACL `Protected=None` and launcher timeout signatures; 2 failed | KNOWN PRE-EXISTING |
| `python -m alembic heads` | `202608200016 (head)` | PASS |
| Revision-016 direct PostgreSQL dialect compile | Passed inside current 89-test core run | PASS (offline only) |
| `pg_isready -h 127.0.0.1 -p 5432 -t 2` | no response, exit 2; no local listener | UNAVAILABLE — STAGING GATE |

## PostgreSQL Qualification

Verified locally:

- SQLite empty/head and legacy-015 bootstrap/downgrade/upgrade behavior.
- Revision 016 direct PostgreSQL dialect compilation for upgrade and downgrade.
- Portable foreign keys, effective-date CHECK, unique/index set, and absence of SQLite-only SQL in revision-016 compilation.
- Alembic head is `202608200016`.

Not verified and not claimed:

- Live PostgreSQL upgrade/downgrade.
- PostgreSQL enforcement of foreign keys and date constraints.
- Concurrent `SELECT ... FOR UPDATE` overlap-confirmation behavior.
- PostgreSQL-driver query-budget and isolation behavior.

These remain the mandatory staging checklist in `09-04-POSTGRES-QUALIFICATION.md`. The known older full-chain offline `alembic --sql` limitation at revision `202607070002` is also still documented and was not hidden or rewritten.

## Security and Review Gates

- Final code review frontmatter is `status: clean`, with zero critical/warning/info findings in the final narrow re-review.
- Review fixes for target-scoped explicit concept bindings and stable candidate-binding identity/provenance are present in current source and covered by passing tests.
- Earlier WR fixes for candidate isolation, trusted-evidence gap semantics, response budgets, and not-linked lineage completeness are present in the current collector/builder code and exercised by the 89-test run.
- Security audit records 20 threats closed and no accepted risks. Independent inspection confirmed the high-risk controls rather than relying only on that report: authorization-before-build, project-qualified queries, derived institution scope, candidate/noncandidate separation, fail-closed authority sources, confidentiality/retrieval provenance, bounds, and row-growth query tests.

## Scope Fence and Prohibitions

| Prohibition | Verification | Status |
|---|---|---|
| No Generator refactor or generator instruction/output change | Phase-managed implementation diff contains no generator file | VERIFIED |
| No frontend route/UI work | Phase-managed implementation diff contains no frontend implementation file; unrelated user frontend worktree changes were not touched | VERIFIED |
| No SQL Generator, DataQualityExpectation, Semantic Impact, graph infrastructure, external service/package, or product multi-agent feature | No matching implementation symbol/file was added by Phase 9 | VERIFIED |
| No RegulatoryContext persistence/cache/snapshot/copied mapping/replicated lineage | Model/migration scan has no context store; builder path has no authoritative write/commit | VERIFIED |
| No rejected/deprecated/retrieved/inferred promotion into trusted facts | Central status and authority validators plus trusted/candidate API tests passed | VERIFIED |
| No natural-order cap | Candidate and regulatory ranking occurs before cap; late-best-candidate tests passed | VERIFIED |
| No Phase 8 API removal/rename | Existing semantic route regression tests passed; context/version routes are additive | VERIFIED |

## Anti-Patterns

No blocker debt marker (`TBD`, `FIXME`, `XXX`) exists in the Phase 9 implementation files. Guarded `return []` / `return {}` branches in collectors and batched resolution are legitimate empty-scope behavior and are covered by typed empty-project/gap tests; they are not stubs. No placeholder response or console-only handler was found.

## Known Technical Debt / Release Constraints

1. **Live PostgreSQL staging qualification remains open.** This is a release gate, not a claimed local pass and not a hidden Phase 9 success.
2. **Historical full-chain offline Alembic SQL remains limited at revision `202607070002`.** Direct revision-016 PostgreSQL compilation passes, but the older inspector-dependent revision prevents claiming full-chain offline SQL success.
3. **Two Windows productization tests remain red.** Their current signatures match the pre-Phase-9 environmental baseline; Phase 9 adds no new failure.
4. **SQLite datetime adapter warnings remain.** The core run emitted four Python 3.12 deprecation warnings from the existing adapter path.

## Human Verification Required

None for the Phase 9 goal. All goal-critical state transitions, isolation invariants, deterministic ordering, bounds, and query-growth claims have passing behavioral tests at current HEAD. Live PostgreSQL is routed to the explicit staging release checklist rather than represented as a human-verified local result.

## Gaps Summary

No blocking Phase 9 gaps. Later roadmap phases remain correctly out of scope; no identified Phase 9 gap was deferred to a later milestone phase.

---

_Verified: 2026-08-22T20:10:45Z_  
_Verifier: the agent (gsd-verifier)_
