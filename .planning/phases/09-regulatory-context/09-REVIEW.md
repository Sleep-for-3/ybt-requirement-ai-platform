---
phase: 09-regulatory-context
reviewed: 2026-08-22T19:05:09Z
depth: standard
files_reviewed: 29
files_reviewed_list:
  - backend/alembic/versions/202608200016_semantic_concept_versions.py
  - backend/app/api/regulatory_context.py
  - backend/app/api/semantic.py
  - backend/app/main.py
  - backend/app/models/__init__.py
  - backend/app/models/semantic.py
  - backend/app/schemas/regulatory_context.py
  - backend/app/schemas/semantic.py
  - backend/app/services/auth/resource_guard.py
  - backend/app/services/governance/workflow.py
  - backend/app/services/retrieval/hybrid_retriever.py
  - backend/app/services/semantic/__init__.py
  - backend/app/services/semantic/context_authority.py
  - backend/app/services/semantic/context_builder.py
  - backend/app/services/semantic/context_collectors.py
  - backend/app/services/semantic/context_conflicts.py
  - backend/app/services/semantic/entity_adapter.py
  - backend/app/services/semantic/graph_service.py
  - backend/app/services/semantic/resolver.py
  - backend/app/services/semantic/status_policy.py
  - backend/app/services/semantic/version_service.py
  - backend/tests/test_governance.py
  - backend/tests/test_knowledge_rag.py
  - backend/tests/test_regulatory_context_api.py
  - backend/tests/test_regulatory_context_builder.py
  - backend/tests/test_regulatory_context_contract.py
  - backend/tests/test_semantic_layer.py
  - backend/tests/test_semantic_migration.py
  - backend/tests/test_uat.py
findings:
  critical: 0
  warning: 4
  info: 0
  total: 4
status: issues_found
---

# Phase 09: Code Review Report

**Reviewed:** 2026-08-22T19:05:09Z
**Depth:** standard
**Files Reviewed:** 29
**Status:** issues_found

## Summary

The Phase 09 implementation preserves the principal project/institution boundary: the route is protected by the resource guard, the endpoint independently calls `PermissionService.require_project_permission(..., "project.view")`, and the builder rejects a request/authorized-project mismatch before collection. The reviewed GET path does not mutate authoritative facts; its only persisted side effect is the explicitly permitted retrieval log.

Four correctness defects remain. Candidate lifecycle rows can influence trusted missing-data signals, `not_linked` mappings are counted as lineage, and unbounded collector output can violate the schema's own limits and turn otherwise valid reads into HTTP 400 responses. The focused SQLite suite passed (79 tests); live PostgreSQL migration execution was unavailable and is recorded only as a qualification, not as a finding.

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: Candidate bindings contaminate confirmed semantic provenance and suppress the confirmed-binding gap

**Files:** `backend/app/services/semantic/context_collectors.py:150-174`, `backend/app/services/semantic/context_collectors.py:378-448`, `backend/app/services/semantic/context_collectors.py:1682-1734`, `backend/app/services/semantic/context_conflicts.py:78-84`

**Issue:** Candidate mode loads `draft` and `ai_suggested` bindings together with confirmed bindings. `binding_by_concept.setdefault(...)` then chooses the first row by entity/id order, not by lifecycle authority. That row is attached as evidence to a `FactState.CONFIRMED` semantic version, and `has_semantic_binding` is set from `bool(bindings)`. A concept with only a draft binding therefore returns a confirmed semantic fact citing the draft association and omits `MISSING_CONFIRMED_SEMANTIC_BINDING`. If both draft and confirmed bindings exist, the lower-authority row can also win provenance selection.

**Fix:** Separate confirmed bindings from candidate bindings before projection. Use only confirmed bindings for trusted semantic-fact evidence and for `has_semantic_binding`; emit draft/AI bindings only as candidate facts. When several confirmed bindings remain, select deterministically by the requested target identity and then stable id.

```python
confirmed_bindings = [binding for binding in bindings if binding.status == "confirmed"]
confirmed_by_concept = {
    int(binding.semantic_concept_id): binding
    for binding in confirmed_bindings
}
# Trusted semantic facts use confirmed_by_concept only.
signals["has_semantic_binding"] = bool(confirmed_bindings)
```

Add a regression test where candidate mode has an effective confirmed version but only a draft binding; the draft binding must remain a candidate and `MISSING_CONFIRMED_SEMANTIC_BINDING` must be present.

### WR-02: Candidate-only mapping evidence suppresses a trusted evidence gap

**Files:** `backend/app/services/semantic/context_collectors.py:180-211`, `backend/app/services/semantic/context_collectors.py:288-310`, `backend/app/services/semantic/context_conflicts.py:123-132`

**Issue:** Mapping rows are partitioned into trusted and candidate groups, and only trusted evidence is projected into `knowledge_evidence`. However, `supporting_evidence_count` still uses `len(evidence_rows)`, which includes evidence attached only to draft/AI mappings in candidate mode. Consequently, an approved mapping with no evidence is treated as supported merely because an unrelated candidate mapping has evidence, so `MISSING_EVIDENCE` is incorrectly omitted. This is an authority-state contamination of the trusted completeness signal.

**Fix:** Derive a trusted evidence collection from `trusted_mapping_keys` once, use it both for trusted evidence facts and trusted gap counts, and keep candidate evidence scoped to candidate facts only.

```python
trusted_evidence_rows = [
    row for row in evidence_rows
    if (row.mapping_type, int(row.mapping_id)) in trusted_mapping_keys
]
signals["evidence_count"] = len(trusted_evidence_rows)
signals["supporting_evidence_count"] = (
    len(trusted_evidence_rows)
    + sum(bool(fact.evidence_references) for fact in regulatory)
    + sum(fact.fact_type == "retrieved_knowledge" for fact in retrieved)
)
```

Add a candidate-mode regression test with one evidence-free approved mapping and one evidenced draft mapping; `MISSING_EVIDENCE` must remain present.

### WR-03: Unbounded collectors can violate the public contract and convert valid GETs into HTTP 400

**Files:** `backend/app/services/semantic/context_collectors.py:150-278`, `backend/app/services/semantic/context_collectors.py:1528-1536`, `backend/app/schemas/regulatory_context.py:108-114`, `backend/app/schemas/regulatory_context.py:291-303`, `backend/app/schemas/regulatory_context.py:489-533`, `backend/app/services/semantic/context_builder.py:75-97`, `backend/app/api/regulatory_context.py:51-55`

**Issue:** The response contract limits each fact section to 500 items, all fact sections together to 1,000 items, and each fact/provenance evidence list to 50 references. Several collectors return all matching semantic, mapping, lineage, and mapping-evidence rows without enforcing those limits. `_mapping_evidence_refs()` likewise returns every reference. Valid persisted data can therefore raise a Pydantic `ValidationError` while the builder constructs `RegulatoryContext`; because it is a `ValueError`, the GET endpoint converts this server-side projection failure into HTTP 400. A direct 51-reference probe already fails at `ContextProvenance`, and current tests cover large retrieved evidence but not these unbounded mapping/lineage paths.

**Fix:** Apply deterministic ordering and caps before constructing contract models. Cap every evidence list at 50, every section at 500, and allocate a deterministic global fact budget of 1,000. Set `build_metadata.truncated = True` and add a bounded warning whenever rows are omitted; compute metadata counts from the emitted facts. Add boundary tests at 50/51 evidence references and 500/501 facts, plus a multi-section case crossing 1,000 total facts.

```python
references = _mapping_evidence_refs(evidence_rows[:50])
section = sorted(section, key=lambda fact: fact.deterministic_sort_key())[:500]
if omitted:
    metadata.truncated = True
    metadata.warnings.append("regulatory context output was deterministically truncated")
```

### WR-04: `not_linked` mappings are counted as persisted lineage and hide the missing-lineage question

**Files:** `backend/app/services/semantic/context_collectors.py:213-228`, `backend/app/services/semantic/context_collectors.py:288-299`, `backend/app/services/semantic/context_collectors.py:720-768`, `backend/app/services/semantic/context_collectors.py:1469-1515`, `backend/app/services/semantic/context_conflicts.py:106-112`

**Issue:** `collect_mapping_lineage_facts()` emits a lineage fact for every trusted source, mart, and technical mapping regardless of `lineage_status`. `_mapping_lineage_fact()` explicitly converts the default `not_linked` value into an observed lineage fact, and `lineage_count = len(lineage)` treats that record as a supporting path. Thus a target whose only mapping rows all say `not_linked` receives no `MISSING_LINEAGE` question. The returned payload describes the absence of a link, but the completeness signal interprets the row as the presence of lineage.

**Fix:** Track actual lineage availability independently of lineage-status audit facts. Count raw lineage edges and mapping lineage rows only when their status represents an existing path (for example `linked`, `verified`, and `stale`); retain `not_linked` facts for audit visibility but exclude them from `lineage_count`.

```python
has_persisted_path = fact.value.lineage_status in {"linked", "verified", "stale"}
signals["lineage_count"] = sum(
    fact.fact_type == "raw_lineage" or has_persisted_path_for(fact)
    for fact in lineage
)
```

Add a regression test with approved mappings whose only lineage status is `not_linked` and no raw lineage edges; `MISSING_LINEAGE` must be emitted.

---

_Reviewed: 2026-08-22T19:05:09Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
