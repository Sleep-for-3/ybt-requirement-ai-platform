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
