---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Regulatory Data Intelligence V2
current_phase: 10
current_phase_name: generator-refactor
status: executing
stopped_at: Completed 10-07-PLAN.md
last_updated: "2026-08-24T13:15:49.104Z"
last_activity: 2026-08-24
last_activity_desc: Phase 10 execution started
progress:
  total_phases: 3
  completed_phases: 2
  total_plans: 15
  completed_plans: 13
---

# Project State

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-08-20)

**Core value:** 监管语义、口径、证据、血缘和治理关系是核心资产，AI 不能越过人工确认。
**Current focus:** Phase 10 — generator-refactor

## Current Position

Phase: 10 (generator-refactor) — EXECUTING
Plan: 3 of 8
Status: Ready to execute
Last activity: 2026-08-24 — Phase 10 execution started

Progress: [█████████░] 87%

## Performance Metrics

**Velocity:**

- Total plans completed: 8
- Average duration: 54m
- Total execution time: 7h 14m

**Per-Plan Metrics:**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 09 P01 | 40m | 3 tasks | 15 files |
| Phase 09 P02 | 23m | 2 tasks | 4 files |
| Phase 09 P03 | 1h 2m | 3 tasks | 9 files |
| Phase 09 P04 | 35min | 3 tasks | 5 files |
| Phase 10 P01 | 45min | 3 tasks | 6 files |
| Phase 10 P02 | 57min | 3 tasks | 4 files |
| Phase 10 P03 | 1h 22m | 3 tasks | 7 files |
| Phase 10 P04 | 1h 30m | 3 tasks | 10 files |
| Phase 10 P05 | 38 min | 2 tasks | 7 files |
| Phase 10 P07 | 9 min | 2 tasks | 5 files |

## Accumulated Context

### Decisions

- [Phase 8]: Semantic scope is project-first and institution-aware; global sharing is deferred.
- [Phase 8]: formal semantic index remains untouched and separate.
- [Phase 8]: PostgreSQL/SQLite adjacency tables and bounded traversal; no graph database.
- [Phase 8]: Existing entities become binding targets; no duplicate Metadata/Lineage/Knowledge models.
- [Phase 9]: Rejected/deprecated semantic rows are audit-only and never trusted or candidate business facts.
- [Phase 9]: SemanticConcept is stable identity; SemanticConceptVersion is canonical governed temporal meaning, with legacy Concept fields as a same-transaction compatibility projection.
- [Phase 9]: RegulatoryContext is a projection-only contract with separate authority/state/provenance and deterministic conflicts/open questions.
- [Phase 9]: Trusted semantic reads remain confirmed-only; candidate mode explicitly adds draft and ai_suggested while rejected/deprecated remain audit-only.
- [Phase 9]: SemanticConceptVersion is canonical temporal meaning and legacy Concept fields are a same-transaction compatibility projection.
- [Phase 9]: The additive effective version route is declared before the dynamic version-id route and uses inclusive date intervals.
- [Phase 9]: Migration 202608200016 bootstraps one version_no=1 per legacy Concept using created_at or fixed 2026-08-20 fallback without fabricated history.
- [Phase 9]: RegulatoryContext requests exclude institution_id; output facts must match the derived project and institution scope.
- [Phase 9]: Formal and human-confirmed sources share the highest authority tier; authority and FactState remain independent.
- [Phase 9]: Retrieved facts require RetrievalLog provenance and matching knowledge confidentiality.
- [Phase 9]: CTX spec-less records remain test-only planning metadata and never enter runtime context output.
- [Phase 9]: RegulatoryContextBuilder accepts only a PermissionService-authorized Project and derives institution scope only from it.
- [Phase 9]: Raw lineage and persisted mapping/scenario lineage use distinct verification predicates based only on real model fields.
- [Phase 9]: Context candidates use seven explicit ranking tiers with caps after stable full sorting; the acceptance collector budget is 21 SQL statements.
- [Phase 9]: Institution-scoped and restricted knowledge fail closed to their owner project; bank_name is never an authorization identity.
- [Phase 9]: Mapping audit rows stay absent, while draft and ai_suggested rows remain explicit state-preserving candidates only.
- [Phase 9]: Effective semantic versions resolve in one batched query using the same inclusive trusted policy as the single resolver.
- [Phase 09]: RegulatoryContext API uses explicit project.view authorization and the canonical authorized-Project builder handoff.
- [Phase 09]: Existing semantic.py mode propagation remains unchanged; regression coverage proves Phase 8 route compatibility.
- [Phase 09]: PostgreSQL 016 offline compilation passes, but live PostgreSQL remains a mandatory staging gate because localhost was unavailable.
- [Phase 10]: Shared RegulatoryContext is the sole generator shared-fact seam; each task builds it exactly once in candidate mode with no legacy fallback.
- [Phase 10]: CatalogColumn projection is limited to enabled same-project evidence or verified-lineage links with one fixed query.
- [Phase 10]: Physical output accepts only exact Context-whitelisted tuples or the unchanged canonical task tuple.
- [Phase 10]: Question merge preserves the human prefix byte-for-byte and appends stable CTX and AI provenance markers.
- [Phase 10]: Both double-layer generators use one immutable RegulatoryContext projection and no legacy shared-fact fallback.
- [Phase 10]: Model attempts commit before a fresh short actor-PermissionService-Project-task snapshot transaction applies any draft.
- [Phase 10]: Mart-to-YBT approved upstream rules are point-in-time Context facts and are not part of the local stale snapshot.
- [Phase 10]: Generation never mutates final_content or formal review state; explicit adoption and review remain human governance boundaries.
- [Phase 10]: Scenario business and technical generation share only the authorized RegulatoryContext seam while retaining distinct snapshots, prompts, outputs, renderers, and apply policies.
- [Phase 10]: Queued authority is reconstructed only from an active persisted User as an explicitly non-legacy frozen Principal; missing, zero, disabled, and revoked identities fail closed.
- [Phase 10]: Scenario generation performs Context and model work without row locks, then revalidates actor and permission before fixed Project-to-task locks and complete snapshot comparison.
- [Phase 10]: Technical physical identifiers require an exact current or same-Context tuple; refused tuples preserve current physical fields and add a stable governed question.
- [Phase 10]: Queued security, readiness, governance, and stale outcomes use bounded blocked codes and per-item commits rather than content-bearing failures or legacy retry paths.
- [Phase 10]: Query regression uses a positive post-warm-up measured baseline, exact +1 Catalog enrichment delta, and invariant growth; historical 21/22 counts are comparison data, not ceilings.
- [Phase 10]: Scenario technical profile evidence remains bounded resolver-candidate provenance frozen into the current-lineage typed projection; it never becomes trusted evidence or a shared-fact fallback.
- [Phase 10]: Only the two exact documented Windows node IDs with matching signatures qualify as pre-existing; the maximum backend suite may deselect those nodes and nothing broader.
- [Phase 10]: SQLite qualification does not imply PostgreSQL parity; live production-driver row-lock and concurrent-commit behavior remains an explicit staging gate while PostgreSQL is unavailable.

### Pending Todos

None.

### Blockers/Concerns

- v1.0 frontend changes are still uncommitted and must be preserved during backend work.
- No PostgreSQL service is guaranteed locally; dialect correctness must be covered by migration construction and SQLite execution, with PostgreSQL runtime verification documented if unavailable.
- The final unfiltered backend suite has 386 passing tests and only the same two pre-existing Windows-only failures (ACL inspection and interactive lifecycle-script timeout); the maximum suite passes 386 tests when exactly those two nodes are deselected.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| SQL | Full SQL Generator | future | v2.0 start |
| Scope | Institution/global shared concept publication | future | v2.0 start |

## Session Continuity

Last session: 2026-08-24T13:15:49.057Z
Stopped at: Completed 10-07-PLAN.md
Resume file: None
