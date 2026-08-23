---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Regulatory Data Intelligence V2
current_phase: 10
current_phase_name: Generator Refactor
status: planning
stopped_at: Phase 10 context gathered
last_updated: "2026-08-23T04:13:22.875Z"
last_activity: 2026-08-23
last_activity_desc: Phase 09 verified complete; Phase 10 planning not started
progress:
  total_phases: 3
  completed_phases: 2
  total_plans: 7
  completed_plans: 7
---

# Project State

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-08-20)

**Core value:** 监管语义、口径、证据、血缘和治理关系是核心资产，AI 不能越过人工确认。
**Current focus:** Phase 10 — Generator Refactor planning boundary

## Current Position

Phase: 10 — Generator Refactor
Plan: Not started
Status: Ready to plan
Last activity: 2026-08-23 — Phase 09 complete, transitioned to Phase 10

Progress: [███░░░░░░░] 2/8 milestone phases complete

## Performance Metrics

**Velocity:**

- Total plans completed: 7
- Average duration: 42m
- Total execution time: 2h 5m

**Per-Plan Metrics:**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 09 P01 | 40m | 3 tasks | 15 files |
| Phase 09 P02 | 23m | 2 tasks | 4 files |
| Phase 09 P03 | 1h 2m | 3 tasks | 9 files |
| Phase 09 P04 | 35min | 3 tasks | 5 files |

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

### Pending Todos

None.

### Blockers/Concerns

- v1.0 frontend changes are still uncommitted and must be preserved during backend work.
- No PostgreSQL service is guaranteed locally; dialect correctness must be covered by migration construction and SQLite execution, with PostgreSQL runtime verification documented if unavailable.
- Baseline backend suite still has the same two pre-existing Windows-only failures: ACL inspection and interactive lifecycle-script timeout; final Phase 9 HEAD has 337 passing tests and no new failure.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| SQL | Full SQL Generator | future | v2.0 start |
| Scope | Institution/global shared concept publication | future | v2.0 start |

## Session Continuity

Last session: 2026-08-23T04:13:22.848Z
Stopped at: Phase 10 context gathered
Resume file: .planning/phases/10-generator-refactor/10-CONTEXT.md
