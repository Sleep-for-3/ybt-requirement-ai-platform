---
phase: 11-semantic-catalog-ui
plan: 04
subsystem: api
tags: [fastapi, sqlalchemy, semantic-catalog, authorization, temporal, audit, tdd]

requires:
  - phase: 11-semantic-catalog-ui
    plan: 01
    provides: authenticated semantic catalog API, canonical version resolution, redacted references, and set-based catalog projections
provides:
  - strict additive DTOs for the semantic detail shell and six independently authorized lazy regions
  - canonical temporal detail projections with separate confirmed, candidate, and audit partitions
  - permission-safe redaction, audit isolation, bounded semantic chains, and set-based related-data loading
  - focused security, temporal, audit, N+1, chain-cap, and 701-concept query-plan regression coverage
affects: [11-03, semantic-detail-ui, semantic-catalog-api, governance-audit]

actuals:
  tokens: 23490
  tasks: 3
  commits: 6

tech-stack:
  added: []
  patterns:
    - strict projection-only DTOs with discriminated readable and restricted references
    - standalone permission-gated lazy regions over canonical semantic source tables
    - set-based partition queries with stable 100-row region and 13-node chain caps
    - empirical query-plan gate before any index or migration proposal

key-files:
  created: []
  modified:
    - backend/app/schemas/semantic_catalog.py
    - backend/app/services/semantic/catalog_query_service.py
    - backend/app/api/semantic_catalog.py
    - backend/tests/test_semantic_catalog_api.py

key-decisions:
  - "Resolve every formal detail meaning only from SemanticConceptVersion; a missing confirmed version remains null while AI and draft versions stay separate candidates."
  - "Authorize each optional lazy region independently and return HTTP 403 for a visible project when its region permission is absent."
  - "Construct restricted references before serialization with only entity_type and restricted=true, never protected identifiers or display metadata."
  - "Keep rejected and deprecated rows audit-only, require audit.read for explicit audit access, and mark audit events non-current."
  - "Retain existing indexes because the measured 701-concept SQLite plan used an existing project index and completed far below the execution threshold."

patterns-established:
  - "Detail temporal seam: inclusive as_of resolution delegates to resolve_effective_versions and surfaces ambiguity as typed HTTP 409."
  - "Lazy authorization seam: project visibility is checked before region permission, preserving safe 404 versus explicit 403 behavior."
  - "Bounded projection seam: confirmed, candidate, and audit partitions expose total, returned, limit, overflow, and truncated metadata."

requirements-completed: [SUI-02]

coverage:
  - id: D1
    description: "The detail shell and all lazy regions expose strict canonical temporal, governance, and bounded partition contracts."
    requirement: SUI-02
    verification:
      - kind: integration
        ref: "backend/tests/test_semantic_catalog_api.py#detail DTO, shell, route, temporal, and partition tests"
        status: pass
    human_judgment: false
  - id: D2
    description: "Project isolation, optional-region authorization, audit.read, and restricted-reference minimization fail closed."
    requirement: SUI-02
    verification:
      - kind: integration
        ref: "backend/tests/test_semantic_catalog_api.py#isolation, audit, optional permission, and redaction tests"
        status: pass
    human_judgment: false
  - id: D3
    description: "Set-based detail projections remain bounded and representative catalog loading avoids per-row query growth."
    requirement: SUI-02
    verification:
      - kind: performance
        ref: "backend/tests/test_semantic_catalog_api.py#701-concept SQLite EXPLAIN, latency, statement-count, and chain-cap tests"
        status: pass
    human_judgment: false

duration: 26min
completed: 2026-08-25
status: complete
---

# Phase 11 Plan 04: Semantic Detail Backend Projections Summary

**Strict additive semantic detail APIs with canonical temporal facts, independently authorized lazy regions, audit-only history, pre-serialization redaction, bounded chains, and measured set-based performance**

## Performance

- **Duration:** 26 min
- **Started:** 2026-08-25T05:31:21Z
- **Completed:** 2026-08-25T05:57:00Z
- **Tasks:** 3
- **Files modified:** 4 implementation/test files

## Accomplishments

- Added strict projection-only DTOs for the detail shell, bindings, relations, evidence, lineage, governance, and versions without introducing a persisted fact store or changing semantic mutation behavior.
- Added seven read-only routes that preserve project/institution scope, safe 404 versus 403 distinctions, independent lazy-region permissions, and explicit `audit.read` enforcement.
- Kept formal meaning canonical: inclusive `as_of` resolution uses `SemanticConceptVersion`, ambiguous confirmed intervals return typed HTTP 409, and AI/draft candidates never become the formal definition.
- Minimized restricted related references before serialization and isolated rejected/deprecated rows from all default and trusted partitions and chain output.
- Batched related entities, versions, reviews, questions, counts, lineage references, and aggregates with fixed region and chain caps.
- Added endpoint regressions for the complete backend contract and captured representative 701-concept query-plan, query-count, and latency evidence.

## Task Commits

Each TDD gate was committed atomically:

1. **Task 1 RED: Define strict semantic detail DTO contract** - `520fa90` (test)
2. **Task 1 GREEN: Define strict semantic detail projections** - `40e1eae` (feat)
3. **Task 2 RED: Define governed semantic detail route behavior** - `efe65c2` (test)
4. **Task 2 GREEN: Implement governed semantic detail routes** - `3383513` (feat)
5. **Task 3 RED: Add detail security and performance regressions** - `cd6553e` (test)
6. **Task 3 GREEN: Align unresolved question lifecycle** - `2fe8c8b` (fix)

## TDD Gate Compliance

- Task 1 RED failed at import because the strict detail DTOs did not exist; Task 1 GREEN passed all focused DTO and catalog tests.
- Task 2 RED returned HTTP 404 because the detail route did not exist; Task 2 GREEN passed the combined catalog and semantic compatibility suites.
- Task 3 RED produced `1 failed, 12 passed` because the catalog aggregate counted only `open` questions while the canonical unresolved lifecycle also includes `assigned` and `answered`.
- Task 3 GREEN passed `16/16` focused catalog tests and `34/34` combined semantic tests.
- No separate refactor commit was needed; the projection service is already divided along shell and lazy-region seams with shared strict helpers.

## Files Created/Modified

- `backend/app/schemas/semantic_catalog.py` - Strict detail, readable/restricted reference, partition, bounded metadata, chain, evidence, lineage, governance, and version DTOs.
- `backend/app/services/semantic/catalog_query_service.py` - Canonical detail shell and lazy projections, authorization-aware reference construction, audit partitioning, set-based related lookups, stable caps, and full unresolved-question aggregation.
- `backend/app/api/semantic_catalog.py` - Seven additive read-only detail routes with project visibility, per-region permission, and audit authorization checks.
- `backend/tests/test_semantic_catalog_api.py` - DTO, route, isolation, temporal, ambiguity, candidate, review, question, audit, redaction, chain-cap, N+1, and 701-concept performance regressions.

## Decisions Made

- Formal detail fields are never synthesized from the mutable legacy concept row. `effective_version` is nullable, while candidate versions are explicit and separate.
- Detail shell access requires `project.view`; evidence additionally requires `knowledge.search`, lineage requires `lineage.view`, and any explicit audit projection requires `audit.read`.
- A restricted reference is a different strict DTO, not a readable DTO with values later masked. Its serialized shape is exactly `entity_type` and `restricted=true`.
- Rejected and deprecated bindings, relations, versions, and audit events remain outside default/trusted results and never contribute to the trusted chain.
- Chain output is one concept plus at most four target, four mart, and four source nodes; overflow is reported rather than silently implied complete.
- The execution evidence did not justify an index or migration. SQLite used the existing project-scope index, the query count stayed fixed at seven statements, and the measured request remained below the 2,000 ms gate.

## Query-Plan and Latency Evidence

Representative local evidence was captured with 701 confirmed concepts and 701 canonical confirmed versions:

- **Database:** SQLite in-memory test database. This is explicitly not PostgreSQL evidence.
- **Request:** trusted semantic catalog, `page_size=100`, `as_of=2026-08-25`, after one warm request.
- **SQL statements:** 7 for the measured request; the regression gate is at most 12.
- **Measured latency:** 69.33 ms; the execution gate is 2,000 ms.
- **SQLite EXPLAIN QUERY PLAN:** `SEARCH semantic_concepts USING INDEX ix_semantic_concepts_project_id (project_id=?)`.
- **Decision:** no migration or new index. The existing index was selected, statement count was bounded, and latency was well below the execution gate.

The latency is a representative local regression measurement, not a production benchmark. PostgreSQL query-plan evidence was unavailable in this execution environment and was not fabricated.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test Bug] Preserved an ORM identifier before session close**
- **Found during:** Task 2 GREEN
- **Issue:** A route assertion accessed `related.id` after the fixture session committed and closed, causing `DetachedInstanceError` instead of testing the API response.
- **Fix:** Captured the scalar identifier while the session was active and asserted against that stable value.
- **Files modified:** `backend/tests/test_semantic_catalog_api.py`
- **Committed in:** `3383513`

**2. [Rule 1 - Bug] Counted the complete unresolved question lifecycle**
- **Found during:** Task 3 RED/GREEN
- **Issue:** The detail shell correctly treated `open`, `assigned`, and `answered` as unresolved, but the catalog aggregate counted only `open` rows.
- **Fix:** Reused the canonical `_OPEN_QUESTION_STATUSES` tuple in the set-based catalog count query.
- **Files modified:** `backend/app/services/semantic/catalog_query_service.py`
- **Committed in:** `2fe8c8b`

### Execution Environment Adjustment

- The plan's pytest commands were run with `PYTHONPATH=backend` because this repository does not install `app` as a top-level package in the current shell. No package or source-path configuration was changed.

---

**Total deviations:** 2 auto-fixed bugs and 1 test-command environment adjustment.
**Impact on plan:** Both fixes were narrow correctness changes inside the allowed files. No dependency, schema, index, mutation API, or architecture change was introduced.

## Verification Results

- `PYTHONPATH=backend python -m pytest backend/tests/test_semantic_catalog_api.py -q -s` - **16 passed**; emitted the 701-concept SQLite evidence above.
- `PYTHONPATH=backend python -m pytest backend/tests/test_semantic_catalog_api.py backend/tests/test_semantic_layer.py -q` - **34 passed, 0 failed, 0 skipped** in 29.44 seconds.
- TDD history contains three RED commits followed by their GREEN commits in order.
- Diff scope contains exactly the four allowed backend implementation/test files; no migration, model, package, frontend detail component, or semantic mutation file changed.

## Security and Threat Coverage

- Visible project without `project.view` returns HTTP 403; a project outside the principal's visibility returns safe HTTP 404.
- Forbidden optional evidence access returns HTTP 403, allowing region-level unauthorized UI state.
- Audit routes deny principals without `audit.read`; successful audit events include `non_current=true`.
- Restricted references are inspected as JSON and contain no identifier, name, code, href, title, or metadata keys.
- All new endpoints and authorization boundaries were already enumerated in the plan threat model; no unplanned threat surface was introduced.

## Known Stubs

None. Empty list defaults are intentional strict DTO representations for empty lazy regions, not mock data or unwired UI values.

## Issues Encountered

- SQLite selected the existing single-column project index rather than the composite project/status index for the ordered representative query. Measured query count and latency remained well within the evidence gate, so this is not grounds for a migration.
- PostgreSQL was not available for a truthful `EXPLAIN` run. The evidence and its database limitation are recorded explicitly.

## User Setup Required

None - no packages, environment variables, migrations, indexes, external services, or mutation workflows were added.

## Next Phase Readiness

- Plan 11-03 can consume the strict shell and six lazy-region contracts with explicit loading, empty, forbidden, retry, candidate, audit, and ambiguity states.
- Route destinations are limited to the existing canonical allow-list; unsupported entity families intentionally expose no invented navigation.
- The complete Phase 11 verification should retain a real PostgreSQL query-plan check if a representative environment becomes available, but this is not required to claim the local regression suite passed.

## Self-Check: PASSED

All four implementation/test files, this summary, and commits `520fa90`, `40e1eae`, `efe65c2`, `3383513`, `cd6553e`, and `2fe8c8b` were found. The plan diff contains no deleted files and no changes outside the allowed backend scope.

---
*Phase: 11-semantic-catalog-ui*
*Completed: 2026-08-25*
