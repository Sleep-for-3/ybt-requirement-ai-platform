---
phase: 09-regulatory-context
fixed_at: 2026-08-23T03:39:43+08:00
review_path: .planning/phases/09-regulatory-context/09-REVIEW.md
iteration: 2
findings_in_scope: 2
fixed: 2
skipped: 0
status: all_fixed
---

# Phase 09: Code Review Fix Report

**Fixed at:** 2026-08-23T03:39:43+08:00
**Source review:** `.planning/phases/09-regulatory-context/09-REVIEW.md`
**Iteration:** 2

**Summary:**

- Findings in scope: 2
- Fixed: 2
- Skipped: 0

## Fixed Issues

### WR-01: Explicit semantic concept can still borrow a confirmed binding from an unrelated target

**Files modified:** `backend/app/services/semantic/context_collectors.py`, `backend/tests/test_regulatory_context_builder.py`
**Commit:** 8382f71
**Status:** fixed: requires human verification
**Applied fix:** Explicit-concept requests now filter both confirmed and draft/AI bindings to the resolved request target identities whenever any target identity is present. Unrelated bindings cannot be cited or suppress `MISSING_CONFIRMED_SEMANTIC_BINDING`; concept-only requests retain concept-wide binding behavior.

### WR-05: Draft binding candidates are emitted with AI-suggested concept lifecycle and provenance

**Files modified:** `backend/app/services/semantic/context_collectors.py`, `backend/tests/test_regulatory_context_builder.py`, `backend/tests/test_regulatory_context_api.py`
**Commit:** 0ffd1d5
**Status:** fixed: requires human verification
**Applied fix:** Candidate `SemanticBinding` rows now project as separate `semantic_binding_candidate` facts with `candidate_type=semantic_binding`, binding id/source id, binding timestamp, `SemanticBinding` provenance, and the persisted draft or AI-suggested lifecycle. Candidate concepts without effective versions remain separate semantic-concept candidates. Added two-binding stable identity coverage and HTTP lifecycle/provenance assertions.

## Verification

Verification ran in the isolated review-fix worktree.

- Focused RED/GREEN tests were run for both findings; each regression failed before its source fix and passed afterward.
- Candidate-focused builder tests: 22 passed.
- Candidate lifecycle HTTP test: 1 passed.
- Query budget tests: builder acceptance/effective-version 2 passed; HTTP budget 1 passed.
- Phase 9 core suite: `python -m pytest -q tests/test_regulatory_context_contract.py tests/test_regulatory_context_builder.py tests/test_regulatory_context_api.py tests/test_semantic_layer.py tests/test_semantic_migration.py` — 89 passed, 4 pre-existing SQLite datetime-adapter warnings.
- Syntax/bytecode: `python -m compileall -q app` — passed.
- Query budgets remained unchanged: builder acceptance 21, effective-version batch 14, HTTP 22.

---

_Fixed: 2026-08-23T03:39:43+08:00_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: 2_
