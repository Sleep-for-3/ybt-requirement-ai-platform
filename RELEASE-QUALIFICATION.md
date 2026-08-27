# Release Qualification — v2.0.0-rc1 Staging Qualification

## RC identity

- Requested source: GitHub `main` / tag `v2.0.0-rc1`.
- Remote verification on 2026-08-27: `origin/main` resolves to `e872a6533b7edeaf58905c6a71342f172b6f8932`; no `v2.0.0-rc1` tag is published.
- This report therefore qualifies only the public `main` commit `e872a653…`. Local hardening `dd569cb` is not treated as the RC because it is not on GitHub `main`.
- Only `PASS`, `FAIL`, `BLOCKED`, `NOT VALIDATED`, or `N/A` are used.

## Qualification evidence

| Gate | Status | Evidence / blocker |
|---|---|---|
| Clean install / fresh clone | PASS | New shallow clone of GitHub `main` in a fresh temporary directory; clean tree and HEAD `e872a653…`. No repository `.env`, local DB, cache, `.next`, virtualenv, or storage reused. |
| Fresh Alembic empty database | NOT VALIDATED | Docker unavailable; no isolated staging PostgreSQL credentials. Local PostgreSQL 5432 is occupied by an existing development process. |
| Startup / health endpoints | PASS (local only) | Existing local PostgreSQL/Redis/backend/frontend returned live 200, ready 200, and health details 200. This is not staging evidence. |
| PostgreSQL qualification | BLOCKED | No isolated staging PostgreSQL endpoint/credentials; SQLite is not used as a substitute. |
| Rollback / FK / unique / semantic constraints | BLOCKED | Must execute against isolated staging PostgreSQL. |
| Concurrency / locking A–F | BLOCKED | No staging PostgreSQL and multi-worker environment; no lost-update, optimistic-conflict, deadlock, governance-lock or idempotency result claimed. |
| Backup / restore disaster drill | BLOCKED | No isolated staging database/object-storage target; RTO/RPO cannot be measured honestly. |
| Security staging | NOT VALIDATED | TLS, encryption at rest, rotation, disabled-user/revoked-membership staging checks, network boundary and external penetration testing remain open. |
| Dependency vulnerability scan | NOT VALIDATED | `npm audit` endpoint unavailable on configured mirror; `pip-audit` not installed. |
| Datasource driver matrix | NOT VALIDATED | No real Oracle/MySQL/SQL Server/DB2/GBase server was connected. |
| Performance qualification | NOT VALIDATED | Existing local synthetic baseline is not near-production scale and does not close requested p50/p95/p99 budgets. |
| Real browser UAT | NOT VALIDATED | Existing local browser evidence is not the requested production frontend + staging backend end-to-end path. |

## Driver matrix

Only a real connection may change a row to `PASS`. Current status is `NOT VALIDATED` for every external database driver.

| Priority | Database | Driver / version | Connection | Readonly | Metadata / schema | Safe query | Sync | Validated environment | Known limitations |
|---|---|---|---|---|---|---|---|---|---|
| P0 | PostgreSQL | psycopg 3.x (requirements range) | NOT VALIDATED | NOT VALIDATED | NOT VALIDATED | NOT VALIDATED | NOT VALIDATED | None | Isolated staging server required |
| P1 | SQLite | stdlib sqlite3 | PASS (automated/local) | PASS (automated/local) | PASS (automated/local) | PASS (automated/local) | PASS (automated/local) | CI/local test databases | Not evidence for production PostgreSQL |
| P1 | MySQL/MySQL-compatible | PyMySQL 1.x (requirements range) | NOT VALIDATED | NOT VALIDATED | NOT VALIDATED | NOT VALIDATED | NOT VALIDATED | None | No real server supplied |
| P1 | Oracle | No enabled production driver configured | NOT VALIDATED | NOT VALIDATED | NOT VALIDATED | NOT VALIDATED | NOT VALIDATED | None | Driver/server/version unknown |
| P1 | SQL Server | No enabled production driver configured | NOT VALIDATED | NOT VALIDATED | NOT VALIDATED | NOT VALIDATED | NOT VALIDATED | None | Driver/server/version unknown |
| P1 | DB2 | No enabled production driver configured | NOT VALIDATED | NOT VALIDATED | NOT VALIDATED | NOT VALIDATED | NOT VALIDATED | None | Driver/server/version unknown |
| P2 | GBase | Product/version unknown | NOT VALIDATED | NOT VALIDATED | NOT VALIDATED | NOT VALIDATED | NOT VALIDATED | None | Do not infer compatibility from SQLAlchemy |

## Performance checklist

Status: `NOT VALIDATED`. Required near-realistic data and staging measurements are missing for ordinary API p50/p95/p99, workspace request count/latency, semantic catalog, dashboard aggregation, project-switch cancellation/clearance, and background queue/execution latency. No hidden loading or synthetic cache is used to claim success.

## Browser UAT checklist

Status: `NOT VALIDATED`. Staging still needs the production frontend and real backend path: login → dashboard → project → datasource/connection/schema discovery/metadata sync → catalog → target table/field/scenario → workspace → AI draft/evidence/lineage → human final/review → deliverable → SQL/metadata change → semantic impact/review task → dashboard drill-down. Return links, breadcrumbs, URL restoration, deep links, project switch, restricted/error/conflict/long-text/large-table states must be recorded.

## Go / No-Go

**NO-GO for production.** Clean clone identity is known, but staging PostgreSQL, concurrency/locking, backup/restore, security deployment, driver matrix, performance and real browser UAT are not validated. Qualification stops here; no production release or tag is created.
