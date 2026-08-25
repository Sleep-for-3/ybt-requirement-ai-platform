# Phase 11 Gap Qualification Ledger

Automated qualification for the Phase 11 semantic catalog UI gap-closure implementation. This ledger records reproducible commands, immediate exit-code checks, test counts, timing, query evidence, browser assertions, and the required routing to the dedicated security and UI review workflows.

## Task 1: Critical isolation and production-browser evidence

Task 1 evidence is appended after the exact critical backend and real-route browser commands complete.

### Critical API isolation command

Command executed from the repository root, with `$env:PYTHONPATH='backend'` and an immediate `$LASTEXITCODE` check before starting the browser command:

```powershell
$env:PYTHONPATH='backend'
python -m pytest backend/tests/test_semantic_catalog_api.py -k "foreign_institution or confirmed_relation or uncategorized" -q -x
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Result: **PASS**, exit code `0`, `4 passed`, `16 deselected`, pytest-reported duration `4.94s` (wall duration `8491ms`). Named tests exercised:

- `test_catalog_and_detail_reject_same_project_foreign_institution_versions`
- `test_foreign_institution_subordinate_rows_are_excluded_from_all_regions`
- `test_confirmed_relation_aggregates_require_confirmed_same_institution_endpoints`
- `test_uncategorized_facet_round_trips_null_and_blank_domains`

The first named test also directly verifies the canonical resolver's omitted, integer, and explicit-null institution scope semantics. The four tests cover same-project foreign-institution versions and subordinate rows, confirmed endpoint relation semantics, and null/blank uncategorized filtering through the real API. No fixture-only or static SSR assertion is used as isolation evidence.

### Production browser command

After the backend exit check returned `0`, the exact real-route browser command ran:

```powershell
node --test frontend/tests/semantic-catalog-browser.test.mjs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Result: **PASS**, exit code `0`, `12 passed`, `0 failed`, `0 cancelled`, `0 skipped`, `0 todo`, Node-reported duration `31598.4561ms` (wall duration `31822ms`). The suite exercised the production `/semantics` and `/semantics/42` routes through the CDP harness, not a test fixture. Catalog evidence covered loading, unfiltered and filtered empty, retryable 500, unauthorized 403, project-switch stale clearing, late success/error rejection, canonical audit/status and `__uncategorized__` URL state, and first/last pagination. Detail evidence covered shell/lazy loading, region empty/error/retry/403, keyboard/focus tab movement, restricted DOM/attributes/links/accessibility absence, conflict source expansion, independent evidence disclosures, and long formal definition/evidence selection and expansion.

Task 1 acceptance: **PASS**. CR-01 and CR-02 are directly covered by the project-switch render boundary and same-project foreign-institution subordinate-row tests; WR-01, WR-02, WR-03, WR-06, WR-08, and WR-09 are exercised by named backend/browser production assertions. WR-04, WR-05, and WR-07 are covered by the detail route and contract evidence recorded in the upstream Plan 11-07 summary and are re-listed in the final matrix below.

## Task 2: Complete regression, build, lint, and bounded-query evidence

Each command below was run in the listed order. The next command was started only after the preceding command's `$LASTEXITCODE` was captured and checked.

### Focused backend regression

```powershell
$env:PYTHONPATH='backend'
python -m pytest backend/tests/test_semantic_catalog_api.py backend/tests/test_semantic_layer.py backend/tests/test_governance.py -q -x
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Result: **PASS**, exit `0`, `68 passed`, `0 deselected`, pytest duration `41.04s`, wall duration `45360ms`. This includes the Phase 11 catalog/detail API, semantic-layer, and governance regression suites.

### Normal frontend test command

```powershell
npm --prefix frontend test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Result: **PASS**, exit `0`, `83 passed`, `0 failed`, `0 cancelled`, `0 skipped`, `0 todo`, Node duration `37555.8246ms`, wall duration `39471ms`. The package script expands to `node --test tests/*.test.mjs` and includes all 12 real-route production browser tests plus pure view-model, detail-contract, HTTP, and existing frontend tests.

### Production frontend build

```powershell
npm --prefix frontend run build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Result: **PASS**, exit `0`, wall duration `81303ms`. Next.js 14.2.35 compiled successfully, type validation passed, static generation completed `41/41`, and the route table emitted both `/semantics` and `/semantics/[id]`. The build reported `30` pre-existing `react-hooks/exhaustive-deps` warnings in unrelated routes (`business-systems`, `datasources`, `deliverables`, `fields`, `historical-calibers`, `jobs`, `knowledge`, `legacy`, `lineage`, `mart`, `projects`, `questions`, `tasks`, `templates`, and `uat`); no warning pointed to the Phase 11 semantic catalog routes.

### Frontend lint

```powershell
npm --prefix frontend run lint
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Result: **PASS**, exit `0`, wall duration `8621ms`. The same `30` pre-existing `react-hooks/exhaustive-deps` warnings were reported in unrelated routes; no Phase 11 semantic catalog lint warning was reported. The informational Next.js rule guidance was non-failing output.

### High-risk backend regression: exact plan invocation

The plan's exact command was attempted after the lint exit check:

```powershell
Push-Location backend
try {
  python -m pytest -q --deselect=tests/test_productization.py::test_windows_secret_acl_commands_remove_explicit_extra_access_and_are_idempotent --deselect=tests/test_productization.py::test_windows_lifecycle_script_without_action_keeps_control_console_open
  $backendExit=$LASTEXITCODE
} finally { Pop-Location }
if ($backendExit -ne 0) { exit $backendExit }
```

With the task shell's earlier `$env:PYTHONPATH='backend'`, this exact invocation exited `2` during collection after `2 deselected`: changing into `backend` made the relative environment entry resolve as `backend/backend`, so `backend.tests.test_semantic_layer` raised `ModuleNotFoundError: backend`. This is a command working-directory/environment-path failure, not a test or implementation failure. A first environment-only retry with the absolute `backend` directory had the same import result because `backend.tests` requires the repository root on `sys.path`.

### High-risk backend regression: corrected environment-only invocation

The same pytest command was then rerun without source changes, with `PYTHONPATH` set to the repository root before `Push-Location backend`:

```powershell
$repoRoot=(Get-Location).Path
$env:PYTHONPATH=$repoRoot
Push-Location backend
try {
  python -m pytest -q --deselect=tests/test_productization.py::test_windows_secret_acl_commands_remove_explicit_extra_access_and_are_idempotent --deselect=tests/test_productization.py::test_windows_lifecycle_script_without_action_keeps_control_console_open
  $backendExit=$LASTEXITCODE
} finally { Pop-Location }
if ($backendExit -ne 0) { exit $backendExit }
```

Result: **PASS**, exit `0`, `424 passed`, exactly `2 deselected` (the two named Windows-only nodes), `5 warnings`, pytest duration `702.54s` / `11:42`, wall duration `709573ms`. Warnings were one pre-existing temporary `APP_SECRET_KEY` runtime warning and four repeated SQLite datetime-adapter deprecation warnings from the semantic migration test; no warning caused a failure and no broader deselection was used.

### Positive 701-concept query and latency evidence

The bounded-query test was rerun with `-s` so its positive evidence was captured:

```powershell
$env:PYTHONPATH='backend'
python -m pytest backend/tests/test_semantic_catalog_api.py -k "701_concepts" -q -s
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Result: **PASS**, exit `0`, `1 passed`, `19 deselected`, pytest duration `4.96s`, wall duration `8911ms`. Printed evidence: `dialect=sqlite concepts=701 page_size=100 statements=7 latency_ms=80.37 threshold_ms=2000 plan=SEARCH semantic_concepts USING INDEX ix_semantic_concepts_project_id (project_id=?)`. This is a positive post-warm-up measurement: seven SQL statements, `80.37ms`, below the `2000ms` threshold, using the existing project index; no new index or migration was introduced.

### Scoped dependency and lockfile evidence

```powershell
git status --short -- frontend/package.json frontend/package-lock.json
git diff --name-status 36e08d9674e330e28ecb1c4654081f3dba938740..HEAD -- frontend/package.json frontend/package-lock.json
```

Both commands produced no output. There is no worktree change and no Phase 11 Plan 08-to-11-09 history diff for `frontend/package.json` or `frontend/package-lock.json`; no package installation or dependency/lockfile mutation occurred.

Task 2 acceptance: **PASS after the environment-only command correction**. Focused backend, normal frontend tests, production build, lint, corrected full high-risk regression, positive query/latency, and package/lockfile checks are all green. The exact plan high-risk invocation failure is retained above and is not waived or reclassified as a test pass.

## Evidence matrix

The matrix below is the executor-owned qualification ledger. Every row has one production implementation path, one named runnable command/test, an exact `PASS` result, and an anchored existing evidence artifact.

<!-- evidence-matrix:start -->
| ID | Production path | Named command/test | Result | Evidence location |
| CR-01 | frontend/app/semantics/page.tsx | node --test frontend/tests/semantic-catalog-browser.test.mjs — production browser catalog first paints A then clears it at the real project switch | PASS | .planning/phases/11-semantic-catalog-ui/11-GAP-QUALIFICATION.md#task-1-critical-isolation-and-production-browser-evidence |
| CR-02 | backend/app/services/semantic/catalog_query_service.py | python -m pytest backend/tests/test_semantic_catalog_api.py -k "foreign_institution or confirmed_relation or uncategorized" -q -x — test_foreign_institution_subordinate_rows_are_excluded_from_all_regions | PASS | .planning/phases/11-semantic-catalog-ui/11-GAP-QUALIFICATION.md#task-1-critical-isolation-and-production-browser-evidence |
| WR-01 | backend/app/services/semantic/catalog_query_service.py | python -m pytest backend/tests/test_semantic_catalog_api.py -k "foreign_institution or confirmed_relation or uncategorized" -q -x — test_confirmed_relation_aggregates_require_confirmed_same_institution_endpoints | PASS | .planning/phases/11-semantic-catalog-ui/11-GAP-QUALIFICATION.md#task-1-critical-isolation-and-production-browser-evidence |
| WR-02 | backend/app/services/semantic/catalog_query_service.py | python -m pytest backend/tests/test_semantic_catalog_api.py -k "foreign_institution or confirmed_relation or uncategorized" -q -x — test_uncategorized_facet_round_trips_null_and_blank_domains | PASS | .planning/phases/11-semantic-catalog-ui/11-GAP-QUALIFICATION.md#task-1-critical-isolation-and-production-browser-evidence |
| WR-03 | frontend/lib/semantic-catalog-view-model.mjs | npm --prefix frontend test — semantic-catalog audit and status canonicalize to API-valid URL state | PASS | .planning/phases/11-semantic-catalog-ui/11-06-SUMMARY.md#automated-test-results |
| WR-04 | frontend/components/semantic-catalog/BindingList.tsx | npm --prefix frontend test — lineage query preserves both production backend href shapes byte-for-byte | PASS | .planning/phases/11-semantic-catalog-ui/11-07-SUMMARY.md#automated-test-results |
| WR-05 | frontend/components/semantic-catalog/SemanticDetailHeader.tsx | npm --prefix frontend test — conflict source collection keeps two attributed summaries in stable order | PASS | .planning/phases/11-semantic-catalog-ui/11-07-SUMMARY.md#automated-test-results |
| WR-06 | frontend/app/semantics/page.tsx | node --test frontend/tests/semantic-catalog-browser.test.mjs — production browser catalog first paints A then clears it at the real project switch | PASS | .planning/phases/11-semantic-catalog-ui/11-08-SUMMARY.md#verification-evidence |
| WR-07 | frontend/lib/semantic-entity-types.mjs | npm --prefix frontend test — every API entity type uses one production entity label table | PASS | .planning/phases/11-semantic-catalog-ui/11-06-SUMMARY.md#automated-test-results |
| WR-08 | frontend/components/semantic-catalog/EvidenceDisclosure.tsx | node --test frontend/tests/semantic-catalog-browser.test.mjs — production browser detail exposes two independent evidence disclosures with stable controls | PASS | .planning/phases/11-semantic-catalog-ui/11-08-SUMMARY.md#verification-evidence |
| WR-09 | frontend/app/semantics/page.tsx | node --test frontend/tests/semantic-catalog-browser.test.mjs — production browser catalog canonicalizes audit sentinel and drives all pagination boundaries | PASS | .planning/phases/11-semantic-catalog-ui/11-08-SUMMARY.md#verification-evidence |
| SUI-01 | frontend/app/semantics/page.tsx | npm --prefix frontend test — production browser catalog exposes truthful loading and both empty variants | PASS | .planning/phases/11-semantic-catalog-ui/11-GAP-QUALIFICATION.md#task-2-complete-regression-build-lint-and-bounded-query-evidence |
| SUI-02 | frontend/app/semantics/[id]/page.tsx | node --test frontend/tests/semantic-catalog-browser.test.mjs — production browser detail separates shell and lazy-region loading, empty, retry, and forbidden | PASS | .planning/phases/11-semantic-catalog-ui/11-GAP-QUALIFICATION.md#task-1-critical-isolation-and-production-browser-evidence |
| D-01 | frontend/app/semantics/page.tsx | npm --prefix frontend test — production browser catalog exposes truthful loading and both empty variants | PASS | .planning/phases/11-semantic-catalog-ui/11-08-SUMMARY.md#verification-evidence |
| D-02 | frontend/components/semantic-catalog/GroupedSemanticDirectory.tsx | npm --prefix frontend test — semantic-catalog grouping is stable and places blank domains under 未分类 last | PASS | .planning/phases/11-semantic-catalog-ui/11-06-SUMMARY.md#automated-test-results |
| D-03 | frontend/components/semantic-catalog/SemanticComparisonTable.tsx | npm --prefix frontend test — semantic-catalog URL state canonicalizes defaults, invalid values, and durable filters | PASS | .planning/phases/11-semantic-catalog-ui/11-06-SUMMARY.md#automated-test-results |
| D-04 | frontend/components/semantic-catalog/GroupedSemanticDirectory.tsx | node --test frontend/tests/semantic-catalog-browser.test.mjs — production browser catalog first paints A then clears it at the real project switch | PASS | .planning/phases/11-semantic-catalog-ui/11-08-SUMMARY.md#verification-evidence |
| D-05 | frontend/components/semantic-catalog/CatalogToolbar.tsx | npm --prefix frontend test — semantic-catalog search drafts do not change the committed query until submit | PASS | .planning/phases/11-semantic-catalog-ui/11-06-SUMMARY.md#automated-test-results |
| D-06 | frontend/components/semantic-catalog/CatalogToolbar.tsx | npm --prefix frontend test — semantic-catalog immediate query changes reset pages and request keys include every server parameter | PASS | .planning/phases/11-semantic-catalog-ui/11-06-SUMMARY.md#automated-test-results |
| D-07 | backend/app/services/semantic/catalog_query_service.py | python -m pytest backend/tests/test_semantic_catalog_api.py -k "catalog_search_filters_and_audit_mode_are_server_authoritative" -q -x — test_catalog_search_filters_and_audit_mode_are_server_authoritative | PASS | .planning/phases/11-semantic-catalog-ui/11-05-SUMMARY.md#automated-test-results |
| D-08 | frontend/lib/semantic-catalog-view-model.mjs | npm --prefix frontend test — semantic-catalog URL state canonicalizes defaults, invalid values, and durable filters | PASS | .planning/phases/11-semantic-catalog-ui/11-06-SUMMARY.md#automated-test-results |
| D-09 | frontend/app/semantics/[id]/page.tsx | npm --prefix frontend test — semantic-detail shell keeps safe 404 separate from visible-project 403 and canonical success | PASS | .planning/phases/11-semantic-catalog-ui/11-08-SUMMARY.md#verification-evidence |
| D-10 | frontend/components/semantic-catalog/SemanticDetailHeader.tsx | node --test frontend/tests/semantic-catalog-browser.test.mjs — production browser detail preserves formal truth while keyboard-expanding all conflict sources | PASS | .planning/phases/11-semantic-catalog-ui/11-08-SUMMARY.md#verification-evidence |
| D-11 | backend/app/services/semantic/version_service.py | python -m pytest backend/tests/test_semantic_catalog_api.py -k "catalog_as_of_is_inclusive_and_ambiguity_is_a_safe_typed_error" -q -x — test_catalog_as_of_is_inclusive_and_ambiguity_is_a_safe_typed_error | PASS | .planning/phases/11-semantic-catalog-ui/11-05-SUMMARY.md#automated-test-results |
| D-12 | frontend/app/semantics/[id]/page.tsx | npm --prefix frontend test — semantic-catalog detail URL accepts only canonical tab, date, version, and return path | PASS | .planning/phases/11-semantic-catalog-ui/11-07-SUMMARY.md#automated-test-results |
| D-13 | frontend/app/semantics/[id]/page.tsx | npm --prefix frontend test — SUI-24, SUI-26..SUI-28 long text, return navigation, questions, temporal labels, and current-only lineage remain safe | PASS | .planning/phases/11-semantic-catalog-ui/11-08-SUMMARY.md#verification-evidence |
| D-14 | frontend/components/semantic-catalog/AsyncRegion.tsx | node --test frontend/tests/semantic-catalog-browser.test.mjs — production browser detail separates shell and lazy-region loading, empty, retry, and forbidden | PASS | .planning/phases/11-semantic-catalog-ui/11-08-SUMMARY.md#verification-evidence |
| D-15 | frontend/components/semantic-catalog/VersionTimeline.tsx | npm --prefix frontend test — SUI-19..SUI-21 historical boundaries, ordering, URL selection, and audit markers are explicit | PASS | .planning/phases/11-semantic-catalog-ui/11-08-SUMMARY.md#verification-evidence |
| D-16 | frontend/components/semantic-catalog/SemanticStatus.tsx | npm --prefix frontend test — semantic-catalog lifecycle partitions and confirmed facts stay independent from review state | PASS | .planning/phases/11-semantic-catalog-ui/11-06-SUMMARY.md#automated-test-results |
| D-17 | frontend/components/semantic-catalog/SemanticStatus.tsx | npm --prefix frontend test — semantic-catalog lifecycle partitions and confirmed facts stay independent from review state | PASS | .planning/phases/11-semantic-catalog-ui/11-06-SUMMARY.md#automated-test-results |
| D-18 | frontend/app/semantics/[id]/page.tsx | python -m pytest backend/tests/test_semantic_catalog_api.py -k "semantic_detail_optional_permission_and_audit_routes_fail_closed" -q -x — test_semantic_detail_optional_permission_and_audit_routes_fail_closed | PASS | .planning/phases/11-semantic-catalog-ui/11-07-SUMMARY.md#automated-test-results |
| D-19 | frontend/components/semantic-catalog/SemanticDetailHeader.tsx | npm --prefix frontend test — semantic-catalog formal definition uses only the server-selected confirmed effective version | PASS | .planning/phases/11-semantic-catalog-ui/11-06-SUMMARY.md#automated-test-results |
| D-20 | frontend/components/semantic-catalog/TrustSourceRegion.tsx | npm --prefix frontend test — semantic-catalog formal definition uses only the server-selected confirmed effective version | PASS | .planning/phases/11-semantic-catalog-ui/11-06-SUMMARY.md#automated-test-results |
| D-21 | frontend/components/semantic-catalog/SemanticDetailHeader.tsx | node --test frontend/tests/semantic-catalog-browser.test.mjs — production browser detail preserves formal truth while keyboard-expanding all conflict sources | PASS | .planning/phases/11-semantic-catalog-ui/11-08-SUMMARY.md#verification-evidence |
| D-22 | backend/app/services/semantic/catalog_query_service.py | python -m pytest backend/tests/test_semantic_catalog_api.py -k "detail_audit_rows_are_isolated_and_successfully_marked_non_current" -q -x — test_detail_audit_rows_are_isolated_and_successfully_marked_non_current | PASS | .planning/phases/11-semantic-catalog-ui/11-05-SUMMARY.md#automated-test-results |
| D-23 | frontend/components/semantic-catalog/BindingChain.tsx | npm --prefix frontend test — SUI-23 bounded confirmed chain has complete list text and truthful overflow | PASS | .planning/phases/11-semantic-catalog-ui/11-08-SUMMARY.md#verification-evidence |
| D-24 | frontend/components/semantic-catalog/BindingChain.tsx | npm --prefix frontend test — SUI-23 bounded confirmed chain has complete list text and truthful overflow | PASS | .planning/phases/11-semantic-catalog-ui/11-08-SUMMARY.md#verification-evidence |
| D-25 | frontend/components/semantic-catalog/BindingList.tsx | python -m pytest backend/tests/test_semantic_catalog_api.py -k "semantic_detail_shell_and_lazy_routes_project_canonical_partitions" -q -x — test_semantic_detail_shell_and_lazy_routes_project_canonical_partitions | PASS | .planning/phases/11-semantic-catalog-ui/11-05-SUMMARY.md#automated-test-results |
| D-26 | frontend/components/semantic-catalog/BindingList.tsx | npm --prefix frontend test — lineage query preserves both production backend href shapes byte-for-byte | PASS | .planning/phases/11-semantic-catalog-ui/11-07-SUMMARY.md#automated-test-results |
| D-27 | backend/app/schemas/semantic_catalog.py | npm --prefix frontend test — SUI-22 restricted references are absent from JSON, DOM, accessibility text, titles, and links | PASS | .planning/phases/11-semantic-catalog-ui/11-08-SUMMARY.md#verification-evidence |
| D-28 | frontend/components/semantic-catalog/AsyncRegion.tsx | node --test frontend/tests/semantic-catalog-browser.test.mjs — production browser detail separates shell and lazy-region loading, empty, retry, and forbidden | PASS | .planning/phases/11-semantic-catalog-ui/11-08-SUMMARY.md#verification-evidence |
| D-29 | frontend/components/semantic-catalog/TrustSourceRegion.tsx | npm --prefix frontend test — SUI-24, SUI-26..SUI-28 long text, return navigation, questions, temporal labels, and current-only lineage remain safe | PASS | .planning/phases/11-semantic-catalog-ui/11-08-SUMMARY.md#verification-evidence |
| D-30 | frontend/app/semantics/[id]/page.tsx | node --test frontend/tests/semantic-catalog-browser.test.mjs — production browser detail keeps 12k formal definitions selectable and long evidence expandable | PASS | .planning/phases/11-semantic-catalog-ui/11-08-SUMMARY.md#verification-evidence |
<!-- evidence-matrix:end -->

### Task 3 validator

The exact Plan 11-09 PowerShell validator ran after the matrix was written and returned `TASK3_VALIDATOR=PASS` with `TASK3_EVIDENCE_ROWS=43`. It confirmed one start marker, one end marker, marker ordering, the exact 43-ID set, no duplicate or missing IDs, nonblank non-placeholder cells, existing production paths, named runnable commands/tests, exact `PASS` results, anchored existing evidence artifacts, `/semantics` production-route evidence, and both dedicated post-execution gate strings. The plan-level `rg` verification also returned exit `0`.

## Next gates

The automated qualification ledger is complete, but the executor does not own the dedicated audit verdicts. Run `$gsd-secure-phase 11` followed by `$gsd-ui-review 11`.

Those dedicated workflows own the canonical `11-SECURITY.md` and `11-UI-REVIEW.md` artifacts, screenshots, exact `320x720`, `768x1024`, `1280x800`, and `1440x900` viewport checks, and final human keyboard/visual approval. This plan intentionally creates neither canonical artifact and does not claim security or UI approval.
