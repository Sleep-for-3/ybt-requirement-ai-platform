---
phase: 11-semantic-catalog-ui
plan: 05
subsystem: api
tags: [fastapi, sqlalchemy, semantic-catalog, institution-isolation, temporal, audit, tdd]

requires:
  - phase: 11-semantic-catalog-ui
    plan: 01
    provides: authoritative set-based catalog projection and canonical effective-version integration
  - phase: 11-semantic-catalog-ui
    plan: 04
    provides: governed detail shell, lazy-region partitions, audit projections, and bounded traceability
provides:
  - backward-compatible institution-scoped canonical effective-version resolution with distinct omitted, integer, and explicit-null semantics
  - one authorized Project institution boundary across semantic versions, bindings, relations, questions, audits, lineage rows, counts, and chains
  - trusted relation aggregates requiring confirmed institution-visible source and target concepts
  - truthful uncategorized filtering for null and whitespace-only domains with consistent totals, facets, ordering, and pagination
affects: [11-06, 11-07, 11-08, 11-09, semantic-catalog-api, semantic-detail-api]

actuals:
  tokens: 9879
  tasks: 3
  commits: 6

tech-stack:
  added: []
  patterns:
    - named sentinel preserving omitted versus explicit-null scope semantics
    - equality-or-null institution predicates applied before subordinate counts and projections
    - aliased confirmed endpoint joins for trusted relation aggregates
    - normalized wire sentinel matching over one filtered catalog population

key-files:
  created: []
  modified:
    - backend/app/services/semantic/version_service.py
    - backend/app/services/semantic/catalog_query_service.py
    - backend/tests/test_semantic_catalog_api.py

key-decisions:
  - "Keep UNSCOPED_INSTITUTION as the default so existing callers remain unscoped, while an integer requires equality and explicit None requires IS NULL on both concept and version rows."
  - "Apply the authorized Project institution predicate before every institution-bearing subordinate count or projection, including explicit-null Projects."
  - "Count a trusted relation only when the relation row and both endpoint concepts are same-scope confirmed facts."
  - "Keep __uncategorized__ stable on the wire while matching and faceting both null and trimmed-blank business domains."

patterns-established:
  - "Institution scope seam: omitted, integer, and explicit-null resolver calls are distinct and regression-tested."
  - "Trusted relation seam: source and target aliases independently satisfy project, institution, and confirmed predicates."
  - "Uncategorized seam: matching, sorting, facets, totals, and pagination share the normalized filtered population."

requirements-completed: [SUI-01, SUI-02]

coverage:
  - id: D1
    description: "Catalog and detail formal definitions reject same-project foreign-institution semantic versions without legacy or AI fallback."
    requirement: SUI-02
    verification:
      - kind: integration
        ref: "backend/tests/test_semantic_catalog_api.py#test_catalog_and_detail_reject_same_project_foreign_institution_versions"
        status: pass
    human_judgment: false
  - id: D2
    description: "All institution-bearing subordinate semantic projections and trusted relation aggregates share the authorized Project boundary."
    requirement: SUI-02
    verification:
      - kind: integration
        ref: "backend/tests/test_semantic_catalog_api.py#foreign_institution, confirmed_relation, and audit_rows focused gate"
        status: pass
    human_judgment: false
  - id: D3
    description: "The uncategorized facet round-trips null and blank domains while the hardened 701-concept projection remains set-based and bounded."
    requirement: SUI-01
    verification:
      - kind: integration
        ref: "backend/tests/test_semantic_catalog_api.py#test_uncategorized_facet_round_trips_null_and_blank_domains"
        status: pass
      - kind: performance
        ref: "backend/tests/test_semantic_catalog_api.py#test_semantic_catalog_701_concepts_uses_existing_index_with_bounded_queries"
        status: pass
    human_judgment: false

duration: 17min
completed: 2026-08-25
status: complete
---

# Phase 11 Plan 05: Institution Isolation and Catalog Population Integrity Summary

**Canonical formal meaning and every subordinate semantic projection now honor the authorized institution boundary, while trusted relation and uncategorized catalog aggregates remain truthful and bounded.**

## Performance

- **Duration:** 17 min
- **Started:** 2026-08-25T09:24:39Z
- **Completed:** 2026-08-25T09:42:05Z
- **Tasks:** 3
- **Implementation/test files modified:** 3

## Accomplishments

- Added `UNSCOPED_INSTITUTION` to preserve source compatibility while distinguishing omitted scope from integer equality and explicit-null `IS NULL` scope on both canonical concept and version rows.
- Passed the authorized Project institution explicitly through every Phase 11 formal resolver call and kept `SemanticConceptVersion` as the sole formal source.
- Scoped candidate versions, partition counts/rows, confirmed bindings, relations, questions, audits, lineage bindings/nodes/edges, and catalog aggregates before DTO construction.
- Rebuilt trusted relation IDs with confirmed source and target aliases under the same project/institution boundary, excluding draft, rejected, deprecated, and foreign endpoints.
- Made `__uncategorized__` match null and trimmed-blank business domains and derive items, totals, facets, ordering, and pagination from the same normalized population.
- Retained the existing database indexes: the 701-concept SQLite request used seven statements and the existing project index.

## Task Commits

1. **Task 1 RED:** `5282321` — expose same-project foreign-institution formal-version leakage and resolver three-state semantics.
2. **Task 1 GREEN:** `0ee43cc` — add institution-aware canonical temporal resolution and Phase 11 propagation.
3. **Task 2 RED:** `17a8bfc` — expose subordinate version/binding/relation/question/audit contamination and endpoint-state drift.
4. **Task 2 GREEN:** `d4301bd` — scope every subordinate projection/count and require confirmed same-scope relation endpoints.
5. **Task 3 RED:** `a5e7760` — expose the uncategorized facet round-trip failure across totals, facets, pagination, and order.
6. **Task 3 GREEN:** `fdb1600` — normalize uncategorized matching, sorting, and facets without a migration or index.

## TDD Gate Compliance

- Task 1 RED failed because the real catalog returned `FOREIGN_INSTITUTION_FORMAL_DEFINITION`; GREEN passed the exact route/resolver test.
- Task 2 RED failed because a foreign binding entered catalog JSON; GREEN passed four focused institution/relation/audit cases and the full catalog suite.
- Task 3 RED returned total `0` for `domain=__uncategorized__`; GREEN returned the two null/blank concepts with matching facets and stable pagination.
- Each RED commit precedes its GREEN commit. No separate refactor commit was needed.

## Files Modified

- `backend/app/services/semantic/version_service.py` — Named unscoped sentinel plus equality/null predicates across joined concept and version rows.
- `backend/app/services/semantic/catalog_query_service.py` — Explicit Phase 11 resolver scope, subordinate institution predicates, aliased confirmed relation endpoints, and uncategorized normalization.
- `backend/tests/test_semantic_catalog_api.py` — Adversarial formal/subordinate fixtures, resolver three-state regression, relation contamination coverage, and uncategorized round-trip evidence.

## Decisions Made

- Omitted resolver scope remains backward compatible; only an explicitly supplied `institution_id` activates institution filtering.
- Explicit `None` is a real scope meaning both `SemanticConcept.institution_id IS NULL` and `SemanticConceptVersion.institution_id IS NULL`, not an alias for omission.
- A confirmed relation row is insufficient for trusted aggregates unless both endpoint identities are also confirmed and institution-visible.
- Rejected/deprecated semantic data remains audit-only, and `audit.read` never broadens institution scope.
- The query-count and latency evidence did not justify any migration or new index.

## Deviations from Plan

None - plan executed exactly as written.

## Automated Test Results

- Task 1 exact formal isolation test — **1 passed**.
- Task 2 `foreign_institution or confirmed_relation or audit_rows` gate — **4 passed, 15 deselected**.
- Task 3 uncategorized plus 701-concept gate — **2 passed**; seven statements, 182.99 ms, existing SQLite `ix_semantic_concepts_project_id` index.
- Full focused catalog suite — **20 passed**.
- Plan-level combined catalog, semantic-layer, and governance regression — **68 passed** in 38.96 seconds.

## Security and Threat Coverage

- T-11-05-01 closed by the explicit sentinel and joined concept/version institution predicates.
- T-11-05-02 closed by applying the Project institution policy before subordinate row counts, partitions, audit events, questions, and chains.
- T-11-05-03 closed by confirmed source/target aliases under project/institution scope.
- T-11-05-04 remained within the existing performance envelope at seven SQL statements; no new database surface was introduced.
- No unplanned endpoint, auth path, schema, package, migration, index, file-access pattern, or production action was added.

## Known Stubs

None. Empty lists and nullable values in the touched code are intentional bounded/empty projection states or function defaults, not unwired data.

## Issues Encountered

None. The existing test that treated a confirmed edge to a draft endpoint as trusted was updated to retain a confirmed-to-confirmed positive case, as required by the plan.

## User Setup Required

None - no package, environment variable, migration, index, external service, or production operation was added.

## Next Phase Readiness

- Plan 11-06 can consume institution-safe authoritative catalog totals, facets, and formal definitions.
- Plans 11-07 through 11-09 can verify traceability, production interactions, security, and UI behavior without the former subordinate cross-institution contamination.
- Frontend and unrelated user WIP remained outside all six task commits.

## Self-Check: PASSED

The three implementation/test files, this summary, and commits `5282321`, `0ee43cc`, `17a8bfc`, `d4301bd`, `a5e7760`, and `fdb1600` were found. The realized plan diff contains only the three declared backend files, no deletions, and no staged user WIP.

---
*Phase: 11-semantic-catalog-ui*
*Completed: 2026-08-25*
