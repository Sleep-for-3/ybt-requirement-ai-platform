---
phase: 10-generator-refactor
reviewed: 2026-08-24T22:35:00+08:00
depth: standard
scope: gap-closure-5940fbb-parent-through-98e6350
reviewer: primary-orchestrator
specialized_reviewer_dispatch: skipped-by-permission-policy
files_reviewed: 14
findings:
  critical: 0
  warning: 0
  info: 0
  total: 0
resolved_findings: [CR-01, CR-02, WR-01]
status: clean
---

# Phase 10: Post-Gap Code Review Report

**Verdict:** CLEAN for the Phase 10 gap-closure range. The three findings from the 2026-08-23 review are closed by production changes and post-fix regression evidence.

The configured GSD code-review hook was executed inline by the primary orchestrator because the active workspace permission profile is unrestricted and project `AGENTS.md` prohibits launching Luna reviewer/tester agents under that permission. No alternate model or generic reviewer was substituted.

## Scope

Reviewed the existing files changed by `5940fbb^..98e6350` after filtering planning artifacts and deleted modules:

- `backend/app/api/deliverables.py`
- `backend/app/api/mapping_rules.py`
- `backend/app/api/target_fields.py`
- `backend/app/services/auth/resource_guard.py`
- `backend/app/services/governance/double_layer_review.py`
- `backend/app/services/llm/prompt_runtime.py`
- `backend/app/services/mapping/context_adapters.py`
- `backend/app/services/mapping/mart_to_ybt_generator.py`
- `backend/app/services/mapping/source_to_mart_generator.py`
- `backend/tests/test_deliverables.py`
- `backend/tests/test_double_layer_mapping.py`
- `backend/tests/test_generator_context_adapters.py`
- `backend/tests/test_legacy_mapping_retirement.py`
- `backend/tests/test_scenario_traceability.py`

Deleted modules were checked through reference scans and retirement tests:

- `backend/app/services/deliverables/source_to_mart_compiler.py`
- `backend/app/services/deliverables/mart_to_ybt_compiler.py`
- `backend/app/services/mapping_generator.py`

## Resolved Findings

### CR-01: Deliverable compiler authority and permission bypass - CLOSED

Direct compile and Deliverable queued Source/Mart paths now call the governed Source/Mart generators, pass the exact `technical.edit`-authorized Project and actor, and preserve optional `as_of` for direct calls. Both legacy compiler modules are deleted. Tests exercise direct function/HTTP calls, real queued rows, permission revocation, bounded item outcomes, and absence of legacy imports/calls.

### CR-02: Approved double-layer mappings writable through generation - CLOSED

`ensure_double_layer_mapping_editable` enforces draft-only, no-final-content, no-active-review state before Context/model work and again after fresh Project-to-task locking. Both generators record bounded governance-blocked audits and skip output application when the post-lock policy fails. Source and Mart tests cover approved, final, active-review, and concurrent governance transitions with zero model or draft mutation where required.

### WR-01: Resolved Source questions reopened - CLOSED

`SourceToMartContextAdapter` filters `resolution_state == "open"` before the deterministic cap and projection. Mixed and resolved-only regressions prove resolved questions are absent from prompt, merge, trace, pending state, and readiness behavior.

## Security And Regression Review

- The retired `/fields/{field_id}/generate-mapping` route resolves the resource and requires `technical.edit` before returning HTTP 410, preventing scope and retirement-detail disclosure.
- Direct and queued callers retain explicit actor validation, project permission checks, project/institution matching, and bounded diagnostics.
- The task row remains the only allowed task-local read outside RegulatoryContext; no ORM/RAG/evidence/history/lineage fallback was reintroduced.
- Post-model writes revalidate actor, permission, Project-to-task lock order, lifecycle policy, and full local snapshot before applying a whitelisted draft.
- Durable audit/job results contain bounded identifiers and reason codes, not raw Context, prompts, evidence, final content, or model output.
- Deleted constructor names and the retired prompt key have no remaining production references.

## Executed Evidence

- Focused gap suite: `79 passed`.
- Adjacent Phase 9/runtime/governance/retrieval suite: `176 passed`.
- Maximum backend suite: `404 passed, 2 deselected, 5 warnings`, exit 0.
- Unfiltered backend suite: only the two exact documented Windows baseline failures.
- `python -m compileall -q app`: PASS.
- `git diff --check 5940fbb^..98e6350`: PASS.

## Residual Qualification

Live PostgreSQL was unavailable. SQLite evidence validates application ordering, lifecycle revalidation, stale rejection, and atomic application, but does not verify production-driver `SELECT ... FOR UPDATE` blocking or concurrent commits. This remains a staging gate, not a code-review finding.

---

_Reviewed: 2026-08-24_
_Reviewer: primary orchestrator (specialized Luna dispatch skipped by permission policy)_
_Depth: standard_
