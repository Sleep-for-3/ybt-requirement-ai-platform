# Production E2E Product Review (2026-09-19)

> Latest production status: this report is superseded by
> `docs/handoff/production-product-optimization-aefe738.md`.
> The production release is now `aefe738`, with a 13/13 E2E pass,
> real-model success for both generated sections, and a confirmed direct
> source-to-regulatory-target path. The historical sections below remain as
> evidence for the earlier `3494894` and `f0825b4` investigations.

## Status

- Production follow-up deployed `3494894`, which contains the `01020be` client-id fix, after this review began. `origin/main` points to `3494894`.
- Production backend, worker, beat, embedding, and frontend were verified healthy; backend health reported all 11 checks healthy and Alembic revision `202609180039`.
- The production frontend bundle contains `client_request_id` and no longer contains the old `event.currentTarget.reset` defect.
- No password was reset or changed. `smoke_admin` was not modified.
- No production project was physically deleted. All lifecycle changes use suspend/restore.
- No production database, credential, token, `.env` file, build output, or uploaded customer file is part of this report.

## Database Conclusion

The original project-creation failure was not caused by SQLite, WSL PostgreSQL, or server PostgreSQL. It was a browser-side React event-timing defect:

1. The project POST completed successfully.
2. The handler awaited the response.
3. It then read `event.currentTarget`, which React had already cleared, and called `reset()` on null.
4. The UI reported failure even though the project existed, so retrying created another row.

The same frontend behavior occurs against every database backend. WSL verification was nevertheless completed against PostgreSQL `16.15`; the production compose contract also uses PostgreSQL 16. The migration chain reached `202609180039`, and repeating the same project request key returned the same project row.

The fix now snapshots `formElement` before the `await`, and project creation uses a stable client request id. A unique database index provides the final concurrency guard.

## Project Lifecycle Decision

Projects are not hard-deleted. A project is the isolation boundary for permissions, assets, lineage, scripts, requirements, reviews, UAT, deliveries, background jobs, and audit history. Hard deletion would break historical references and auditability.

The implemented lifecycle is:

- active: visible to normal project selection and work entry points;
- suspended: hidden from normal selection, but all history and explicit references remain;
- restored: returns to active status without recreating or rewriting history.

Suspension and restoration require institution admin/security admin (or legacy platform-admin) permission and write an audit record.

## Duplicate Production Projects

Read-only production statistics found 13 likely duplicate rows left by the old frontend defect:

| Project name | Institution id | Copies |
|---|---:|---:|
| 天津农商银行 | 1 | 8 |
| 天津农商银行智能监管平台 | 1 | 3 |
| 天津农商银行智能监管平台 | 2 | 2 |

They were not automatically deleted or modified. An administrator should keep the row that owns real work and suspend only the confirmed empty duplicates after checking assets, requirements, reviews, deliveries, and audit references.

Two dedicated acceptance projects remain as suspended history:

- project `25`: API/browser idempotency acceptance;
- project `26`: browser creation and architecture configuration acceptance.

## Browser Findings

A real production browser session was established through a backend-signed, short-lived session without exposing or storing the token. Password login was not used because the documented legacy password does not match the real account and changing it was forbidden.

Passed in production browser:

- `/projects` loads with 25 cards and no application error;
- project `25` restore and suspend round-trip through the real UI;
- suspended project disappears from normal project selection;
- project creation completes without the old reset exception;
- created project `26` is suspended after acceptance;
- `/resources/architecture?projectId=26` loads and saves the two-layer example (`HTTP 200`).

The browser review then found a second deployment-only defect:

- `/resources/import?projectId=26` showed `Application error: a client-side exception has occurred`;
- console error: `TypeError: crypto.randomUUID is not a function`;
- cause: `crypto.randomUUID()` is available only in secure browser contexts, while production is reached through plain HTTP by IP.

The fix in `01020be` centralizes client id generation and falls back to `crypto.getRandomValues`, then to `Date.now()` plus `Math.random()` when Web Crypto is absent. The same helper is now used by project creation, batch import, architecture layer creation, reverse requirement creation, and requirement generation submission.

## Verification

Deterministic/local verification completed:

- targeted client-id, project-contract, and declaration tests: `8 passed`;
- frontend full suite: `148 passed`;
- TypeScript: passed;
- isolated production Next build: 52 pages generated successfully;
- real Next production browser with `crypto.randomUUID` removed: batch-import page rendered, default layers loaded, no page or console errors.

Earlier isolated deterministic and Mock verification remains valid for batch import, reverse requirements, policy comparison, review, delivery, Word/Excel, and recheck flows. Those results are not represented here as a real external-model acceptance test.

Evidence paths:

- production project page: `.local-run/production-e2e-20260919/projects-production-smoke.png`;
- production project lifecycle: `.local-run/production-e2e-20260919/project-lifecycle-production.json`;
- production project creation: `.local-run/production-e2e-20260919/project-created-production.png`;
- production architecture save: `.local-run/production-e2e-20260919/architecture-project26.png`;
- HTTP fallback browser result: `.local-run/production-e2e-20260919/batch-import-http-fallback-local.json`.

## Local Database and Follow-up Verification (2026-09-19)

- The WSL PostgreSQL container `ybt-pg-host` was read-only checked and reports PostgreSQL `16.15`; production and the compose contract use PostgreSQL 16 as well.
- The currently running local API uses the workspace-managed Windows PostgreSQL on `127.0.0.1:5432`, not the WSL container on `15432`. The WSL database `ybt_pg_smoke` is currently at Alembic `202609120027`, and `ybt_host_probe` has no Alembic version table, so either WSL database would need the incremental migration to `202609180039` before the current API connects to it.
- The local Windows development database initially reported Alembic `202609180038` while the application expected `039`. A logical backup was written to `.local-run/backups/ybt_local-before-202609180039-20260919-020754.dump`, then the existing Alembic migration was applied. The result is `202609180039`, `projects.creation_request_id` is nullable, all six pre-existing local projects remain, and backend readiness returned `ready`.
- The open local browser was serving a stale JavaScript chunk from before the fix. The current `3000` bundle contains `client_request_id` and the fixed `formElement.reset()` path. Refreshing or restarting that page is required to discard the old chunk; the database backend does not change this.
- A current-source production build and browser lifecycle regression passed against an isolated in-memory SQLite API: create, same-key replay returning the same project, suspend, hide from the selector, restore, and zero page errors. This is recorded as `databaseBackend=sqlite` and `realPostgresql=false`; it is not represented as a PostgreSQL browser test.
- `projects-lifecycle.browser.acceptance.mjs` now requires the caller to declare `sqlite` or `postgresql` as its fourth argument. This removes the former hard-coded `realPostgresql: true` result, which could have misreported a non-PostgreSQL run.

The historical production duplicate rows still require administrator review. Keep the project that owns assets, lineage, requirements, reviews, deliveries, or audit references and suspend confirmed empty duplicates; do not hard-delete them.

No real external-model test, production restore drill, or production reverse-requirement end-to-end generation is claimed here.
