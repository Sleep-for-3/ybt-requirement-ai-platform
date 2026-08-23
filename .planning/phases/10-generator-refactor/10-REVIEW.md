---
phase: 10-generator-refactor
reviewed: 2026-08-23T12:03:14Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - backend/app/api/deliverables.py
  - backend/app/api/jobs.py
  - backend/app/api/mapping_rules.py
  - backend/app/api/scenario_mappings.py
  - backend/app/services/mapping/context_adapters.py
  - backend/app/services/mapping/generation_readiness.py
  - backend/app/services/mapping/generator_context.py
  - backend/app/services/mapping/mart_to_ybt_generator.py
  - backend/app/services/mapping/scenario_draft_generator.py
  - backend/app/services/mapping/source_to_mart_generator.py
  - backend/app/services/semantic/context_collectors.py
  - backend/tests/test_deliverables.py
  - backend/tests/test_double_layer_mapping.py
  - backend/tests/test_generator_context_adapters.py
  - backend/tests/test_governance.py
  - backend/tests/test_regulatory_context_api.py
  - backend/tests/test_regulatory_context_builder.py
  - backend/tests/test_scenario_traceability.py
findings:
  critical: 2
  warning: 1
  info: 0
  total: 3
status: issues_found
---

# Phase 10: Code Review Report

**Reviewed:** 2026-08-23T12:03:14Z  
**Depth:** standard  
**Files Reviewed:** 18  
**Status:** issues_found

## Summary

The Context-backed direct generators generally preserve one-build, temporal trace, bounded projection, and optimistic stale-write behavior. However, two production paths still violate the locked authority/governance boundary: Deliverable compilation bypasses `RegulatoryContextBuilder` and its task permissions, and the Source-to-Mart/Mart-to-YBT services can regenerate already-approved rows without an editability check. Source-to-Mart also reopens resolved Context questions.

Focused validation was green (`51 passed in 375.54s`; `python -m compileall -q app` succeeded), but the tests do not exercise the failing paths described below.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Deliverable compilers bypass the sole Context authority path and technical-edit authorization

**Classification:** BLOCKER  
**File:** `backend/app/api/deliverables.py:538-556` (also `backend/app/api/deliverables.py:790-797`)  
**Issue:** The queued Deliverable handler directly calls `compile_source_to_mart` and `compile_mart_to_ybt`, and the public compile routes expose the same mutating functions with only `deliverable.generate`. Those callees issue legacy peer ORM queries over Scenario/Source/Mart rows and write `ai_generated_content` and mapping summary fields without one candidate `RegulatoryContextBuilder` build, `as_of`, readiness, or Context trace. They also treat unfiltered draft peer rows as usable input (`compile_source_to_mart`) and any upstream row as `evidence_supported` (`compile_mart_to_ybt`). Because the `business_analyst` role has `deliverable.generate` but not `technical.edit`, these paths additionally let that role mutate technical mapping rows that the governed generator routes correctly protect with `technical.edit`. This is an authorization bypass and a direct violation of D-01/D-02/D-05/D-21 and the no-promotion authority rule.

The current Deliverable test at `backend/tests/test_scenario_traceability.py:986-1029` creates only Scenario rows and therefore never enters the Source/Mart compiler loops; the static no-fallback test inspects only the four generator service functions.

**Fix:** Route Source-to-Mart and Mart-to-YBT work from both Deliverable and direct compile endpoints through `generate_source_to_mart_draft` / `generate_mart_to_ybt_draft` with the frozen actor, a `technical.edit`-authorized Project, optional/resolved date, readiness, and one Context build. If deterministic compilation must remain as a distinct feature, make it read-only and consume an already-authorized typed Context projection; it must not query peer shared-fact rows or mutate mapping records. Add tests proving one builder call, `technical.edit` enforcement, and exclusion of draft/rejected/candidate peer rows for both direct compile and Deliverable jobs.

### CR-02: Approved double-layer mappings remain writable through generate-draft

**Classification:** BLOCKER  
**File:** `backend/app/services/mapping/source_to_mart_generator.py:64-80` (also `backend/app/services/mapping/source_to_mart_generator.py:128-182`, `backend/app/services/mapping/mart_to_ybt_generator.py:57-73`, and `backend/app/services/mapping/mart_to_ybt_generator.py:121-175`)  
**Issue:** Neither double-layer service performs a task-specific editability/status check before Context/model execution or again after the authoritative row lock. Snapshot comparison only detects a change relative to the captured status; an unchanged `approved` mapping therefore passes and `_apply_output` rewrites its structured rules/summaries, confidence, questions, and AI draft while the row remains formally approved. This permits post-approval mutation outside adoption/review governance and contradicts the Phase 10 plan's required status/editability revalidation. Scenario generators correctly call `ensure_scenario_mapping_editable` before and inside the write boundary; these two services do not have an equivalent guard.

The current tests assert that model-supplied `mapping_status="approved"` cannot change a draft row, but never start generation from an already-approved task, so they miss this path.

**Fix:** Add a task-specific mapping editability policy and invoke it before building Context and after locking the current mapping in the fresh write transaction. Reject approved/review-locked/non-editable lifecycle states with a stable governed block before model execution, and revalidate after the model to close stale/governance races. Add direct-service and API tests for approved/reviewed mappings that assert zero model call, zero field/draft mutation, and a diagnosable non-success response.

## Warnings

### WR-01: Source-to-Mart reintroduces resolved Context questions as open task questions

**Classification:** WARNING  
**File:** `backend/app/services/mapping/context_adapters.py:155-168`  
**Issue:** `SourceToMartContextAdapter.project` copies every item in `context.open_questions` without filtering `resolution_state`. It then converts each item to `ContextQuestionConstraint`, which drops the resolution state. `merge_generation_questions` consequently treats a resolved item as open and appends it as `[CTX:<code>]`, and `pending_confirmation` remains true. The shared `_projection_inputs` path used by the other three adapters correctly filters `resolution_state == "open"`, so behavior is inconsistent and resolved governance work can be reopened on regeneration.

**Fix:** Apply the same `resolution_state == "open"` filter before the Source-to-Mart cap (or preserve the state in `ContextQuestionConstraint` and filter during prompt/merge). Add a regression containing both open and resolved Context questions and assert only the open item reaches the prompt, merged task text, trace codes, and pending-confirmation decision.

---

_Reviewed: 2026-08-23T12:03:14Z_  
_Reviewer: the agent (gsd-code-reviewer)_  
_Depth: standard_
