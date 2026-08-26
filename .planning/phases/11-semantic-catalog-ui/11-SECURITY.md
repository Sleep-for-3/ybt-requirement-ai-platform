---
phase: 11
slug: semantic-catalog-ui
status: verified
threats_total: 46
threats_closed: 46
threats_open: 0
accepted_risks: 9
asvs_level: 1
block_on: high
created: 2026-08-26
verified: 2026-08-26
---

# Phase 11 — Security

> Phase 11 Semantic Catalog UI threat contract, accepted-risk log, and mitigation verification.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Authenticated user → project-scoped catalog API | Existing authentication, `project.view`, resource permissions, `audit.read`, and project-derived institution scope protect every catalog/detail projection. | Semantic identities, versions, bindings, relations, evidence, lineage, governance, and audit data |
| Catalog API → serialized DTO | Readable and restricted references are separated before serialization; restricted DTOs contain only `entity_type` and `restricted=true`. | Potentially confidential asset identifiers and metadata |
| API response → browser state | Catalog/detail state is keyed by project, canonical query, concept, date, audit mode, region, and attempt before commit/render. | Project-scoped catalog rows and detail regions |
| URL/navigation → application routes | Enums, dates, page state, tabs, `returnTo`, and lineage destinations are canonicalized or exact-allowlisted. | User-controlled navigation and filter input |
| Governed semantic truth → audit/candidate presentation | Confirmed effective versions remain formal truth; rejected/deprecated rows are audit-only and candidates/conflicts never become a silent winner. | Regulatory meaning, lifecycle state, conflict provenance |
| Test harness → local runtime | Browser/server ports are loopback-only and CDP commands, child processes, profiles, and signal cleanup are bounded. | Intercepted local API fixtures and temporary browser profiles |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-11-01 | Elevation of Privilege | project catalog reads | high | mitigate | `semantic_catalog.py` permission gates plus project/institution predicates; adversarial isolation tests | closed |
| T-11-02 | Information Disclosure | restricted binding DTOs | critical | mitigate | Strict discriminated restricted DTO and JSON/DOM absence tests | closed |
| T-11-03 | Tampering | URL filters and `returnTo` | medium | mitigate | Canonical enum/date/query parsing and relative `/semantics` return allowlist | closed |
| T-11-04 | Information Disclosure | stale frontend responses | high | mitigate | Project/query request keys, abort, attempt comparison, and production reducer | closed |
| T-11-05 | Tampering | trusted/audit status partition | high | mitigate | Server lifecycle policy excludes rejected/deprecated rows from trusted projections | closed |
| T-11-06 | Tampering | catalog query state | medium | mitigate | Canonical parsing, explicit search commit, and bounded pagination inputs | closed |
| T-11-07 | Information Disclosure | project-switch response race | high | mitigate | Scope-keyed visible state and adversarial late-success/late-error browser tests | closed |
| T-11-08 | Elevation of Privilege | audit filter UI | high | mitigate | `audit.read` gate and server-confirmed audit-only response partition | closed |
| T-11-09 | Information Disclosure | directory/table render models | high | mitigate | Server-side redaction and type-only restricted client rendering | closed |
| T-11-10 | Elevation of Privilege | detail/lazy-region APIs | high | mitigate | Project and per-resource permission gates with explicit 403/hidden 404 behavior | closed |
| T-11-11 | Information Disclosure | restricted detail chain | critical | mitigate | Strict restricted union plus JSON, DOM, attribute, link, and accessibility-tree absence tests | closed |
| T-11-12 | Tampering | `as_of`/version/tab navigation | medium | mitigate | Canonical URL state and effective-version resolution through `version_service.py` | closed |
| T-11-13 | Information Disclosure | conflict/candidate/audit display | high | mitigate | No conflict winner, formal/candidate separation, and non-current audit presentation | closed |
| T-11-14 | Denial of Service | chain and lazy regions | medium | mitigate | Server caps, bounded client rendering, and independently loaded regions | closed |
| T-11-15 | Elevation of Privilege | optional lazy routes | high | mitigate | Resource-specific permission checks and region-level 403 regression tests | closed |
| T-11-16 | Information Disclosure | restricted reference construction | critical | mitigate | Type-only restricted object constructed before DTO serialization | closed |
| T-11-17 | Tampering | audit-only filters | high | mitigate | `audit.read` authorization and explicit non-trusted audit projections | closed |
| T-11-18 | Tampering | temporal version selection | high | mitigate | Inclusive canonical resolver with explicit project/institution scope and ambiguity rejection | closed |
| T-11-19 | Denial of Service | detail aggregates and chain | medium | mitigate | Set-based aggregates, region/page/chain caps, and query-count regression | closed |
| T-11-05-01 | Information Disclosure | effective version resolver | critical | mitigate | Three-state `UNSCOPED_INSTITUTION` resolver and omitted/integer/null isolation tests | closed |
| T-11-05-02 | Information Disclosure | subordinate semantic partitions | critical | mitigate | Shared institution predicate applied before counts, DTOs, conflicts, audit, and chains | closed |
| T-11-05-03 | Tampering | confirmed relation aggregates | high | mitigate | Confirmed, institution-visible source and target aliases required for trusted relations | closed |
| T-11-05-04 | Denial of Service | added joins | medium | mitigate | Set-based queries and positive 701-concept seven-statement latency gate | closed |
| T-11-06-01 | Information Disclosure | production catalog route state | critical | mitigate | Immutable request key/attempt reducer used by the real `/semantics` route | closed |
| T-11-06-02 | Tampering | audit/status normalization | medium | mitigate | One canonical state machine for parsing, controls, links, and API parameters | closed |
| T-11-06-03 | Denial of Service | pagination controls | low | mitigate | First/previous/next/last targets clamped to server metadata and disabled at boundaries | closed |
| T-11-07-01 | Elevation of Privilege | binding/lineage links | high | mitigate | Exact local destination, selector, provenance, concept, query-count, and fragment allowlist | closed |
| T-11-07-02 | Spoofing | conflict source presentation | medium | mitigate | Stable attributed sources rendered separately from formal truth | closed |
| T-11-07-03 | Information Disclosure | restricted references | high | mitigate | Type-only restricted branch and adversarial absence assertions | closed |
| T-11-08-01 | Spoofing | fixture-only UI evidence | high | mitigate | CDP suite exercises real `/semantics` and `/semantics/42` routes and production DOM/effects | closed |
| T-11-08-02 | Information Disclosure | out-of-order project fetch | critical | mitigate | Held A/B requests resolved adversarially with stale-state absence assertions | closed |
| T-11-08-03 | Information Disclosure | restricted browser output | high | mitigate | Protected markers checked across text, HTML, attributes, links, and accessibility output | closed |
| T-11-08-04 | Denial of Service | browser/server lifecycle | medium | mitigate | Loopback-only runtime, hard timeouts, bounded CDP/process teardown, and profile cleanup | closed |
| T-11-09-01 | Repudiation | qualification ledger | high | mitigate | Exact commands, exit checks, counts, corrections, IDs, and evidence anchors recorded | closed |
| T-11-09-02 | Information Disclosure | isolation/browser qualification | critical | mitigate | Adversarial institution/project, restricted-output, and stale-response gates rerun | closed |
| T-11-09-03 | Denial of Service | query/build regressions | medium | mitigate | Focused/full tests, build, lint, high-risk backend run, and positive query measurement | closed |
| T-11-09-04 | Spoofing | security/UI verdict ownership | high | mitigate | Qualification ledger delegates canonical security and UI verdicts to their dedicated workflows | closed |
| T-11-SC@11-01 | Tampering | dependency supply chain | low | accept | No Phase 11 package/lockfile change; documented as accepted process risk | closed |
| T-11-SC@11-02 | Tampering | dependency supply chain | low | accept | No package installation or registry use; documented as accepted process risk | closed |
| T-11-SC@11-03 | Tampering | dependency supply chain | low | accept | No package installation or external registry dependency; documented as accepted process risk | closed |
| T-11-SC@11-04 | Tampering | dependency supply chain | low | accept | No package installation; documented as accepted process risk | closed |
| T-11-05-SC | Tampering | dependency supply chain | low | accept | Gap repair introduced no package installation; documented as accepted process risk | closed |
| T-11-06-SC | Tampering | dependency supply chain | low | accept | Catalog repair introduced no package installation; documented as accepted process risk | closed |
| T-11-07-SC | Tampering | dependency supply chain | low | accept | Detail repair introduced no package installation; documented as accepted process risk | closed |
| T-11-08-SC | Tampering | browser test dependencies | low | accept | Harness uses installed Next, Edge/Chrome, and Node built-ins without lockfile changes | closed |
| T-11-09-SC | Tampering | qualification dependency integrity | low | accept | Scoped package/lockfile worktree and commit-range diffs are empty | closed |

All plan-time threats are closed. The nine accepted low-severity supply-chain entries were already assigned disposition `accept` in their respective plans; this artifact records those existing decisions and their clean dependency-history evidence.

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-11-01 | T-11-SC@11-01 | Existing dependencies are reused; package and lockfile history is unchanged. | Phase 11 plan decision | 2026-08-26 |
| AR-11-02 | T-11-SC@11-02 | No package installation or registry access was introduced. | Phase 11 plan decision | 2026-08-26 |
| AR-11-03 | T-11-SC@11-03 | Detail UI reuses existing dependencies without external registry additions. | Phase 11 plan decision | 2026-08-26 |
| AR-11-04 | T-11-SC@11-04 | Backend detail projections add no package dependency. | Phase 11 plan decision | 2026-08-26 |
| AR-11-05 | T-11-05-SC | Isolation and relation repairs require no new package. | Phase 11 gap-plan decision | 2026-08-26 |
| AR-11-06 | T-11-06-SC | Catalog controller repairs require no new package. | Phase 11 gap-plan decision | 2026-08-26 |
| AR-11-07 | T-11-07-SC | Link, conflict, and disclosure repairs require no new package. | Phase 11 gap-plan decision | 2026-08-26 |
| AR-11-08 | T-11-08-SC | The test harness intentionally relies on installed runtimes and Node built-ins. | Phase 11 gap-plan decision | 2026-08-26 |
| AR-11-09 | T-11-09-SC | Qualification confirms empty package and lockfile diffs. | Phase 11 gap-plan decision | 2026-08-26 |

---

## Environment Qualifications

- PostgreSQL was unavailable; the recorded seven-statement query plan and latency are SQLite regression evidence, not a production benchmark.
- The corrected repository-root `PYTHONPATH` high-risk invocation passed 424 tests with exactly the two named Windows-only deselections.
- The security auditor used the committed 68-test backend, 83-test frontend, build/lint, and 12/12 production-browser evidence without redundantly rerunning the suites.
- Four-viewport visual geometry and visible-focus approval remain owned by `$gsd-ui-review 11`; this does not leave a threat mitigation open.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-08-26 | 46 | 46 | 0 | `gsd-security-auditor` + primary orchestrator |
| 2026-08-26 | 46 | 46 | 0 | Primary orchestrator — ASVS L1 short-circuit re-verification |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-08-26
