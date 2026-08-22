---
phase: 09-regulatory-context
plan: 04
revision: "202608200016"
qualified_at: 2026-08-23
sqlite: passed
postgresql_offline: passed
postgresql_live: unavailable
---

# Phase 09 Plan 04 PostgreSQL Qualification

## Qualification Verdict

Revision `202608200016` is qualified on the local SQLite lifecycle and by direct PostgreSQL-dialect compilation of its explicit upgrade and downgrade operations. A live PostgreSQL runtime was **not available** on this machine, so PostgreSQL migration execution, row locking, and concurrent overlap rejection remain a mandatory staging gate.

The historical full-chain `alembic --sql` limitation at revision `202607070002` remains visible and was not bypassed or rewritten. It is separate from the passing direct compilation of revision `202608200016`.

## Executed Evidence

| Gate | Exact command/check | Result |
| --- | --- | --- |
| Alembic head | `cd backend; python -m alembic heads` | PASS — `202608200016 (head)` |
| SQLite empty/head and downgrade/up lifecycle | `cd backend; python -m pytest -q tests/test_semantic_migration.py -k "postgres or migration or 016" -x` | PASS — 4 passed, 4 warnings in 26.79s |
| SQLite legacy 015 bootstrap | Same migration command | PASS — one version 1 row per legacy concept, original effective dates retained, safe downgrade to 015 |
| Formal index preservation | Same migration command | PASS — `embedding_index_versions` and all formal semantic version indexes remain present after round trips |
| PostgreSQL direct/offline revision compilation | `test_revision_016_compiles_portable_postgresql_upgrade_and_downgrade_sql` in the same command | PASS — PostgreSQL DDL contains all three foreign keys, the effective-date CHECK, formal indexes, and downgrade; no `PRAGMA`, `AUTOINCREMENT`, or `sqlite` token |
| SQLite serialized confirmed interval | `cd backend; python -m pytest -q tests/test_semantic_layer.py::test_sqlite_confirmed_interval_is_serialized_across_sessions` | PASS — 1 passed in 19.36s |
| Context/API/semantic/migration core | `cd backend; python -m pytest -q tests/test_regulatory_context_api.py tests/test_regulatory_context_contract.py tests/test_regulatory_context_builder.py tests/test_semantic_layer.py tests/test_semantic_migration.py` | PASS — 79 passed, 4 warnings in 64.65s |
| Knowledge/governance/lineage adjacency | `cd backend; python -m pytest -q tests/test_hybrid_retriever.py tests/test_knowledge_rag.py tests/test_knowledge_reindex.py tests/test_semantic_retrieval_security.py tests/test_rag_evaluation_semantic.py tests/test_governance.py tests/test_sql_lineage.py` | PASS — 86 passed in 26.54s |
| Python compilation | `cd backend; python -m compileall -q app` | PASS — exit 0, no output |
| Full backend regression | `cd backend; python -m pytest -q` | QUALIFIED — 327 passed, 2 pre-existing failures, 5 warnings in 216.28s |

The migration warnings are Python 3.12's deprecated default SQLite datetime adapter. The full-suite warning set also includes the existing development-only temporary `APP_SECRET_KEY` warning. Neither warning changes the migration or API verdict.

## PostgreSQL Availability Evidence

The following read-only probes were executed without printing credentials:

- `pg_isready` and `psql` executables are installed.
- `pg_isready -h 127.0.0.1 -p 5432 -t 2` returned `127.0.0.1:5432 - no response`.
- No Windows PostgreSQL service and no local TCP listener on port 5432 were found.
- `DATABASE_URL`, `PGHOST`, and `PGPORT` were not set in the process environment.
- Application settings resolved to the `sqlite` backend.

Therefore no PostgreSQL connection, live upgrade/downgrade, constraint execution, or concurrent transaction test was run. The `postgresql_live` status is `unavailable`, not passed.

## Direct Revision 016 PostgreSQL Dialect Evidence

The migration test loads only `202608200016_semantic_concept_versions.py`, binds Alembic `Operations` to an offline `MigrationContext` with `dialect_name="postgresql"`, and executes both `upgrade()` and `downgrade()`.

The compiled PostgreSQL SQL proves:

- `semantic_concept_versions` is created and dropped without runtime ORM metadata.
- Foreign keys target `semantic_concepts.id`, `institutions.id`, and `projects.id`.
- `ck_semantic_concept_version_dates` enforces `effective_to IS NULL OR effective_to >= effective_from`.
- Unique, status, concept, project/effective, and single-column indexes compile.
- The downgrade emits explicit single-column index drops and table removal.
- No SQLite-only SQL expression leaks into either direction.

## Known Historical Full-Chain Limitation

Executed command:

```text
cd backend
$env:DATABASE_URL = 'postgresql+psycopg://qualification:qualification@127.0.0.1:5432/qualification'
python -m alembic upgrade 202608200016 --sql
```

Result: expected baseline failure, exit code 1, while applying `202607070002_template_datasource_nl_task.py`. That older migration calls `inspect(bind)` against Alembic's offline `MockConnection`, producing:

```text
sqlalchemy.exc.NoInspectionAvailable: No inspection system is available for object of type <class 'sqlalchemy.engine.mock.MockConnection'>
```

This failure occurs before revisions 015 and 016. It does not contradict the direct PostgreSQL compilation result for 016, and it must not be hidden by changing the target revision or claiming full-chain offline success.

## Regression Classification

Phase 8's delivered baseline was 255 passed and the same two Windows failures. The current suite is 327 passed and those same two failures; Phase 9 added 72 passing tests without adding a failure.

| Failure identity | Current signature | Classification |
| --- | --- | --- |
| `tests/test_productization.py::test_windows_secret_acl_commands_remove_explicit_extra_access_and_are_idempotent` | `acl["Protected"]` is `None`, expected `True` | Pre-existing Windows environment baseline |
| `tests/test_productization.py::test_windows_lifecycle_script_without_action_keeps_control_console_open` | `subprocess.TimeoutExpired` after 10 seconds waiting for `项目启停.ps1` | Pre-existing Windows environment baseline |

No new Phase 9 regression was observed. The baseline failures were not skipped, renamed, or rewritten.

## Performance and N+1 Evidence

`test_candidate_limit_and_http_query_budget_do_not_grow_with_rows` instruments SQLAlchemy at the HTTP boundary. A candidate request with 5 source candidates and 2 knowledge units used 22 statements. After growth to 65 source candidates and 42 knowledge units, the same request still used 22 statements, while `candidate_limit=3` returned exactly 3 candidates. This confirms the builder's 21-statement service budget plus one project authorization lookup, with no row-count-driven N+1 growth.

## Mandatory Live PostgreSQL Staging Checklist

Run every item against an isolated PostgreSQL staging database before release:

- [ ] Record PostgreSQL server version, Alembic current revision, and a backup/restore point.
- [ ] Upgrade an empty database to `202608200016`; verify all semantic tables, foreign keys, the effective-date CHECK, unique constraints, and named indexes.
- [ ] Upgrade a populated database from `202608200015`; verify exactly one bootstrap version 1 per legacy concept, source provenance, dates, aliases, status, and confirmed metadata.
- [ ] Downgrade head to `202608200015`, confirm only the version table is removed, then upgrade back to head and verify the formal embedding index is unchanged.
- [ ] Attempt invalid foreign keys and `effective_to < effective_from`; confirm PostgreSQL rejects each write.
- [ ] In two concurrent PostgreSQL transactions, confirm overlapping confirmed intervals for the same concept; verify `SELECT ... FOR UPDATE` serialization permits at most one commit and returns the stable 409 conflict for the loser.
- [ ] Exercise inclusive boundary dates (`effective_from` and `effective_to`) and the ambiguous-overlap 409 through the HTTP API.
- [ ] Use two institutions/projects with identical codes and real principals; verify `project.view`, 403/404 visibility, target/source isolation, and derived institution provenance.
- [ ] Seed confidential/restricted knowledge in both projects; verify RetrievalLog traceability and that foreign content never crosses the response boundary.
- [ ] Re-run the 22-statement baseline/growth measurement using the PostgreSQL driver and investigate any row-count-dependent increase.
- [ ] Re-run the complete Phase 8 semantic route suite and compare response fields for Concept, Binding, Relation, graph, path, resolver, status, and version endpoints.
- [ ] Run `python -m pytest -q` against the staging configuration and classify every failure by test identity and signature.

Live PostgreSQL qualification remains **required** until this checklist is completed and attached to the release evidence.
