---
phase: 09-regulatory-context
plan: 02
subsystem: api-contract
tags: [pydantic, regulatory-context, authority, provenance, validation, tdd]

# Dependency graph
requires:
  - phase: 09-regulatory-context/09-01
    provides: Confirmed-only semantic visibility policy, temporal semantic versions, and explicit entity adapters
provides:
  - Strict RegulatoryContext 1.0 request/response contract with bounded discriminated fact values
  - Code-defined authority ordering independent from governed fact lifecycle state
  - Typed build input scope and versioned policy metadata bound to context scope, target, scenario, and retrieval provenance
  - Project/institution provenance, retrieval-log, confidentiality, temporal, conflict, and open-question guards
  - Test-only four-record CTX spec-less metadata probe with verified non-emission from product output
affects: [09-03 context builder, 09-04 context API, phase-10 generators]

# Actuals (#2632)
actuals:
  tokens: 16825
  tasks: 2
  commits: 9

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Strict Pydantic v2 projection models with extra-forbid and bounded discriminated unions
    - Independent authority rank and lifecycle state vocabularies with fail-closed source mapping
    - Mirrored fact/provenance fields validated for consistency at the contract boundary
    - Reproducible build metadata whose typed inputs and retrieval-log set are validated against emitted facts

key-files:
  created:
    - backend/app/schemas/regulatory_context.py
    - backend/app/services/semantic/context_authority.py
    - backend/tests/test_regulatory_context_contract.py
  modified:
    - backend/app/services/semantic/__init__.py

key-decisions:
  - "RegulatoryContextRequest accepts project and target inputs but never institution_id; institution scope is output-derived and facts must match the context project/institution boundary."
  - "Formal and explicitly human-confirmed sources share the highest authority tier, while authority comparison never changes FactState."
  - "Retrieved facts require RetrievalLog provenance, and knowledge confidentiality must match between the bounded value and provenance."
  - "Every ContextFact authority is derived from its registered source_type; unknown sources fail closed and cannot self-assign a stronger rank."
  - "Build metadata records context/policy versions plus a typed input scope, and its project/date/target/scenario/retrieval identities must match the emitted context."
  - "The CTX-01 through CTX-04 spec-less probe exists only in tests; the runtime contract exports no probe symbol and emits no synthetic questions."

patterns-established:
  - "ContextFact envelope: typed discriminated value plus independent authority/state, bounded evidence, temporal fields, confidence, and consistent provenance."
  - "Deterministic gaps: conflicts and open questions expose stable sort keys and are normalized by RegulatoryContext before serialization."

requirements-completed: []
requirements-progressed: [CTX-01, CTX-02, CTX-04]

coverage:
  - id: D1
    description: "Versioned RegulatoryContext request/response contract with normalized scope, target, scenario, and all bounded fact sections"
    requirement: CTX-01
    verification:
      - kind: unit
        ref: "tests/test_regulatory_context_contract.py#test_schema_version_normalized_scope_and_deterministic_json_round_trip"
        status: pass
      - kind: unit
        ref: "tests/test_regulatory_context_contract.py#test_all_section_values_are_bounded_and_reject_orm_or_arbitrary_nested_data"
        status: pass
      - kind: unit
        ref: "tests/test_regulatory_context_contract.py#test_build_metadata_is_typed_complete_and_bound_to_context_inputs_and_retrievals"
        status: pass
    human_judgment: false
  - id: D2
    description: "Stable authority ranking separated from lifecycle state with retrieval/inference promotion protection"
    requirement: CTX-02
    verification:
      - kind: unit
        ref: "tests/test_regulatory_context_contract.py#test_authority_order_is_code_defined_without_mutating_fact_state"
        status: pass
      - kind: unit
        ref: "tests/test_regulatory_context_contract.py#test_retrieved_provenance_requires_log_and_matching_confidentiality"
        status: pass
      - kind: unit
        ref: "tests/test_regulatory_context_contract.py#test_fact_authority_must_match_registered_source_and_unknown_sources_fail_closed"
        status: pass
    human_judgment: false
  - id: D3
    description: "Deterministic provenance, inclusive temporal validation, bounded conflicts/questions, and planning-only CTX probe non-emission"
    requirement: CTX-04
    verification:
      - kind: unit
        ref: "tests/test_regulatory_context_contract.py#test_inclusive_period_bounds_scope_and_deterministic_gap_ordering"
        status: pass
      - kind: unit
        ref: "tests/test_regulatory_context_contract.py#test_spec_less_edge_metadata_is_planning_only_and_not_product_output"
        status: pass
    human_judgment: false

duration: 39min
completed: 2026-08-22
status: complete
---

# Phase 09 Plan 02: RegulatoryContext Contract Summary

**Strict RegulatoryContext 1.0 with bounded discriminated facts, source-derived authority, typed reproducible build inputs, and exact retrieval provenance accounting.**

## Performance

- **Duration:** 39 min
- **Started:** 2026-08-22T12:05:36Z
- **Completed:** 2026-08-22T12:44:26Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added a deterministic `context_schema_version = "1.0"` Pydantic contract covering scope, target, scenario, semantic, regulatory, metadata, candidate, mapping, lineage, knowledge/evidence, historical, quality, conflicts, open questions, and build metadata.
- Added bounded typed values and a shared `ContextFact` envelope that rejects ORM rows, arbitrary nested dumps, extra fields, invalid identifiers/dates, cross-project provenance, and inconsistent build counts.
- Added explicit authority/source ranking independent from `FactState`, including protections against retrieved or inferred promotion and required retrieval/confidentiality provenance.
- Bound each fact's authority to the registered `source_type` policy and reject unknown sources, preventing a source from self-assigning a stronger rank.
- Added typed `ContextInputScope` plus context/policy versions and retrieval log IDs to build metadata; the root contract validates project, date, reporting period, mode, target, scenario, and exact retrieval provenance consistency.
- Kept the four CTX spec-less records in an ordered test-only metadata table and proved they never enter normal context serialization.

## Task Commits

Each TDD task was committed as RED then GREEN; RED-test corrections were kept as explicit atomic fixes:

1. **Task 1 RED: typed RegulatoryContext tracer tests** - `478d4b5` (test)
2. **Task 1 RED correction: authority adjacency assertion** - `3feda15` (test)
3. **Task 1 RED correction: shared formal/human top tier** - `9c06ea7` (test)
4. **Task 1 GREEN: strict contract and authority/state tracer** - `6446c2b` (feat)
5. **Task 2 RED: bounded sections, provenance, scope, and non-emission tests** - `b685bf0` (test)
6. **Task 2 GREEN: retrieval-log and confidentiality enforcement** - `97fa7f2` (feat)
7. **Review RED: metadata/retrieval and source-authority regression tests** - `629c388` (test)
8. **Review RED correction: supported candidate mode fixture** - `39a65c2` (test)
9. **Review GREEN: governed build inputs and source-derived authority** - `13f0152` (feat)

**Plan metadata:** finalized in the subsequent state-tracking commit.

## Files Created/Modified

- `backend/app/schemas/regulatory_context.py` - strict request, scope, target/scenario, fact/value, provenance, temporal, conflict/question, build metadata, and RegulatoryContext schemas.
- `backend/app/services/semantic/context_authority.py` - stable authority/state enums, explicit rank/source maps, comparison, and confirmation helpers.
- `backend/app/services/semantic/__init__.py` - additive authority-policy exports while preserving Phase 8 symbols.
- `backend/tests/test_regulatory_context_contract.py` - nine contract, rejection, provenance, ordering, scope, source-authority, build-input, retrieval-accounting, and spec-less non-emission tests.

## Decisions Made

- Keep institution ownership out of caller-controlled request data; future API/builder code must derive it from the authorized Project and populate output scope.
- Treat formal and human-confirmed sources as an equal highest authority tier, then rank regulatory, semantic, mapping, lineage, metadata, historical, retrieved, and inferred sources explicitly.
- Keep authority, state, source/evidence/temporal fields, confidence, and provenance independently serialized; mirrored fact/provenance fields must agree.
- Require a retrieval log for retrieved facts and require knowledge confidentiality to survive unchanged into provenance.
- Derive `ContextFact.authority` from the registered source policy at validation time; an unknown or mismatched source fails closed before it can enter a context.
- Record build project/date, typed target/scenario inputs, candidate limit, semantic/authority policy versions, and a bounded normalized retrieval-log list; require exact agreement with the context and all emitted fact provenance.
- Keep conflict/question normalization in the contract, but keep domain gap production and all persistence in later plans or existing source models.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test Bug] Corrected the initial authority-order RED assertion**
- **Found during:** Task 1 RED review
- **Issue:** The first test used unequal `zip(..., strict=True)` inputs and simultaneously treated formal/human-confirmed as ordered and equal.
- **Fix:** Compared only adjacent equal-length slices and modeled formal/human-confirmed as one highest authority tier before the descending sequence.
- **Files modified:** `backend/tests/test_regulatory_context_contract.py`
- **Verification:** RED still failed only because the production modules were absent; the final authority test passes.
- **Committed in:** `3feda15`, `9c06ea7`

**2. [Rule 1 - State Bookkeeping] Corrected SDK-generated phase progress metadata**
- **Found during:** Final state update
- **Issue:** `state.update-progress` replaced the milestone's eight-phase count with two and labeled the global 5/7 plan ratio as Phase 9 progress; `state.add-decision` emitted `Phase ?`, and ROADMAP retained the stale `09-02 next` text.
- **Fix:** Restored eight total milestone phases, recorded Phase 9 as 2/4 (50%), assigned the decisions to Phase 9, refreshed last activity, and advanced the ROADMAP status text to 09-03.
- **Files modified:** `.planning/STATE.md`, `.planning/ROADMAP.md`
- **Verification:** Final planning-file diff and `state.load` show Plan 3 of 4 with 50% Phase 9 progress and 09-03 as next.
- **Committed in:** final plan metadata commit

**3. [Rule 1 - Contract Bug] Closed review gaps in build provenance and authority enforcement**
- **Found during:** Main-thread post-implementation review
- **Issue:** Build metadata omitted required version/input/retrieval identity fields, and `ContextFact` did not apply the existing fail-closed `authority_for_source()` policy, so a known source could declare a mismatched authority.
- **Fix:** Added strict typed input scope and complete version/project/date/retrieval metadata, validated it against scope/target/scenario and the exact fact retrieval-log set, and enforced registered source authority while preserving source/provenance mirroring and anti-promotion guards.
- **Files modified:** `backend/app/schemas/regulatory_context.py`, `backend/tests/test_regulatory_context_contract.py`
- **Verification:** Review regressions and the full directed contract suite pass; compileall remains clean.
- **Committed in:** `629c388`, `39a65c2`, `13f0152`

---

**Total deviations:** 3 auto-fixed (3 Rule 1 bugs)
**Impact on plan:** The corrections close required contract acceptance behavior without broadening production scope beyond the 09-02 schema and authority policy.

## Issues Encountered

- Context7 documentation lookup returned a monthly-quota error and the required `ctx7` CLI fallback was not installed. No package was downloaded; implementation followed the repository's installed Pydantic 2.13.4 patterns and passed runtime tests.
- An additional, non-required Phase 8 regression run produced `23 passed, 1 failed`: `test_additive_version_routes_preserve_concept_compatibility_and_static_precedence` creates an effective version using the current date (2026-08-22) but queries the fixed date 2026-08-20, so the effective response is `None`. This plan did not modify `version_service.py` or `test_semantic_layer.py`; the date-sensitive test is outside the 09-02 owned-file boundary and was not changed.

## Verification

- `python -m pytest -q tests/test_regulatory_context_contract.py` — **9 passed**.
- `python -m pytest -q tests/test_regulatory_context_contract.py -k "schema_version or fact or authority" -x` — **3 passed, 1 deselected** at the tracer gate.
- `python -m compileall -q app` — **passed**.
- Prohibition scan found no SQLAlchemy persistence model, cache/repository, generator, frontend import, ORM serialization mode, or unconstrained `dict[str, Any]` fact store in plan-owned runtime files.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 09-03 can construct `RegulatoryContextRequest`, emit section-specific `ContextFact` values, and rely on strict cross-scope and build-count validation.
- 09-03 must populate typed build input scope, policy versions, and the exact normalized set of retrieval log IDs emitted by its facts.
- CTX-01, CTX-02, and CTX-04 remain in progress until the 09-03 builder and 09-04 project-aware API complete the end-to-end requirement behavior.
- Retrieval-backed collectors must provide `retrieval_log_id` and preserve the knowledge confidentiality level in provenance.
- No builder, API endpoint, generator, frontend, database table, cache, snapshot, copied mapping, or copied lineage was introduced in 09-02.
- The unrelated date-sensitive semantic regression should be repaired in the owner of `version_service.py`/`test_semantic_layer.py`, not by 09-02.

## Self-Check: PASSED

- Summary and all four plan-owned implementation/test files exist.
- All nine RED/GREEN and test-correction commit hashes are present in git history.
- Required contract tests, compile verification, stub scan, and scope/prohibition scan completed with the results recorded above.

---
*Phase: 09-regulatory-context*
*Plan: 02*
*Completed: 2026-08-22*
