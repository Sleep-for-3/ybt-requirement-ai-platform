---
phase: 09
slug: regulatory-context
status: verified
threats_open: 0
asvs_level: 1
block_on: high
created: 2026-08-23
---

# Phase 09 — Security

> Verification of the threat models authored in plans 09-01 through 09-04. This audit verifies the registered mitigations only; it does not expand Phase 9 scope.

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| HTTP caller to authenticated API | Caller-controlled project, scope, mode, date, and limit parameters enter the service. | Identifiers, dates, authorization context |
| API/service to ORM | Permission-qualified project and institution scope constrain semantic, mapping, knowledge, historical, and lineage queries. | Governed business facts and metadata |
| ORM/retrieval to context contract | Existing rows and retrieval results are projected into bounded facts with authority, state, and provenance. | Definitions, evidence, confidentiality metadata |
| Migration to stored database | Legacy semantic concepts are bootstrapped into temporal version rows. | Existing semantic data and lifecycle state |
| Context response to downstream consumer | A read-only, bounded `RegulatoryContext` crosses the wire. | Facts, candidates, conflicts, open questions |

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation and evidence | Status |
|-----------|----------|-----------|----------|-------------|-------------------------|--------|
| T-09-01-01 | Information disclosure | semantic API / binding / graph | high | mitigate | `PermissionService`, project predicates, institution derived from project; two-project isolation tests in `test_semantic_layer.py`. | closed |
| T-09-01-02 | Tampering / repudiation | lifecycle policy / resolver / governance | high | mitigate | Central `status_policy.py`; rejected/deprecated excluded from trusted paths; audited confirmation transitions. | closed |
| T-09-01-03 | Tampering | temporal semantic versions | high | mitigate | Inclusive interval validation, transactional overlap rejection, confirmed-row immutability, deterministic 409 responses. | closed |
| T-09-01-04 | Information disclosure | semantic entity adapter | medium | mitigate | Explicit frozen bounded descriptors and provenance; tests reject ORM/reflection dumps. | closed |
| T-09-01-05 | Denial of service | graph / resolver | medium | mitigate | Traversal and result caps, stable rank-before-cap ordering, deterministic bounded-query tests. | closed |
| T-09-02-01 | Information disclosure | context scope / provenance | high | mitigate | No client institution override; project-scoped identifiers and provenance validation. | closed |
| T-09-02-02 | Tampering / repudiation | authority / fact state | high | mitigate | Machine-defined authority registry, separate lifecycle state, validation prevents retrieved or inferred fact promotion. | closed |
| T-09-02-03 | Tampering | effective periods | medium | mitigate | Normalized inclusive date ordering and invalid-period contract tests. | closed |
| T-09-02-04 | Information disclosure | context serialization | high | mitigate | `extra="forbid"`, typed bounded values, explicit provenance, ORM/arbitrary-dump rejection tests. | closed |
| T-09-02-05 | Denial of service | nested contract collections | medium | mitigate | Text, nested-list, fact, question, and candidate limits enforced at the schema boundary. | closed |
| T-09-03-01 | Information disclosure | builder / collectors | high | mitigate | Builder requires an authorized project, rejects project mismatch, derives institution internally, and project-qualifies collectors. | closed |
| T-09-03-02 | Tampering / repudiation | authority normalization | high | mitigate | Every fact uses the shared authority policy; state is preserved independently; contradictions become explicit conflicts. | closed |
| T-09-03-03 | Tampering | effective version resolution | high | mitigate | Batched inclusive `as_of` resolution; ambiguous periods surface as conflicts instead of silent winners. | closed |
| T-09-03-04 | Information disclosure | knowledge collectors | high | mitigate | Regulatory knowledge is project-only; retrieved evidence retains visibility, confidentiality, source, and retrieval-log provenance. | closed |
| T-09-03-05 | Denial of service | candidate/query fan-out | high | mitigate | Batched queries, explicit candidate tiers, rank-before-cap, and fixed-growth query-budget regression tests. | closed |
| T-09-04-01 | Information disclosure | context API | high | mitigate | `project.view` is checked before builder construction; all scope identifiers are project-qualified; API isolation tests pass. | closed |
| T-09-04-02 | Tampering / repudiation | context response / candidate mode | high | mitigate | Trusted and candidate states remain separate; rejected/deprecated cannot become confirmed; no-authoritative-mutation HTTP test passes. | closed |
| T-09-04-03 | Tampering | version API / migration | high | mitigate | Machine-readable 409 conflicts, inclusive constraints, reversible SQLite migration, and offline PostgreSQL dialect qualification. | closed |
| T-09-04-04 | Information disclosure | context facts / knowledge response | high | mitigate | Typed bounded response carries confidentiality/provenance and omits foreign-project content. | closed |
| T-09-04-05 | Denial of service | context GET / builder | high | mitigate | Bounded HTTP parameters, section/global fact budgets, deterministic truncation, rank-before-cap, and constant-growth query tests. | closed |

All 20 registered threats are closed. There are no below-threshold open threats.

## Accepted Risks Log

No accepted risks.

## Qualification

- The Phase 9 core suite passed with 89 tests; four SQLite datetime-adapter warnings are pre-existing compatibility warnings.
- Revision 016 upgrade/downgrade paths compile against the PostgreSQL dialect and pass the SQLite migration lifecycle.
- A live PostgreSQL server was unavailable locally. Live migration execution, database-enforced constraints, and concurrent `SELECT FOR UPDATE` behavior remain an explicit staging release gate and are not represented as verified here.

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-08-23 | 20 | 20 | 0 | `gsd-security-auditor` |

## Sign-Off

- [x] All threats have a disposition.
- [x] Accepted-risks status documented.
- [x] `threats_open: 0` confirmed.
- [x] `status: verified` set in frontmatter.

**Approval:** verified 2026-08-23
