---
phase: 09-regulatory-context
fixed_at: 2026-08-23T03:22:23+08:00
review_path: .planning/phases/09-regulatory-context/09-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 09: Code Review Fix Report

**Fixed at:** 2026-08-23T03:22:23+08:00
**Source review:** `.planning/phases/09-regulatory-context/09-REVIEW.md`
**Iteration:** 1

**Summary:**

- Findings in scope: 4
- Fixed: 4
- Skipped: 0

## Fixed Issues

### WR-01: Candidate bindings contaminate confirmed semantic provenance and suppress the confirmed-binding gap

**Files modified:** `backend/app/services/semantic/context_collectors.py`, `backend/tests/test_regulatory_context_builder.py`
**Commit:** 56dea4d
**Status:** fixed: requires human verification
**Applied fix:** Partitioned confirmed and draft/AI bindings before projection. Confirmed facts and trusted gap signals now use confirmed bindings only; draft/AI bindings remain candidate facts. Confirmed binding selection prefers the explicitly requested target identity and then stable binding id.

### WR-02: Candidate-only mapping evidence suppresses a trusted evidence gap

**Files modified:** `backend/app/services/semantic/context_collectors.py`, `backend/tests/test_regulatory_context_builder.py`
**Commit:** ba4a8f8
**Status:** fixed: requires human verification
**Applied fix:** Derived trusted evidence rows from trusted mapping keys once and reused that collection for trusted evidence facts and completeness counts. Candidate-only evidence no longer suppresses `MISSING_EVIDENCE`.

### WR-03: Unbounded collectors can violate the public contract and convert valid GETs into HTTP 400

**Files modified:** `backend/app/services/semantic/context_builder.py`, `backend/app/services/semantic/context_collectors.py`, `backend/tests/test_regulatory_context_builder.py`, `backend/tests/test_regulatory_context_api.py`
**Commit:** 548b750
**Applied fix:** Capped each evidence list at 50, each fact section at 500, and all fact sections at 1,000 in stable Contract order. Emitted metadata counts now describe the retained facts, and truncation produces `truncated: true` with one bounded warning. Added 50/51 evidence, 500/501 section, 1,000/1,001 global, and HTTP 200 regression coverage.

### WR-04: `not_linked` mappings are counted as persisted lineage and hide the missing-lineage question

**Files modified:** `backend/app/services/semantic/context_collectors.py`, `backend/tests/test_regulatory_context_builder.py`
**Commit:** cddecd6
**Status:** fixed: requires human verification
**Applied fix:** Preserved `not_linked` mapping-lineage facts for audit visibility while counting only raw edges and mapping statuses `linked`, `verified`, or `stale` as actual persisted lineage.

## Verification

Verification ran in the isolated review-fix worktree.

- Focused RED/GREEN tests were run for each finding; every regression failed before its source fix and passed afterward.
- Phase 9 core suite: `python -m pytest -q tests/test_regulatory_context_contract.py tests/test_regulatory_context_builder.py tests/test_regulatory_context_api.py tests/test_semantic_layer.py tests/test_semantic_migration.py` — 87 passed, 4 pre-existing SQLite datetime-adapter warnings.
- Syntax/bytecode: `python -m compileall -q app` — passed.
- Query budgets remained unchanged and passed: builder acceptance 21, effective-version batch 14, HTTP 22.

---

_Fixed: 2026-08-23T03:22:23+08:00_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: 1_
