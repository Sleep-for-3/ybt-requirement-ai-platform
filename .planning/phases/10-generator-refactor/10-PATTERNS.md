# Phase 10: Generator Refactor - Pattern Map

**Mapped:** 2026-08-23  
**Files classified:** 15  
**Files with an exact or role-match analog:** 15 / 15  
**Search scope:** `backend/app/services/{mapping,semantic,llm,governance}`, `backend/app/api`, `backend/tests`

## Scope and Compatibility Anchors

- Keep `RegulatoryContextBuilder.build(request, authorized_project=...)` as the only production entry for shared facts. Generator code may load and mutate its own task row, but must not query peer mappings, evidence, knowledge, candidates, metadata, lineage, history, or catalog facts directly.
- Preserve the four prompt keys and four structured outputs in `backend/app/services/llm/{prompt_runtime,structured_outputs}.py`; do not introduce a universal generator or output model.
- Generation changes `ai_generated_content` and task-local draft fields only. `final_content` changes only through existing adopt/review routes.
- Existing route suffixes and response models remain stable. `as_of` is additive and optional.
- No frontend, migration, dependency, reporting-period store, Context contract redesign, SQL generator, or semantic-impact work belongs in this phase.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/app/services/semantic/context_collectors.py` | service | batch + transform + read-only DB | same file: `collect_base_context`, `_target_scope`, `_target_field_fact` | exact extension |
| `backend/app/services/mapping/generator_context.py` | service | request-response orchestration | `backend/app/services/semantic/context_builder.py` | role/data-flow match |
| `backend/app/services/mapping/context_adapters.py` | service | zero-I/O transform | `backend/app/services/semantic/context_conflicts.py` + `context_authority.py` | role-match |
| `backend/app/services/mapping/generation_readiness.py` | service/policy | zero-I/O transform | `backend/app/services/semantic/context_conflicts.py` | role-match |
| `backend/app/services/mapping/source_to_mart_generator.py` | service | request-response + CRUD | same file: `generate_source_to_mart_draft`, `_apply_output` | exact migration |
| `backend/app/services/mapping/mart_to_ybt_generator.py` | service | request-response + CRUD | same file: `generate_mart_to_ybt_draft`, `_apply_output` | exact migration |
| `backend/app/services/mapping/scenario_draft_generator.py` | service | request-response + CRUD | same file: `generate_business_draft`, `generate_technical_draft` | exact migration |
| `backend/app/api/mapping_rules.py` | route/controller | request-response | `backend/app/api/regulatory_context.py` + existing generate/adopt routes | exact route + auth role-match |
| `backend/app/api/scenario_mappings.py` | route/controller | request-response | `backend/app/api/regulatory_context.py` + existing editability routes | exact route + auth role-match |
| `backend/app/api/jobs.py` | route/background handler | batch + event-driven | same file: `_draft_handler`; `deliverables.py` queued handler | exact caller migration |
| `backend/app/api/deliverables.py` | route/background handler | batch + event-driven | same file: `_deliverable_generate_handler`; `jobs.py` `_draft_handler` | exact caller migration |
| `backend/tests/test_generator_context_adapters.py` | test | transform + request-response | `backend/tests/test_regulatory_context_builder.py` | role/data-flow match |
| `backend/tests/test_double_layer_mapping.py` | test | request-response + CRUD | same file: `test_double_layer_mapping_end_to_end_api` | exact extension |
| `backend/tests/test_scenario_traceability.py` | test | request-response + CRUD | same file: `test_scenario_mappings_adopt_drafts_quality_checks_and_knowledge_search` | exact extension |
| `backend/tests/test_regulatory_context_builder.py` | test | batch + transform + query-budget | same file: builder acceptance/query tests | exact extension |

## Pattern Assignments

### `backend/app/services/semantic/context_collectors.py`

**Symbols:** `collect_base_context`, `_target_scope`, new metadata helpers, evidence/lineage-connected catalog batching.

**Copy the collector ownership boundary** (`context_collectors.py:1-5`):

```python
"""Project-scoped collectors for the RegulatoryContext projection.

Collectors own SQL and return typed, bounded facts.  They accept the Project
already authorized by PermissionService; caller-supplied institution scope is
never accepted or inferred from free text.
"""
```

**Copy the typed fact construction shape** (`context_collectors.py:1934-1974`): build `ContextProvenance`, bounded `ContextAttribute` values, then a `ContextFact` whose authority comes from `authority_for_source` and whose state is explicit.

```python
return ContextFact(
    fact_type="target_field_metadata",
    value=MetadataContextValue(..., attributes=attributes),
    authority=authority_for_source(source_type),
    state=FactState.OBSERVED,
    source_type=source_type,
    source_id=field.id,
    observed_at=observed_at,
    confidence=1.0,
    provenance=provenance,
)
```

**Copy the scope guard** (`context_collectors.py:370-406`): every requested `TargetField`, `TargetTable`, and `MartField` query includes `project_id`; a mismatch raises before facts are emitted.

**Copy the stable collection finish** (`context_collectors.py:294-321`): sort each section before returning `CollectedContext`, and name collectors in build metadata.

**Required divergence:** `collect_base_context` currently emits metadata only for `target_field` (`209-212`). Add bounded MartField/MartTable descriptors when `mart_field_id` is scoped, and only evidence/lineage-connected `CatalogColumn` descriptors for Scenario technical safety. Batch IDs; do not dump all project catalog rows. If fixed SQL count rises above 21, the plan must document the exact delta while keeping row-growth count constant.

---

### `backend/app/services/mapping/generator_context.py`

**Proposed symbols:** `ResolvedGenerationDate`, `resolve_generation_as_of`, `build_generation_context`, compact trace/question helpers.

**Analog:** `backend/app/services/semantic/context_builder.py`.

**Copy the explicit authorized-project interface and fail-closed scope check** (`context_builder.py:43-59`):

```python
class RegulatoryContextBuilder:
    def __init__(self, db: Session):
        self.db = db

    def build(self, request: RegulatoryContextRequest, *, authorized_project: Project) -> RegulatoryContext:
        if int(request.project_id) != int(authorized_project.id):
            raise ValueError("request project_id does not match the authorized project")
        collected = collect_base_context(self.db, authorized_project, request)
```

**Copy the metadata/trace extraction pattern** (`context_builder.py:67-99`): collect sorted retrieval IDs, counts, policy versions, `as_of`, input scope, warnings, and truncation without persisting another Context copy.

**Date convention:** use `datetime.date`, return both resolved date and source, and inject `today_provider` for tests. Current persistence has no legitimate middle fallback tier; do not infer a date from `created_at`, review timestamps, `report_name`, or free-text `reporting_condition`.

**Required divergence:** unlike `RegulatoryContextBuilder`, this seam coordinates a task snapshot and generation trace. It must still issue no shared-fact ORM queries and must call the builder exactly once in `ContextMode.CANDIDATE`. Builder/authorization failure propagates; there is no legacy branch.

---

### `backend/app/services/mapping/context_adapters.py`

**Proposed symbols:** `SourceToMartContextAdapter`, `MartToYbtContextAdapter`, `ScenarioContextAdapter` (or repository-style equivalents), typed task snapshots/projections, question merge, physical-source whitelist.

**Analog:** pure transformation in `backend/app/services/semantic/context_conflicts.py` plus authority policy in `context_authority.py`.

**Copy the pure-input/pure-output boundary** (`context_conflicts.py:1-5,25-71`): accept collected/typed facts, execute no SQL, create typed results, and return a deterministic sort.

**Use the canonical rank table rather than duplicating weights** (`context_authority.py:43-57`):

```python
AUTHORITY_RANKS = MappingProxyType({
    AuthorityRank.FORMAL: 900,
    AuthorityRank.HUMAN_CONFIRMED: 900,
    AuthorityRank.REGULATORY: 850,
    AuthorityRank.SEMANTIC: 800,
    AuthorityRank.MAPPING: 700,
    AuthorityRank.LINEAGE: 600,
    AuthorityRank.METADATA: 500,
    AuthorityRank.HISTORICAL: 400,
    AuthorityRank.RETRIEVED: 300,
    AuthorityRank.INFERRED: 200,
})
```

**Deterministic-order analogs:** fact sections use `(fact_type, source_type, source_id)` (`context_collectors.py:1977-1978`); candidates use `(rank_tier, candidate_type, candidate_id)` (`1981-1985`). The adapter may put descending authority first, then these stable keys, but must not depend on DB order.

**Projection convention:** return typed `prompt_text`, all selected `confidentiality_levels`, readiness, Context question constraints, trace summary, and Scenario-technical `allowed_physical_sources`. Exclude volatile `built_at` and retrieval IDs from prompt text; retain them in audit. Never serialize `context.model_dump()` wholesale.

**Required divergence:** there is no exact adapter analog. The planner must lock deterministic character/fact/question/conflict budgets and a stable truncation marker. Scenario business and technical may share infrastructure, but keep distinct projections/instructions and never accept ORM `__dict__`.

---

### `backend/app/services/mapping/generation_readiness.py`

**Proposed symbols:** `GenerationReadiness`, `evaluate_readiness`, confidence normalization/capping.

**Analog:** `backend/app/services/semantic/context_conflicts.py:13-22,74-143`.

Reuse the exact Context codes rather than spelling local variants: `MISSING_CONFIRMED_SEMANTIC_BINDING`, `MISSING_CONFIRMED_SEMANTIC_VERSION`, `MISSING_SOURCE_MAPPING`, `MISSING_MART_TO_YBT_MAPPING`, `MISSING_LINEAGE`, `STALE_LINEAGE`, `MISSING_KNOWLEDGE`, `MISSING_EVIDENCE`, `HISTORICAL_ONLY_DEFINITION`, and `CONFLICTING_AUTHORITATIVE_FACTS`.

**Typed model convention:** follow Pydantic models already used by `structured_outputs.py:3-12`, but readiness should use `ConfigDict(extra="forbid")`, not the output compatibility model's `extra="ignore"`.

**Task-aware policy divergence:** a generic “any missing mapping blocks” rule is wrong. `MISSING_SOURCE_MAPPING` is non-blocking for Source-to-Mart, and `MISSING_MART_TO_YBT_MAPPING` is non-blocking for Mart-to-YBT. High-authority task-core conflicts, target/scope mismatch, governance prohibition, and Context construction failure block before the model call. Normalize model confidence to `low|medium|high` and enforce the cap after structured validation but before mutation.

---

### `backend/app/services/mapping/source_to_mart_generator.py`

**Keep from current file:** task row load/not-found behavior (`10-13`), task-specific prompt key and `SourceToMartOutput` boundary (`50`), `_apply_output` field ownership (`57-72`), non-SQL final draft rendering (`75-95`), commit/refresh (`51-54`).

```python
mapping = db.get(SourceToMartMapping, mapping_id)
if mapping is None:
    raise ValueError("Source-to-mart mapping not found")
...
output = await execute_runtime_chat(..., SourceToMartOutput, ...)
_apply_output(mapping, output)
db.commit()
db.refresh(mapping)
```

**Remove after cutover:** direct MartField/MartTable/evidence reads (`15-25`), `_source_candidates` (`98-110`), `_evidence_text` (`113-120`), `HybridRetriever` import/call (`7,50`).

**Required divergence:** call the shared Context seam before the runtime; merge existing human questions + Context questions + AI questions instead of `new or old` at line 70; cap confidence; audit Context/date/readiness; never assign `final_content`.

---

### `backend/app/services/mapping/mart_to_ybt_generator.py`

**Keep from current file:** task row load (`18-21`), prompt key and `MartToYbtOutput` (`64`), output field application (`71-83`), business final renderer (`86-103`), commit/refresh (`65-68`).

**Remove after cutover:** Target/Mart descriptor reads (`23-27`), evidence query (`28-35`), `_source_to_mart_summary` (`106-119`), `_evidence_text` (`122-129`), direct `HybridRetriever` (`15,64`).

**Context mapping analog:** Context collectors already treat approved Source-to-Mart mappings as trusted (`context_collectors.py:71-83`) and emit/sort mapping facts (`213-246,294-300`). The adapter must derive the upstream summary from approved Context `rule_text`; do not preserve the current fallback chain `final_content or business_rule or ai_generated_content` (`mart_to_ybt_generator.py:117`) because it mixes lifecycle states.

**Required divergence:** same question merge, confidence cap, trace audit, single-builder-call, and no-`final_content` mutation rules as Source-to-Mart.

---

### `backend/app/services/mapping/scenario_draft_generator.py`

**Keep from current file:** distinct runtime keys/output schemas (`18,45`), distinct business/technical field application (`19-29,46-59`), Scenario audit action names (`28,57`), and task-local commit/refresh (`29-31,58-60`).

**Physical safety behavior to preserve semantically** (`94-113`): existing values may remain unchanged; a new schema/table/column tuple is accepted only when exact governed metadata proves it.

**Remove after cutover:** direct TargetField/ProductScenario/peer/evidence/RAG queries (`15-18,38-45`), `_context` ORM dump (`63-73`), and `_physical_value_allowed` DB query (`94-113`).

**Required divergence:** the Scenario adapter supplies an exact normalized Context whitelist. Unknown proposed physical identifiers are skipped, current values retained, and a deterministic question appended; non-physical processing logic may still be applied when readiness permits. Preserve editability checks in the API before generation and preserve `final_content` byte-for-byte.

---

### `backend/app/api/mapping_rules.py`

**Route compatibility analog:** current generate/adopt pairs at `72-89` and `172-189`. Keep route suffixes and response models; adoption alone copies `ai_generated_content` to `final_content` and resets status to draft.

**Authorization + date analog:** `backend/app/api/regulatory_context.py:20-53`.

```python
def get_regulatory_context(
    project_id: int,
    principal: CurrentPrincipal,
    as_of: date = Query(...),
    ...,
):
    project = PermissionService(db, principal).require_project_permission(
        project_id, "project.view"
    )
    ...
    return builder.build(request, authorized_project=project)
```

**Required divergence:** generation routes are resource-ID scoped, so first load the mapping through the existing guard/404 path, then obtain the permission-qualified `Project` for that resolved `mapping.project_id`; do not trust a client project ID. Add `as_of: date | None = Query(default=None)` only to generate routes. Map readiness/governance blocking to one explicit additive diagnostic response while keeping existing 404/422 behavior.

---

### `backend/app/api/scenario_mappings.py`

**Keep the editability and adoption boundaries** (`76-96,177-197`):

```python
mapping = _business_or_404(db, mapping_id)
ensure_scenario_mapping_editable(db, "scenario_business", mapping.id)
...
mapping.final_content = mapping.ai_generated_content  # adopt route only
```

The technical route uses the same sequence with `"scenario_technical"`. The shared resource guard maps generation to exact permissions `business.edit` and `technical.edit` (`resource_guard.py:78-83`).

**Auth/date analog:** use the explicit `CurrentPrincipal` + `PermissionService(...).require_project_permission(...)` handoff from `api/regulatory_context.py:20-53`, after resolving the task row's project.

**Required divergence:** add optional `as_of` only to the two generate routes; pass authorized Project and actor to the service; keep confirm/reject/adopt schemas and behavior unchanged.

---

### `backend/app/api/jobs.py`

**Current caller pattern:** `_draft_handler` selects only rows with `model.project_id == job.project_id`, filters field/scenario, invokes the generator, records an item, and rolls back per failed row (`jobs.py:167-183`).

```python
statement = select(model).where(model.project_id == job.project_id)
...
asyncio.run(generator(db, row.id))
...
except Exception as exc:
    db.rollback()
```

**Required divergence:** load/validate the job-scoped `Project` once and pass it plus `job.created_by` to every generator invocation; existing queued payloads provide no `as_of`, so pass `None` and let the shared resolver use the injected current business date. Do not silently keep an old two-argument callable path.

---

### `backend/app/api/deliverables.py`

**Current caller pattern:** `_deliverable_generate_handler` validates package/job project equality (`407-411`), skips existing governed content (`430-443`), and invokes business/technical generators per row (`434,443`). Preserve all three guards.

**Required divergence:** resolve the package/job-scoped `Project` and pass Project/actor/`as_of=None` explicitly. Decide in the plan whether a blocked generation is recorded as the handler's existing `blocked` count or `failed`; the current function declares both counters (`412`) but the shown generator loop records only completed/skipped and outer failures.

---

### `backend/tests/test_generator_context_adapters.py`

**Analog:** `backend/tests/test_regulatory_context_builder.py`.

Copy its direct service-test style: seed project-scoped fixtures, resolve `_authorized_project`, build typed input, and assert typed fields (`73-108`). Copy the fail-before-dependency monkeypatch pattern (`111-133`) for no-fallback tests, stable repeat projection assertions (`151-185`), and SQL event counting (`1326-1387`).

Minimum contract cases: explicit/today date source, three adapter families/four task variants, authority ordering, exact truncation, missing-mapping exceptions, authoritative conflict block, stable three-source question merge, confidence cap, all-selected-fact confidentiality, Scenario physical whitelist, zero adapter SQL, builder exception/no model call/no mutation.

---

### `backend/tests/test_double_layer_mapping.py`

**Keep the full API fixture style** (`1-12,205-246`) and extend the existing end-to-end test instead of replacing it.

**Compatibility assertions to copy** (`130-159`): snapshot human `final_content`, call both `generate-draft` routes, assert it survives, assert `ai_generated_content` is populated/non-SQL, then prove only explicit adoption copies it to final.

Add focused cases for optional `as_of`, temporal version choice, authorized Project handoff, one builder call/no legacy calls, Source-to-Mart gap exception, approved-only upstream summary, blocked conflict diagnostics, question idempotence, confidence cap, audit trace, cross-project isolation, and fixed-growth query behavior.

---

### `backend/tests/test_scenario_traceability.py`

**Compatibility analog:** `test_scenario_mappings_adopt_drafts_quality_checks_and_knowledge_search` (`49-205`). Its key boundary is lines `94-124`: manual business/technical final content survives generation, AI drafts are populated, and adoption is the only copy to final.

Extend with same-Context/different-output assertions, editability/governance block, explicit snapshot (no ORM `__dict__`), current physical value retention, unknown physical tuple refusal + question, Context-whitelisted tuple acceptance, Context provenance/confidentiality audit, and job/Deliverable caller coverage.

---

### `backend/tests/test_regulatory_context_builder.py`

**Keep the existing acceptance conventions:** typed project/institution/date assertions (`73-108`), mismatch rejection before collectors (`111-133`), projection-only/no-authoritative-mutation snapshot (`136-148`), deterministic rebuild normalization (`151-185`), and retrieval-log trace (`188-214`).

**Query-budget convention:** attach/remove SQLAlchemy `before_cursor_execute` in `try/finally`, compare baseline and row-growth counts, and snapshot authoritative rows (`1326-1387`). Add MartField/MartTable and connected CatalogColumn metadata fixtures, foreign-project/institution negatives, bounded order assertions, and update `ACCEPTANCE_QUERY_BUDGET` only with an explicit fixed-delta rationale.

## Shared Patterns

### Authorization and Isolation

**Source:** `backend/app/api/regulatory_context.py:20-53`, `backend/app/services/auth/resource_guard.py:19-53,78-107`, `backend/app/services/semantic/context_builder.py:49-58`.

Apply to all direct and background generation callers: resolve resource project, require the existing exact permission, pass the resulting Project object, and let Builder verify request/project equality. Institution scope comes only from that Project.

### Model Runtime and Confidentiality

**Source:** `backend/app/services/llm/prompt_runtime.py:17-25,43-48,51-82,95-119,163-205`.

Keep prompt keys stable, call `get_prompt_runtime`, aggregate confidentiality for Project plus every selected fact, call `prepare_model_input`, then `execute_runtime_chat` with the existing task schema and Context retrieval-log linkage. Do not add another LLM service or redaction implementation.

### Structured Output Boundary

**Source:** `backend/app/services/llm/structured_outputs.py:6-89`.

Keep `SourceToMartOutput`, `MartToYbtOutput`, `ScenarioBusinessOutput`, and `ScenarioTechnicalOutput` distinct. Their validators establish minimum content, but confidence is currently free text and therefore must be normalized/capped by Phase 10 policy before persistence.

### Audit and Error Handling

**Source:** `backend/app/services/governance/audit.py:15-72`, `backend/app/services/llm/prompt_runtime.py:175-205`.

Use `record_audit`; it recursively bounds/redacts summaries. Store Context schema/date/counts/codes/IDs/readiness/projection hash/truncation/output-field names, never raw Context or prompt. Runtime failures already create a failed `ModelCallLog` and commit before re-raising. Define a consistent generator audit transaction for success, readiness block, Context failure, and confidentiality denial without leaving partial task mutations.

### Determinism

**Source:** `context_builder.py:125-152`, `context_collectors.py:294-301,1977-1985`, `test_regulatory_context_builder.py:151-185`.

Sort before capping; use stable section order and truncation markers; exclude volatile build time/log IDs from prompt hashing while preserving them in audit; inject the current-date provider in tests.

### Human Final-Content Boundary

**Source:** `mapping_rules.py:80-89,180-189`, `scenario_mappings.py:76-86,177-187`, `test_double_layer_mapping.py:130-159`, `test_scenario_traceability.py:94-124`.

Generation must not assign `final_content` or promote approved/confirmed status. Adoption remains explicit and test-visible.

## Divergences Requiring an Explicit Plan Decision

| Decision | Why it cannot be copied verbatim | Required planning outcome |
|---|---|---|
| Blocked-generation HTTP shape/status | No existing generator readiness exception; research recommends 409 but current routes only translate `ValueError` to 404. | Name the exception, additive detail keys, and route mapping; preserve old success schemas/404/422. |
| Question provenance storage | Task rows store nullable Text, while Context questions are typed. | Decide whether `[CTX:...]`/`[AI]` prefixes are user-visible or provenance lives only in AuditLog; require stable idempotent dedup either way. |
| Candidate-mode exposure | Generation needs ranked candidates, but candidate mode includes draft/AI-suggested lifecycle facts. | Confirm all generators use candidate mode and adapters label/filter lifecycle without promoting it. |
| Scenario CatalogColumn scope | Current direct query accepts any enabled exact project tuple; Context currently projects none. | Define evidence/lineage connection rules and conservative behavior when coverage is sparse; never broaden to all project catalog rows. |
| Query budget after metadata enrichment | Current acceptance ceiling is 21. Batched Mart/catalog projection may add a fixed query. | Preserve 21 if possible; otherwise record exact before/after delta and keep growth count identical. |
| Service signature/actor type | Direct callers have `CurrentPrincipal`; background jobs have only `created_by` and project ID. | Define one explicit authorized Project + actor contract for all six call sites; no compatibility fallback overload. |
| Blocked/failure audit transaction | A blocked attempt needs durable diagnostics but no draft mutation; runtime failures currently commit their ModelCallLog. | Specify transaction/rollback order and test byte-for-byte task snapshots after builder, readiness, confidentiality, and runtime failures. |
| Prompt budgets | No existing task-adapter budget exists; research suggests 6,000 default/12,000 hard cap. | Lock configuration source, per-section caps, and exact truncation marker before implementation tests. |

## No Exact Analog Found

The three proposed modules have strong role matches but no exact repository precedent:

| File | Missing exact precedent | Planner instruction |
|---|---|---|
| `generator_context.py` | No shared generator date/build/trace seam | Combine Builder's explicit Project boundary with existing runtime/audit transaction behavior; do not invent persistence. |
| `context_adapters.py` | No bounded task-specific Context projection | Implement as strict typed zero-I/O transforms and test exact serialized output. |
| `generation_readiness.py` | No task-aware generator blocking/confidence policy | Reuse Context codes and Pydantic conventions; lock task matrix explicitly. |

## Metadata

**Strong analog groups read:** 5 — Context orchestration/collection, pure Context policy, generator runtime/write boundary, authorized API boundary, regression/query-budget tests.  
**Large files inspected by targeted non-overlapping ranges:** `context_collectors.py`, `test_regulatory_context_builder.py`.  
**Worktree note:** unrelated frontend and untracked user changes existed during mapping; this artifact does not include or authorize changes to them.  
**Pattern extraction date:** 2026-08-23
