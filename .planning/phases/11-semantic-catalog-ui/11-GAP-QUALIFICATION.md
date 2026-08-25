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
