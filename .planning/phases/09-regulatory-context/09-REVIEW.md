---
phase: 09-regulatory-context
reviewed: 2026-08-22T19:28:50Z
depth: standard
review_type: fix_re_review
reviewed_commits:
  - 56dea4d
  - ba4a8f8
  - 548b750
  - cddecd6
files_reviewed: 4
files_reviewed_list:
  - backend/app/services/semantic/context_builder.py
  - backend/app/services/semantic/context_collectors.py
  - backend/tests/test_regulatory_context_api.py
  - backend/tests/test_regulatory_context_builder.py
findings:
  critical: 0
  warning: 2
  info: 0
  total: 2
status: issues_found
---

# Phase 09: Code Review Re-review Report

**Reviewed:** 2026-08-22T19:28:50Z
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

The four fix commits were re-reviewed only against WR-01 through WR-04 and regressions introduced by those fixes. WR-02, WR-03, and WR-04 are closed. WR-01 remains open for an explicit-concept/target mismatch that the new preference-only binding sort does not reject. The WR-01 fix also introduces one lifecycle/provenance regression for draft binding candidates.

The Phase 09 focused suite passed: 87 tests with four pre-existing SQLite datetime-adapter warnings. Additional read-only probes reproduced both remaining findings. No Critical issue was found.

## Re-review Status

| Finding | Status | Verification |
|---|---|---|
| WR-01 | **OPEN** | Same-target candidate binding is isolated, but an unrelated confirmed binding is still selected when `semantic_concept_id` and a different target are supplied together. |
| WR-02 | **CLOSED** | Completeness counts and trusted evidence facts now share `trusted_evidence_rows`; candidate-only evidence no longer suppresses `MISSING_EVIDENCE`. |
| WR-03 | **CLOSED** | Evidence references, per-section facts, global facts, conflicts, and open questions are bounded before response validation; truncation metadata is emitted. |
| WR-04 | **CLOSED** | `not_linked` audit facts remain visible but are excluded from the persisted-lineage completeness count. |

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: Explicit semantic concept can still borrow a confirmed binding from an unrelated target

**Files:** `backend/app/services/semantic/context_collectors.py:160-195`, `backend/app/services/semantic/context_collectors.py:422-446`

**Issue:** When `semantic_concept_id` is explicit, `_semantic_inputs()` loads every visible binding for that concept without constraining the binding to the request's target identities. `_semantic_binding_sort_key()` only ranks matching identities first; if none match, the first unrelated confirmed binding is still selected. The builder then cites that binding on the confirmed semantic fact and sets `has_semantic_binding` true. A request for target field B plus a concept bound only to target field A therefore returns evidence `target_field:A` for target B and omits `MISSING_CONFIRMED_SEMANTIC_BINDING`. The original cross-target authority contamination remains possible.

**Fix:** When any target identity is present, filter confirmed and candidate bindings to those identities before selection and gap calculation. Concept-only requests may retain concept-wide behavior. Add a regression test combining an explicit concept with a different same-project target and assert that the unrelated binding is not cited and the confirmed-binding gap remains open.

```python
target_identities = _requested_target_identities(request, target)
if target_identities:
    bindings = [
        binding for binding in bindings
        if (str(binding.entity_type), int(binding.entity_id)) in target_identities
    ]
```

### WR-05: Draft binding candidates are emitted with AI-suggested concept lifecycle and provenance

**Files:** `backend/app/services/semantic/context_collectors.py:196-207`, `backend/app/services/semantic/context_collectors.py:1820-1865`, `backend/tests/test_regulatory_context_builder.py:424-452`

**Issue:** Commit `56dea4d` newly projects candidate bindings through `_semantic_candidate_fact()`, but that helper always emits `candidate_type="semantic_concept"`, `source_model="SemanticConcept"`, the concept id, and `FactState.AI_SUGGESTED`. A persisted binding whose status is `draft` is therefore returned as an AI-suggested concept candidate rather than a draft binding candidate. Multiple candidate bindings for the same concept also share the same candidate/source identity, leaving only evidence references to distinguish them. This loses the lifecycle and identity of the row actually under review; the added regression test codifies the incorrect `draft -> ai_suggested` conversion.

**Fix:** Project candidate bindings with their own identity, timestamp, and lifecycle. Keep concept candidates separate for candidate concepts without effective versions.

```python
ContextFact(
    fact_type="semantic_binding_candidate",
    value=CandidateContextValue(
        candidate_type="semantic_binding",
        candidate_id=binding.id,
        # ...
    ),
    state=FactState(binding.status),
    source_id=binding.id,
    provenance=ContextProvenance(
        source_model="SemanticBinding",
        source_id=binding.id,
        # ...
    ),
)
```

Update the test to require `FactState.DRAFT` for a draft binding and add a two-binding case proving stable, distinct candidate identities.

## Closed Findings

### WR-02: Candidate-only mapping evidence suppresses a trusted evidence gap — CLOSED

Verified by direct code trace and `test_candidate_mapping_evidence_does_not_suppress_trusted_evidence_gap`.

### WR-03: Unbounded collectors violate the public contract — CLOSED

Verified at 50/51 evidence references, 500/501 section facts, 1,000/1,001 global facts, and through the HTTP 200 regression test.

### WR-04: `not_linked` mappings suppress the missing-lineage question — CLOSED

Verified by the dedicated audit-visibility/completeness regression test.

---

_Reviewed: 2026-08-22T19:28:50Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
