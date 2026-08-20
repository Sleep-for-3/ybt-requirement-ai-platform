---
phase: 09-regulatory-context
plan: 01
subsystem: semantic-api
tags: [semantic, resolver, temporal-versioning, governance, alembic, fastapi, sqlalchemy]

# Dependency graph
requires:
  - phase: 08-semantic-foundation
    provides: Phase 8 semantic Concept, Binding, Relation models, services, APIs, and governance audit flow
provides:
  - Central trusted/candidate/audit lifecycle policy and explicit twelve-type semantic entity descriptors
  - Deterministic bounded resolver evidence and provenance without confirmation side effects
  - Canonical SemanticConceptVersion temporal service with transactional legacy Concept projection
  - Additive project-scoped version routes and compatibility delegation for Concept CRUD/status
  - Reversible 202608200016 schema/bootstrap migration with one v1 row per legacy Concept
affects: [09-02 regulatory-context builder, semantic governance, semantic graph consumers]

# Actuals (#2632)
actuals:
  tokens: 32687
  tasks: 3
  commits: 7

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Centralized status visibility predicates with trusted-by-default reads and explicit candidate mode
    - Explicit bounded entity adapters and typed resolver evidence/provenance
    - Stable Concept identity with canonical temporal version rows and same-transaction compatibility projection
    - Alembic data bootstrap that is retry-safe and portable across SQLite/PostgreSQL

key-files:
  created:
    - backend/app/services/semantic/status_policy.py
    - backend/app/services/semantic/entity_adapter.py
    - backend/app/services/semantic/version_service.py
    - backend/alembic/versions/202608200016_semantic_concept_versions.py
  modified:
    - backend/app/models/semantic.py
    - backend/app/schemas/semantic.py
    - backend/app/api/semantic.py
    - backend/app/services/semantic/graph_service.py
    - backend/app/services/governance/workflow.py
    - backend/tests/test_semantic_layer.py
    - backend/tests/test_governance.py
    - backend/tests/test_semantic_migration.py

key-decisions:
  - "Trusted mode remains confirmed-only; candidate mode explicitly adds draft and ai_suggested while excluding rejected and deprecated."
  - "SemanticConceptVersion is the canonical temporal meaning; legacy Concept fields are only a same-transaction compatibility projection."
  - "The effective route is declared before the dynamic version-id route, and effective intervals use inclusive boundaries."
  - "Migration bootstrap creates exactly version_no=1 from legacy Concept created_at (fixed 2026-08-20 fallback) without manufacturing edit history."

requirements-completed: []
requirements-progressed: [CTX-02, CTX-04]

coverage:
  - id: D1
    description: "Central lifecycle policy, explicit twelve-type adapters, deterministic resolver ordering, and bounded provenance-bearing candidates"
    requirement: CTX-02
    verification:
      - kind: unit
        ref: "tests/test_semantic_layer.py -k resolver or adapter or policy"
        status: pass
    human_judgment: false
  - id: D2
    description: "Temporal versions, inclusive effective selection, overlap protection, graph policy, projection synchronization, and governance finalization"
    requirement: CTX-04
    verification:
      - kind: integration
        ref: "tests/test_semantic_layer.py tests/test_governance.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "Additive project-scoped version API with static effective-route precedence and Concept write delegation"
    requirement: CTX-02
    verification:
      - kind: integration
        ref: "tests/test_semantic_layer.py::test_additive_version_routes_preserve_concept_compatibility_and_static_precedence"
        status: pass
    human_judgment: false
  - id: D4
    description: "202608200016 SQLite bootstrap/downgrade lifecycle preserving Phase 8 and formal index tables"
    requirement: CTX-04
    verification:
      - kind: integration
        ref: "tests/test_semantic_migration.py::test_semantic_version_migration_bootstraps_one_v1_per_legacy_concept_and_downgrades_safely"
        status: pass
    human_judgment: false

duration: 40min
completed: 2026-08-20
status: complete
---

# Phase 09 Plan 01 Summary

**Governed semantic concept versions now provide transactional temporal meaning, additive compatibility APIs, centralized visibility policy, and a reversible legacy bootstrap migration.**

## Performance

- **Duration:** 40 min
- **Started:** 2026-08-20T18:20:00+08:00
- **Completed:** 2026-08-20T18:59:00+08:00
- **Tasks:** 3
- **Files modified:** 17

## Accomplishments

- Hardened semantic reads with one trusted/candidate/audit policy, twelve explicit entity adapters, deterministic resolver tiers, and bounded typed evidence/provenance.
- Added `SemanticConceptVersion` and transactional version service semantics for initial creation, draft/AI edits, immutable confirmed meaning, inclusive effective selection, status transitions, projection sync, graph filtering, and governance finalization.
- Preserved Phase 8 routes while adding project-scoped list/create/detail/effective/status version routes; shipped 202608200016 with one v1 bootstrap per legacy Concept and downgrade limited to the new table.

## Task Commits

Each TDD task was committed atomically as RED then GREEN:

1. **Task 1: Trace confirmed semantic resolution through policy, adapters, and the existing API** - `bb31126` (test), `541ea1d` (feat)
2. **Task 2: Add temporal versions, transactional Concept delegation, governance finalization, and complete graph policy coverage** - `3a0bf32` (test), `0092b1f` (feat)
3. **Task 3: Expose additive version API and ship the reversible 202608200016 bootstrap migration** - `9718845` (test), `ae41592` (feat)
4. **Independent review remediation: close concurrency, canonical projection, provenance, permission, graph-bound, index, and UAT gaps** - `9e24e2e` (fix)

**Plan metadata:** finalized in the subsequent state-tracking commit.

## Files Created/Modified

- `backend/app/services/semantic/status_policy.py` - shared trusted/candidate/audit status policy.
- `backend/app/services/semantic/entity_adapter.py` - bounded explicit descriptors for all twelve allow-listed entity types.
- `backend/app/services/semantic/version_service.py` - canonical version creation, edits, effective selection, transitions, and legacy projection.
- `backend/app/models/semantic.py` and `backend/app/models/__init__.py` - temporal version model export and constraints/indexes.
- `backend/app/schemas/semantic.py` - strict version payload/read/status schemas and additive Concept effective fields.
- `backend/app/api/semantic.py` - compatibility delegation, additive version routes, and explicit graph visibility mode parameters.
- `backend/app/services/semantic/graph_service.py` and `backend/app/services/governance/workflow.py` - shared status filtering and version workflow targets.
- `backend/alembic/versions/202608200016_semantic_concept_versions.py` - explicit portable schema and retry-safe legacy bootstrap.
- `backend/tests/test_semantic_layer.py`, `backend/tests/test_governance.py`, `backend/tests/test_semantic_migration.py` - RED/GREEN behavioral and lifecycle coverage.

## Decisions Made

- Keep stable Concept identity separate from canonical, date-effective version meaning.
- Require explicit candidate mode for non-confirmed business-fact reads; rejected and deprecated rows remain audit-only.
- Keep bindings and relations identity-level; no version foreign keys were introduced.
- Preserve legacy Concept version counters as compatibility metadata rather than fabricated historical versions.

## Deviations from Plan

- Independent review found and fixed a SQLite overlap-confirmation race, stale legacy projection behavior, incorrect binding provenance, restricted KnowledgeUnit exposure, a graph node-limit off-by-one, missing single-column migration indexes, and the stale UAT migration-head expectation.
- The migration additionally handles an already-present empty version table so retry/bootstrap remains safe when runtime metadata has pre-created the table.

## Issues Encountered

- The SQLite migration fixture's project row required the existing non-null `governance_workflow_enabled` column; the fixture was corrected before the GREEN gate.
- PostgreSQL concurrent-confirmation row-lock staging qualification was not available in this environment. SQLite overlap tests and PostgreSQL-portable `with_for_update` code paths passed static/runtime checks; staging remains an explicit follow-up gate.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

The semantic policy, adapter boundary, canonical temporal version service, governance target, compatibility API, and 016 migration are ready for 09-02 ContextBuilder work. No RegulatoryContext persistence, ContextBuilder implementation, generator, frontend, or Phase 10 file was introduced. PostgreSQL concurrent-confirmation qualification remains open in `.planning/WINDOWS.md`.

## Verification

- `python -m pytest -q tests/test_semantic_layer.py tests/test_governance.py tests/test_semantic_migration.py tests/test_uat.py` — **63 passed, 4 warnings**.
- `python -m pytest -q` — **269 passed, 2 pre-existing Windows-only failures, 5 warnings**.
- `python -m alembic heads` — **202608200016 (head)**.
- `python -m compileall -q app` — **passed**.
- `git diff --name-only 4f84faa..HEAD -- backend` — only the 17 plan-owned semantic/model/service/API/auth/migration/test files; user frontend changes remain outside the plan diff.

## Self-Check: PASSED

- Summary file exists at `.planning/phases/09-regulatory-context/09-01-SUMMARY.md`.
- All six task RED/GREEN commit hashes are present in git history.
- Final focused tests, migration head check, compile check, and diff-scope check passed.

---
*Phase: 09-regulatory-context*
*Plan: 01*
*Completed: 2026-08-20*
