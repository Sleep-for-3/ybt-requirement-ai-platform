# Phase 10: Generator Refactor - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-23
**Phase:** 10-Generator Refactor
**Areas discussed:** Context cutover and fallback, effective generation date, task-specific prompt projection, generation readiness and blocking

---

## Context Cutover and Fallback

| Option | Description | Selected |
|--------|-------------|----------|
| Strict Context-only cutover | ContextBuilder is the sole shared-fact source; build failures fail generation. | ✓ |
| Controlled production fallback | Use old ORM/RAG context if Context is unavailable. | |
| Hybrid per-fact lookup | Fill individual Context gaps using legacy queries. | |

**User's choice:** Strict Context-only production cutover.

**Notes:** Context construction failure and a successfully built but incomplete Context are different states. Mapping-row reads, task-specific writes, status checks, and audit remain generator responsibilities. Legacy comparison is allowed only in tests or shadow diagnostics and cannot affect production facts.

---

## Effective Generation Date

| Option | Description | Selected |
|--------|-------------|----------|
| Optional additive `as_of` | Preserve old calls and resolve a deterministic fallback chain. | ✓ |
| Required `as_of` | Break old callers unless they provide a date. | |
| Always current date | Ignore task/project reporting dates. | |

**User's choice:** Optional additive `as_of` with explicit fallback priority.

**Notes:** Priority is explicit date, existing task/project reporting/effective date, existing project default reporting date, then current business date. The resolved date must be traceable in Context and generation audit metadata. No new ReportingPeriod system is introduced.

---

## Task-Specific Prompt Projection

| Option | Description | Selected |
|--------|-------------|----------|
| Three task-specific adapter families | Preserve Source-to-Mart, Mart-to-YBT, and Scenario differences. | ✓ |
| Whole Context serialization | Put the complete Context into every prompt. | |
| Universal prompt adapter | Normalize all generators behind one generic adapter. | |

**User's choice:** Separate task-specific adapters with typed, deterministic, bounded projections.

**Notes:** Adapters select relevant facts, sort by authority, retain provenance, compress long text, include conflicts/questions, and control prompt size. The complete Context remains available for audit/debug. Task-specific instructions and structured output schemas stay separate.

---

## Generation Readiness and Blocking

| Option | Description | Selected |
|--------|-------------|----------|
| Task-aware deterministic readiness | Classify warnings and blockers relative to the generator's purpose. | ✓ |
| Block on every gap | Stop whenever any missing fact appears. | |
| Always generate | Call the model even when core authoritative facts conflict. | |

**User's choice:** Deterministic task-aware readiness.

**Notes:** Missing evidence/knowledge/lineage, non-core unknowns, and the mapping gap being filled are normally non-blocking but lower confidence and produce questions. Core high-authority contradictions, invalid/cross-project identity, Context failure, and governance prohibition block generation. The LLM must never guess between competing confirmed facts.

---

## the agent's Discretion

- Exact module/class names, prompt limits, additive optional-date API shape, diagnostic HTTP details, audit payload field names, migration wave order, and test-only shadow harness shape.
- Discretion is constrained by backward compatibility, no production fallback, deterministic output, and no Phase 9 contract redesign.

## Deferred Ideas

- Frontend work remains Phase 11+.
- SQL Generator remains outside Phase 10.
- Semantic Impact remains Phase 15.
- A new ReportingPeriod persistence model requires separate future scope if existing date sources are insufficient.
