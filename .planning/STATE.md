---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Regulatory Data Intelligence V2
current_phase: 09
current_phase_name: Regulatory Context
status: executing
stopped_at: Completed 09-03-PLAN.md
last_updated: "2026-08-22T16:55:36.725Z"
last_activity: 2026-08-23
last_activity_desc: 09-03 RegulatoryContextBuilder completed; 09-04 next
progress:
  total_phases: 8
  completed_phases: 1
  total_plans: 7
  completed_plans: 6
---

# Project State

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-08-20)

**Core value:** 监管语义、口径、证据、血缘和治理关系是核心资产，AI 不能越过人工确认。
**Current focus:** Phase 09 — Regulatory Context

## Current Position

Phase: 09 (Regulatory Context) — EXECUTING
Plan: 4 of 4
Status: Ready for 09-04
Last activity: 2026-08-23 — 09-03 RegulatoryContextBuilder completed; 09-04 next

Progress: [████████░░] 75% of Phase 9 plans

## Performance Metrics

**Velocity:**

- Total plans completed: 6
- Average duration: 34m
- Total execution time: 1h 42m

**Per-Plan Metrics:**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 09 P01 | 40m | 3 tasks | 15 files |
| Phase 09 P02 | 23m | 2 tasks | 4 files |
| Phase 09 P03 | 39m | 3 tasks | 6 files |

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

### Pending Todos

None.

### Blockers/Concerns

- v1.0 frontend changes are still uncommitted and must be preserved during backend work.
- No PostgreSQL service is guaranteed locally; dialect correctness must be covered by migration construction and SQLite execution, with PostgreSQL runtime verification documented if unavailable.
- Baseline backend suite has two pre-existing Windows-only failures: ACL inspection and interactive lifecycle-script timeout; 269 other tests pass after 09-01.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| SQL | Full SQL Generator | future | v2.0 start |
| Scope | Institution/global shared concept publication | future | v2.0 start |

## Session Continuity

Last session: 2026-08-22T16:55:36.687Z
Stopped at: Completed 09-03-PLAN.md
Resume file: None
