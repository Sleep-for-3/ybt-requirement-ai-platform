# Phase 10: Generator Refactor - Research

<user_constraints>
## User Constraints (from CONTEXT.md)

Source: [VERIFIED: .planning/phases/10-generator-refactor/10-CONTEXT.md:7-61]

### Locked Decisions

Phase 10 migrates the existing Source-to-Mart, Mart-to-YBT, scenario-business, and scenario-technical draft generators to consume the verified Phase 9 `RegulatoryContext` as their sole shared-fact input. Existing generation APIs, task-specific instructions, structured outputs, AI-draft persistence, explicit adoption, governance, audit, and human `final_content` boundaries remain compatible. This phase does not redesign the Phase 9 contract, build frontend experiences, introduce a new reporting-period system, generate SQL, implement semantic impact, or add new fact stores.

### Context Cutover and Failure Boundary

- **D-01 — Sole shared-fact entry:** After Phase 10, `RegulatoryContextBuilder` is the only production entry point for shared Metadata, Knowledge, Evidence, Historical, Lineage, Semantic, and cross-layer Mapping facts used by generators. A generator must not fill Context gaps by issuing its former ORM, `HybridRetriever`, or evidence queries.
- **D-02 — Fail closed on construction failure:** Authorization failure, ContextBuilder exception, invalid scope, or failed Context construction makes the generation request fail with a diagnosable error. Production code must not fall back to the legacy context-building path.
- **D-03 — Incomplete Context is business state:** A successfully built Context with missing facts is not a construction failure. The generator evaluates its typed gaps, conflicts, available facts, and readiness policy to decide whether a conservative draft is allowed.
- **D-04 — Task-local reads remain allowed:** Generators may directly load the mapping or scenario-lineage row currently being operated on and perform task-specific editability/status checks, output application, audit, commit, and refresh. These reads do not authorize reconstructing shared business context outside ContextBuilder.
- **D-05 — Shadow comparison only:** Legacy-vs-Context comparison may exist in tests or a non-authoritative shadow harness during migration. It must never become a production fallback or contribute competing facts to a generated draft.

### Effective Generation Date

- **D-06 — Backward-compatible `as_of`:** Generator services support an optional `as_of`; existing mapping-id-only API calls remain valid. Any API extension is additive and optional.
- **D-07 — Resolution priority:** Resolve the effective business date in this order: explicit `as_of`; an existing task/project regulatory reporting or effective date; an existing project default reporting date if the current model provides one; current business date only as the final fallback.
- **D-08 — Reuse existing time concepts:** Research and planning must first inspect existing project/task/reporting models. Phase 10 must not create a new `ReportingPeriod` persistence system merely to supply generator dates.
- **D-09 — Trace the resolved date:** The final `resolved_as_of` must appear in Context build metadata and generation audit/trace evidence so a later reviewer can explain which temporal semantic version governed the draft.

### Task-Specific Context Projection

- **D-10 — Three adapter families:** Use distinct Source-to-Mart, Mart-to-YBT, and Scenario Context adapters, or equivalent names matching the repository style. Scenario business and technical projections may share scenario infrastructure while retaining their different instructions and outputs.
- **D-11 — Typed deterministic projection:** Each adapter selects only task-relevant Context facts, sorts by authority, retains compact provenance references, compresses long text, includes applicable conflicts/open questions, and enforces deterministic prompt/token bounds.
- **D-12 — No full Context dump:** The complete `RegulatoryContext` remains available for audit and debugging but is not serialized wholesale into the model prompt.
- **D-13 — Preserve task differences:** Existing task-specific prompt runtime keys, instructions, `SourceToMartOutput`, `MartToYbtOutput`, `ScenarioBusinessOutput`, and `ScenarioTechnicalOutput` remain distinct. Phase 10 must not introduce a universal Generator or universal Prompt Adapter.

### Generation Readiness and Blocking

- **D-14 — Deterministic task-aware policy:** Adapters or a closely related generator policy produce a typed readiness result equivalent to `can_generate`, `confidence_cap`, `blocking_reasons`, and `warnings`. This is an internal Phase 10 projection/policy and must not require redesigning the verified Phase 9 `RegulatoryContext` contract.
- **D-15 — Non-blocking gaps:** Missing evidence, insufficient retrieved knowledge, some missing lineage, non-core unknown fields, and the mapping gap that the current generator exists to fill normally allow a conservative draft. They must create or preserve explicit open questions, cap confidence, use “待确认” where needed, and never authorize invented facts.
- **D-16 — Mapping-gap exception:** `MISSING_SOURCE_MAPPING` is not inherently blocking for Source-to-Mart generation, and `MISSING_MART_TO_YBT_MAPPING` is not inherently blocking for Mart-to-YBT generation. The readiness policy evaluates gaps relative to the current task.
- **D-17 — Blocking conditions:** Do not ask the model to adjudicate an unresolved conflict between high-authority confirmed/formal/approved facts when it affects the task's core field or rule. Missing/cross-project target identity, inability to resolve the task target, Context construction failure, and governance prohibition are also blocking. The caller receives diagnosable blocking reasons and no new usable AI draft is persisted.
- **D-18 — Governance remains final:** Generators only produce AI drafts. Existing human final content is never overwritten by generation; promotion remains the explicit adoption/review/governance workflow.
- **D-19 — Question preservation:** Context-derived deterministic questions are authoritative generation constraints. Generator output may add task-specific questions, but it must not erase existing human questions or Context questions; planning should use stable merge/dedup behavior and preserve source traceability as far as existing storage permits.

### Compatibility and Verification

- **D-20 — Existing API contract:** Existing `generate-draft` and `adopt-ai-draft` routes and response schemas remain compatible. Optional date input and diagnostic detail are additive only.
- **D-21 — Migration scope:** Phase 10 removes duplicated shared-context construction from the three generator modules, including natural-order source candidate lookup, independent knowledge retrieval, evidence normalization, historical lookup, and cross-layer summaries where Context already supplies them.
- **D-22 — Regression focus:** Tests must prove no legacy shared-fact fallback, correct temporal version selection, task-aware readiness, deterministic prompt projection, project/institution isolation, confidentiality, provenance/audit traceability, final-content preservation, and unchanged structured-output/API behavior.

### the agent's Discretion

- Exact adapter, projection, readiness, and date-resolver class/module names within the existing mapping-service style.
- Exact prompt character/token budgets and truncation markers, provided ordering, provenance retention, and truncation are deterministic and tested.
- Exact additive API shape for optional `as_of` and exact HTTP status/error schema for blocked generation, provided old calls remain valid, blocking is diagnosable, and no draft is mutated.
- Which existing reporting/effective-date field supplies each fallback tier after code research; absence of such a field must fall through rather than create new persistence.
- Exact audit payload field names for context schema version, context build time, `resolved_as_of`, fact/conflict/question counts, retrieval log ids, and readiness.
- Migration wave order among Source-to-Mart, Mart-to-YBT, and Scenario generators, provided all four task outputs are covered before Phase 10 verification.
- Shape of a test-only shadow comparison harness, if one is useful; it cannot influence production generation.

### Deferred Ideas (OUT OF SCOPE)

- Frontend presentation and semantic catalog/workspace changes remain Phase 11+.
- Full SQL Generator remains a future requirement outside Phase 10.
- Semantic Impact propagation remains Phase 15.
- A new persistent ReportingPeriod system is not introduced in Phase 10; revisit only through a separately scoped requirement if existing date models prove insufficient.
</user_constraints>

**Researched:** 2026-08-23  
**Domain:** Brownfield Python/FastAPI generator migration onto a governed, temporal RegulatoryContext projection  
**Confidence:** HIGH for current-code facts; MEDIUM-HIGH for the proposed decomposition because two projection-completeness gaps must be closed during implementation.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GEN-01 | “Source→Mart Generator 主要消费 RegulatoryContext，同时保留现有 API、structured output 与 task-specific instruction。” | One candidate-mode Context build scoped by `mart_field_id`; a Source-to-Mart adapter; removal of direct candidate/evidence/retrieval queries; unchanged `SourceToMartOutput`, route and response. [VERIFIED: .planning/REQUIREMENTS.md:25-30; backend/app/services/mapping/source_to_mart_generator.py:10-72] |
| GEN-02 | “Mart→YBT Generator 主要消费 RegulatoryContext，同时保留现有 API、structured output 与 Source→Mart 摘要语义。” | One Context build scoped by `target_field_id` + optional `mart_field_id`; adapter selects approved Source-to-Mart `rule_text`; unchanged `MartToYbtOutput`, route and response. [VERIFIED: .planning/REQUIREMENTS.md:25-30; backend/app/services/semantic/context_collectors.py:577-621,683-720] |
| GEN-03 | “Scenario generators 在适用范围消费同一 Context，confirmed/final 内容不会被 AI draft 覆盖。” | Scenario adapter uses `target_field_id` + `scenario_id`; existing scenario editability guard and separate business/technical outputs stay; generation only writes AI draft and task-local fields, never `final_content`. [VERIFIED: .planning/REQUIREMENTS.md:25-30; backend/app/api/scenario_mappings.py:76-114,177-221] |
| GEN-04 | “缺少证据时生成器产生 open question，不凭空创建不存在的表、字段或正式状态。” | Deterministic Context question codes feed readiness and stable merge; technical physical identifiers are accepted only from current row or Context-projected catalog/lineage evidence; confidence is capped by policy. [VERIFIED: .planning/REQUIREMENTS.md:25-30; backend/app/services/semantic/context_conflicts.py:13-22,74-143; backend/app/services/mapping/scenario_draft_generator.py:46-57,94-113] |
</phase_requirements>

## Summary

The refactor should be an in-place cutover, not a generator rewrite. Each generation request must authorize and load exactly one task row, resolve one `as_of`, build one candidate-mode `RegulatoryContext` with the permission-qualified `Project`, pass that Context plus an explicit task-row snapshot through one of three adapters, apply deterministic readiness, and only then call the existing prompt runtime with the existing task-specific structured schema. The current generators instead perform direct ORM/evidence queries and a second direct `HybridRetriever.search`, and Scenario business serializes `model.__dict__` into the prompt. [VERIFIED: backend/app/services/mapping/source_to_mart_generator.py:10-50; backend/app/services/mapping/mart_to_ybt_generator.py:18-64; backend/app/services/mapping/scenario_draft_generator.py:11-18,34-73]

The Phase 9 Contract is sufficient for authority/state/provenance, mappings, lineage, knowledge, historical facts, conflicts, open questions and build trace. It is not yet projection-complete for two current generator needs: a request scoped only by `mart_field_id` validates that row but does not emit a MartField/MartTable metadata descriptor; and Scenario technical safety currently verifies new physical identifiers through a direct `CatalogColumn` query. Close those gaps narrowly inside the existing `metadata` section using `MetadataContextValue` and existing request scopes/evidence; do not add a second DTO, fact store, cache or legacy fallback. [VERIFIED: backend/app/services/semantic/context_collectors.py:128-153,209-215,370-406; backend/app/schemas/regulatory_context.py:167-180,489-505]

No reusable project/task reporting date exists in the current persisted models. `Project` contains identity, confidentiality and governance fields; mapping/scenario rows contain review timestamps and a textual `reporting_condition`, while `TargetField.report_name` and `report_field_name` are labels. The only governed business-date fields are SemanticConceptVersion `effective_from`/`effective_to`, selected by the request's required `as_of`. Therefore Phase 10's date resolver is: explicit optional API/service `as_of`, then no model-backed intermediate tier in the current schema, then injected `date.today()`; record the result as `resolved_as_of` and its source in audit. [VERIFIED: backend/app/models/entities.py:31-48,63-80,193-249,335-394; backend/app/models/semantic.py:42-79; backend/app/schemas/regulatory_context.py:591-613]

**Primary recommendation:** Implement one shared orchestration seam plus three deterministic adapters, enrich the existing Context metadata projection just enough for Mart/catalog descriptors, migrate all direct and background callers, and enforce “one builder call, zero generator-side shared-fact reads, zero fallback.”

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Optional `as_of` and diagnosable block response | API / Backend | — | The four POST `generate-draft` routes are the compatibility boundary; query input is additive and existing ORM response models remain unchanged. [VERIFIED: backend/app/api/mapping_rules.py:72-89,172-189; backend/app/api/scenario_mappings.py:76-114,177-221] |
| Authorization/project/institution handoff | API / Backend | Database / Storage | The resource guard resolves task project and permissions; the canonical builder requires an authorized `Project` and derives `institution_id` from it. [VERIFIED: backend/app/services/auth/resource_guard.py:19-53,78-107; backend/app/services/semantic/context_builder.py:49-58,100-107] |
| Shared fact collection | API / Backend | Database / Storage | `RegulatoryContextBuilder` owns projection; collectors project existing rows and retrieval logs without storing a second truth. [VERIFIED: backend/app/services/semantic/context_builder.py:43-122; backend/app/services/semantic/context_collectors.py:120-365] |
| Task projection/readiness/date/question merge | API / Backend | — | These are deterministic generator policies over typed Context plus the current task row; they should issue zero SQL. [VERIFIED: .planning/phases/10-generator-refactor/10-CONTEXT.md:24-45] |
| Model execution/confidentiality/structured validation | API / Backend | External or local LLM boundary | `prepare_model_input` enforces external-send policy/redaction and `execute_runtime_chat` validates the task schema and logs model calls. [VERIFIED: backend/app/services/llm/prompt_runtime.py:95-119,122-205] |
| Draft/application/audit persistence | API / Backend | Database / Storage | Generator applies validated draft fields and audit metadata in the task transaction; explicit adopt/review is the only final-content transition. [VERIFIED: backend/app/services/mapping/source_to_mart_generator.py:51-72; backend/app/api/mapping_rules.py:80-99,180-199; backend/app/api/scenario_mappings.py:76-114,177-221] |

## Current System Inventory

### Existing Generator APIs and Call Chains

The exact existing route suffixes are `"/source-to-mart-mappings/{mapping_id}/generate-draft"`, `"/mart-to-ybt-mappings/{mapping_id}/generate-draft"`, `"/scenario-business-mappings/{mapping_id}/generate-draft"`, and `"/scenario-technical-lineages/{lineage_id}/generate-draft"`; adoption remains on the corresponding `"/adopt-ai-draft"` routes. [VERIFIED: backend/app/api/mapping_rules.py:72-89,172-189; backend/app/api/scenario_mappings.py:76-96,177-197]

| Family | Current service path | Direct shared-fact work to remove | Task-local work to retain |
|--------|----------------------|-----------------------------------|---------------------------|
| Source→Mart | API → `generate_source_to_mart_draft` → runtime → `SourceToMartOutput` → apply/commit | Direct Mart field/table reads, MappingEvidenceReference query, natural-order SourceField/SourceTable `.limit(50)`, direct HybridRetriever. [VERIFIED: backend/app/services/mapping/source_to_mart_generator.py:10-50,98-120] | Current `SourceToMartMapping` row, structured output application, raw-SQL draft rejection, AI draft write, commit/refresh. [VERIFIED: backend/app/services/mapping/source_to_mart_generator.py:10-13,51-95,131-133] |
| Mart→YBT | API → `generate_mart_to_ybt_draft` → runtime → `MartToYbtOutput` → apply/commit | Direct Target/Mart table/field reads, direct approved/draft Source→Mart summary query, evidence query, direct HybridRetriever. [VERIFIED: backend/app/services/mapping/mart_to_ybt_generator.py:18-64,106-129] | Current `MartToYbtMapping` row, task fields, structured output application, business final-content renderer, commit/refresh. [VERIFIED: backend/app/services/mapping/mart_to_ybt_generator.py:18-21,65-103] |
| Scenario business/technical | API → editability guard → `generate_business_draft` or `generate_technical_draft` → runtime → separate output → apply/audit/commit | Direct TargetField/ProductScenario/peer mappings/evidence/RAG reads; `model.__dict__` prompt dump; direct CatalogColumn physical-source check. [VERIFIED: backend/app/services/mapping/scenario_draft_generator.py:11-18,34-73,94-113] | Current row, scenario review editability, distinct business/technical apply fields, final-content preservation, physical-identifier refusal, audit/commit. [VERIFIED: backend/app/api/scenario_mappings.py:89-114,190-221; backend/app/services/mapping/scenario_draft_generator.py:19-31,46-60] |

The routers are mounted behind the shared `secured` dependency, and the guard maps mapping generation to `"technical.edit"` or `"business.edit"`; the exact permission strings are quoted here because the planner must not invent a new permission. [VERIFIED: backend/app/main.py:137,166,170; backend/app/services/auth/resource_guard.py:78-86]

Two non-obvious callers must be migrated with the service signature: background jobs call Scenario generators from `_draft_handler`, and Deliverable generation calls them from its queued handler. Both are already project-scoped jobs created after PermissionService authorization; they must pass the job/package Project explicitly to the builder path. [VERIFIED: backend/app/api/jobs.py:99-140,167-181; backend/app/api/deliverables.py:395-444]

### Structured Output and Write Boundaries

The task schemas are distinct: `"ScenarioBusinessOutput"`, `"ScenarioTechnicalOutput"`, `"SourceToMartOutput"`, and `"MartToYbtOutput"`. Shared draft fields are `"confidence_level"`, `"open_questions"`, `"citations"`, `"claim_type"`, and `"final_content_draft"`; every task schema validates that task content is present. [VERIFIED: backend/app/services/llm/structured_outputs.py:6-89]

Generation currently never assigns `final_content`; it updates task fields plus `ai_generated_content`. Adoption explicitly copies `ai_generated_content` to `final_content` and resets the lifecycle to draft, while approval/confirmation requires content and evidence. Preserve this separation exactly. [VERIFIED: backend/app/services/mapping/source_to_mart_generator.py:57-72; backend/app/services/mapping/mart_to_ybt_generator.py:71-83; backend/app/services/mapping/scenario_draft_generator.py:19-29,46-58; backend/app/api/mapping_rules.py:80-99,180-199,259-284; backend/app/api/scenario_mappings.py:76-114,177-221]

The current confidence vocabulary used by Context conversion is exactly `{"low": 0.4, "medium": 0.7, "high": 1.0}`; output schemas themselves accept arbitrary strings. The refactor must normalize model output to `"low" | "medium" | "high"` and apply the readiness cap before persistence so the model cannot self-promote. [VERIFIED: backend/app/services/semantic/context_collectors.py:2024-2025; backend/app/services/llm/structured_outputs.py:6-12]

## Standard Stack

### Core

| Library/runtime | Version | Purpose | Why Standard Here |
|-----------------|---------|---------|-------------------|
| Python | 3.12.4 | Service and tests | Current target interpreter. [VERIFIED: environment probe 2026-08-23] |
| FastAPI | 0.139.0 installed; requirement `fastapi>=0.115,<1` | Additive `as_of` query and stable HTTP errors | Existing routers and dependency authorization boundary. [VERIFIED: backend/requirements.txt:1; environment probe 2026-08-23] |
| Pydantic | 2.13.4 installed | Existing Context and structured-output validation; proposed internal projection/readiness models | Current Contract uses strict `extra="forbid"`; outputs already use Pydantic validators. [VERIFIED: backend/app/schemas/regulatory_context.py:14,31-38; backend/app/services/llm/structured_outputs.py:3-12; environment probe 2026-08-23] |
| SQLAlchemy | 2.0.51 installed; requirement `sqlalchemy>=2.0,<3` | Task row, Context collectors, logs/audit | Existing ORM/session boundary. [VERIFIED: backend/requirements.txt:4; environment probe 2026-08-23] |
| pytest | 8.4.2 installed; requirement `pytest>=8,<9` | Unit, API, isolation, query-count and regression tests | Existing backend test framework. [VERIFIED: backend/requirements.txt:23; environment probe 2026-08-23] |

### Supporting Internal Components

| Component | Purpose | Required use |
|-----------|---------|--------------|
| `RegulatoryContextBuilder` | Sole production shared-fact build | Exactly one build per generation; pass explicit authorized Project. [VERIFIED: backend/app/services/semantic/context_builder.py:43-122] |
| `AUTHORITY_RANKS` / `FactState` | Deterministic fact order and lifecycle | Adapter sorting and readiness must consume, not duplicate, the exact values `"formal"`, `"human_confirmed"`, `"regulatory"`, `"semantic"`, `"mapping"`, `"lineage"`, `"metadata"`, `"historical"`, `"retrieved"`, `"inferred"`; states remain independent. [VERIFIED: backend/app/services/semantic/context_authority.py:14-57] |
| `prepare_model_input` / `execute_runtime_chat` | Confidentiality, redaction, runtime selection, structured validation, ModelCallLog | Keep as the only model boundary. [VERIFIED: backend/app/services/llm/prompt_runtime.py:85-119,163-205] |
| `record_audit` / `AuditLog` | Generation attempt and Context trace | Store summaries/IDs/counts only; redaction is already recursive and bounded. [VERIFIED: backend/app/services/governance/audit.py:15-72; backend/app/models/governance.py:182-200] |

**Installation:** none. No external package is needed or recommended; Phase 10 is a code/config refactor over the installed stack. [VERIFIED: .planning/phases/10-generator-refactor/10-CONTEXT.md:7-9,31-36]

## Package Legitimacy Audit

Not applicable: the recommended implementation installs no package and adds no external service. [VERIFIED: Standard Stack and locked phase boundary above]

## Architecture Patterns

### System Architecture Diagram

```text
POST generate-draft (+ optional as_of)
        |
        v
Resource guard + explicit Project authorization
        |
        v
Load exactly one task row ----> governance/editability check ----X blocked (409, audit, no model call)
        |
        v
resolve_generation_as_of(explicit -> no persisted tier today -> injected current date)
        |
        v
RegulatoryContextBuilder.build(candidate mode, authorized Project, task scope)
        |
        +---- construction/scope failure ----X diagnostic failure, no legacy fallback
        |
        v
Task adapter (SourceToMart | MartToYbt | Scenario business/technical)
        |
        v
Readiness policy ---- blocking core conflict/identity/governance ----X 409 + audit, no draft
        |
        v
Deterministic bounded prompt projection + confidentiality levels
        |
        v
prepare_model_input -> execute_runtime_chat(existing prompt key + existing output schema)
        |
        v
confidence cap + stable question merge + task-local output apply
        |
        v
ModelCallLog + AuditLog + task AI draft commit; final_content untouched
```

This flow is derived from the existing API guard, canonical builder, prompt runtime and explicit adopt/review boundary. [VERIFIED: backend/app/services/auth/resource_guard.py:19-53; backend/app/services/semantic/context_builder.py:49-122; backend/app/services/llm/prompt_runtime.py:95-205; backend/app/api/mapping_rules.py:80-99,180-199]

### Recommended Project Structure

```text
backend/app/services/mapping/
├── generator_context.py          # proposed: authorized build orchestration, date resolution, trace summary
├── context_adapters.py           # proposed: three adapter families + deterministic prompt projections
├── generation_readiness.py       # proposed: task-aware blocking/warnings/confidence cap
├── source_to_mart_generator.py   # existing: task row, instruction, output apply only
├── mart_to_ybt_generator.py      # existing: task row, instruction, output apply only
└── scenario_draft_generator.py   # existing: business/technical task operations only

backend/tests/
├── test_generator_context_adapters.py  # proposed Wave 0 unit contract
├── test_double_layer_mapping.py        # existing mapping API regression + migration integration
└── test_scenario_traceability.py       # existing scenario API regression + migration integration
```

The three proposed shared files are recommendations, not existing paths. Existing generator and test paths are verified. [VERIFIED: .planning/phases/10-generator-refactor/10-CONTEXT.md:53-61; backend/app/services/mapping/source_to_mart_generator.py:1-10; backend/tests/test_double_layer_mapping.py:1-13]

### Pattern 1: One Candidate-Mode Context Build Per Task

Use `ContextMode.CANDIDATE`—whose exact wire value is `"candidate"`—because generation needs ranked source/mart candidates and explicit draft/AI suggestions while the Phase 9 policy still excludes rejected/deprecated rows. Trusted mapping facts remain only `"approved"` for both Mapping families and `"confirmed"` for both Scenario families; candidate rows are exactly `"draft"` and `"ai_suggested"`. [VERIFIED: backend/app/schemas/regulatory_context.py:35-38,591-603; backend/app/services/semantic/status_policy.py:19-21; backend/app/services/semantic/context_collectors.py:71-85,551-644]

Proposed skeleton:

```python
# Proposed Phase 10 seam; names are planner discretion.
request = RegulatoryContextRequest(
    project_id=authorized_project.id,
    target_field_id=task.target_field_id if hasattr(task, "target_field_id") else None,
    mart_field_id=task.mart_field_id if hasattr(task, "mart_field_id") else None,
    scenario_id=task.scenario_id if hasattr(task, "scenario_id") else None,
    as_of=resolved_as_of,
    mode=ContextMode.CANDIDATE,
    candidate_limit=50,
)
context = RegulatoryContextBuilder(db).build(request, authorized_project=authorized_project)
```

Every value in the skeleton is either task data or quoted from the existing request contract; `candidate_limit=50` is the existing default. [VERIFIED: backend/app/schemas/regulatory_context.py:591-603]

### Pattern 2: Typed Adapter Projection, Not Context Serialization

Each adapter should accept `(context, task_snapshot)` and return a typed projection containing `prompt_text`, `confidentiality_levels`, `readiness`, `question_constraints`, `trace_summary`, and (Scenario technical only) `allowed_physical_sources`. It must perform zero DB calls. Sort selected facts by descending `AUTHORITY_RANKS`, then stable `fact_type`, `source_type`, `source_id`; sort candidates by their existing `rank_tier`, score and ID. Exclude volatile `built_at` and `retrieval_log_id` from prompt text, but retain them in trace/audit. [VERIFIED: backend/app/services/semantic/context_authority.py:43-57; backend/app/services/semantic/context_collectors.py:63-69,294-301; backend/tests/test_regulatory_context_builder.py:151-185,1548-1583]

Recommended deterministic bounds: default total projection budget 6,000 characters, hard cap 12,000 from runtime config; no more than 30 facts, 20 open questions and 10 conflicts; each selected text excerpt at most 1,000 characters; end truncated sections with a stable marker carrying omitted count. These are implementation recommendations under D-11, not current facts. [ASSUMED]

### Pattern 3: Task-Aware Readiness

Use an internal strict model equivalent to:

```python
class GenerationReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")
    can_generate: bool
    confidence_cap: Literal["low", "medium", "high"]
    blocking_reasons: list[str]
    warnings: list[str]
```

The exact confidence literals reuse the current repository vocabulary quoted above. [VERIFIED: backend/app/services/semantic/context_collectors.py:2024-2025]

Prescriptive policy:

| Signal | Source→Mart | Mart→YBT | Scenario business | Scenario technical |
|--------|-------------|----------|-------------------|--------------------|
| Task/project/institution or requested target mismatch | Block | Block | Block | Block |
| Context construction failure | Fail request; never call adapter/model/fallback | Same | Same | Same |
| `CONFLICTING_AUTHORITATIVE_FACTS` with `severity="error"` in this task-scoped Context | Block | Block | Block | Block |
| Governance/editability prohibition | Block | Block approved/rejected task mutation | Reuse guard; block | Reuse guard; block |
| `MISSING_SOURCE_MAPPING` | Non-blocking task gap; cap low | Non-blocking upstream-summary gap; cap low | Warning if applicable | Warning if applicable |
| `MISSING_MART_TO_YBT_MAPPING` | Ignore as downstream task gap | Non-blocking task gap; cap low | Warning if applicable | Warning if applicable |
| Missing evidence/knowledge/semantic version/binding; missing or stale lineage | Conservative draft; merge question; cap low or medium | Same | Same | Same; never apply new physical identifiers without Context whitelist |
| Complete governed evidence with no blocker | Allow, cap high | Allow, cap high | Allow, cap high | Allow, cap high |

The code strings used above are quoted exactly from the Context conflict catalog: `"MISSING_CONFIRMED_SEMANTIC_BINDING"`, `"MISSING_CONFIRMED_SEMANTIC_VERSION"`, `"MISSING_SOURCE_MAPPING"`, `"MISSING_MART_TO_YBT_MAPPING"`, `"MISSING_LINEAGE"`, `"STALE_LINEAGE"`, `"MISSING_KNOWLEDGE"`, `"MISSING_EVIDENCE"`, `"HISTORICAL_ONLY_DEFINITION"`, `"CONFLICTING_AUTHORITATIVE_FACTS"`. [VERIFIED: backend/app/services/semantic/context_conflicts.py:13-22]

### Pattern 4: Stable Open-Question Merge With Existing Text Storage

The four task rows persist `open_questions` as nullable Text, while Context questions carry code, target, evidence and resolution state. [VERIFIED: backend/app/models/entities.py:193-215,219-246,335-388; backend/app/schemas/regulatory_context.py:431-449]

Do not add a new question table in this phase. Merge in this order: existing task text (human-owned) → sorted Context questions → validated model questions. Split existing text by non-empty lines; normalize Unicode whitespace and case only for dedup keys; preserve first-seen original text. Serialize Context questions as `[CTX:<question_code>:<target_type>:<target_id-or-none>] <question_text>` and model additions as `[AI] <text>`. Repeated generation must be idempotent. Put complete Context question codes and evidence references in AuditLog even when the Text field can only preserve compact tags. This is the recommended storage-compatible solution under D-19. [ASSUMED]

### Pattern 5: Generation Trace Without a New Store

Keep ModelCallLog as the runtime trace: it already stores project, model profile, one retrieval-log FK, prompt key/version, provider/model, request hash, redacted summaries, status, latency, token usage, confidentiality and error type. [VERIFIED: backend/app/models/entities.py:580-581; backend/app/services/llm/prompt_runtime.py:122-205]

Add/standardize an AuditLog for every generator family. Recommended `after_summary_json` keys: `context_schema_version`, `context_built_at`, `resolved_as_of`, `as_of_source`, `context_fact_count`, `context_conflict_codes`, `context_question_codes`, `retrieval_log_ids`, `readiness`, `prompt_projection_hash`, `prompt_projection_truncated`, `output_fields`, `merged_question_sources`, and `final_content_preserved`. Do not store raw Context or prompt text in audit. On success, task draft + ModelCallLog + AuditLog commit together; on readiness block, persist only retrieval/audit diagnostics with `result="blocked"`; on runtime failure, preserve the existing failed ModelCallLog and add a redacted generation audit before re-raising. [VERIFIED: backend/app/services/governance/audit.py:15-72; backend/app/models/governance.py:182-200; backend/app/services/llm/prompt_runtime.py:122-205]

### Anti-Patterns to Avoid

- **Generator imports `HybridRetriever`:** retrieval now belongs only inside Context collectors; a second call duplicates RetrievalLog and can disagree with Context. [VERIFIED: backend/app/services/semantic/context_collectors.py:1112-1243]
- **Direct MappingEvidenceReference or peer-mapping queries in generator modules:** this recreates competing shared facts and bypasses authority/state filtering. [VERIFIED: backend/app/services/semantic/context_collectors.py:551-910]
- **Direct Mart/Target/Source/Catalog descriptor lookup to patch a Context gap:** enrich the existing Context `metadata` section instead; never reintroduce a legacy fallback. [VERIFIED: backend/app/schemas/regulatory_context.py:167-180,489-505]
- **`model.__dict__` in prompts:** it exposes ORM internals and uncontrolled fields; use explicit task snapshot types. [VERIFIED: backend/app/services/mapping/scenario_draft_generator.py:63-73]
- **Whole `RegulatoryContext.model_dump()` in prompts:** the Contract allows up to 1,000 facts and contains volatile/audit-only fields; adapters must select and bound. [VERIFIED: backend/app/schemas/regulatory_context.py:489-533]
- **Letting model confidence bypass readiness cap:** current output schema accepts arbitrary `str`; normalize/cap after validation. [VERIFIED: backend/app/services/llm/structured_outputs.py:6-12]
- **Catching ContextBuilder failure and continuing:** this directly violates D-02 and makes no-fallback tests impossible. [VERIFIED: .planning/phases/10-generator-refactor/10-CONTEXT.md:18-22]

## Required Narrow Context Projection Completion

### Mart Metadata

`_target_scope` project-validates a requested MartField, but `collect_base_context` appends metadata only when a TargetField exists. The existing `MetadataContextValue` already supports entity type/id/code/name/description and bounded attributes. Add MartField plus its MartTable descriptor to the existing `metadata` list when `mart_field_id` is requested; include field/table code/name/type/comment/physical identifiers as bounded attributes. This is a collector completion, not a Contract redesign. [VERIFIED: backend/app/services/semantic/context_collectors.py:128-153,209-215,370-406; backend/app/schemas/regulatory_context.py:167-180]

### Scenario Technical Physical-Source Safety

The current technical generator accepts a new schema/table/field tuple only if an enabled CatalogColumn with the exact project-scoped tuple exists. After cutover, that query cannot remain in the generator. Project relevant CatalogColumn descriptors into existing Context metadata when they are connected by current scenario mapping evidence or scoped lineage; then make the Scenario technical adapter build an exact normalized whitelist. Existing row values remain allowed unchanged. If Context cannot prove a proposed tuple, skip those physical fields, append a deterministic open question, and still allow non-physical processing logic when readiness permits. [VERIFIED: backend/app/services/mapping/scenario_draft_generator.py:46-57,94-113; backend/app/schemas/regulatory_context.py:167-180]

Do not broaden the collector to dump all project catalog columns. That would undermine the current bounded Context/query model and increase prompt injection/exfiltration surface. Select only evidence/lineage-connected IDs in batched queries. [VERIFIED: backend/app/services/semantic/context_builder.py:23-40,125-137; backend/app/services/semantic/context_collectors.py:647-679,913-1017]

## Effective Date Resolution

### Verified Fields

| Model/contract | Exact relevant fields | Planning consequence |
|----------------|-----------------------|----------------------|
| `Project` | `"institution_id"`, `"confidentiality_level"`, `"governance_workflow_enabled"`; no reporting/effective date field | No project default date tier currently exists. [VERIFIED: backend/app/models/entities.py:31-48] |
| `TargetField` | `"report_name"`, `"report_field_name"`; these are string labels | Do not parse them into dates. [VERIFIED: backend/app/models/entities.py:63-80] |
| `MartToYbtMapping` | `"reporting_condition"` is Text; review time is `"reviewed_at"` | Reporting condition is prompt content, not a date source; review timestamp is not business-effective date. [VERIFIED: backend/app/models/entities.py:367-394] |
| Scenario rows | `"business_confirm_at"`, `"tech_confirm_at"` and lineage verification timestamps | Governance/observation timestamps are not reporting dates. [VERIFIED: backend/app/models/entities.py:193-249] |
| Semantic version | `"effective_from"`, `"effective_to"` | These are outputs selected by `as_of`, not fallback inputs for choosing `as_of`. [VERIFIED: backend/app/models/semantic.py:42-79; backend/app/services/semantic/version_service.py:357-417] |
| Context request/scope/build metadata | required `"as_of"`; optional normalized label `"reporting_period"` | Phase 10 must resolve a date before building Context; reporting_period does not infer or persist a date. [VERIFIED: backend/app/schemas/regulatory_context.py:40-68,353-368,452-479,591-613] |

Recommended resolver signature: `resolve_generation_as_of(explicit_as_of: date | None, task: object, project: Project, *, today_provider=date.today) -> ResolvedGenerationDate`. Return both date and source enum. Current source enum should contain only proposed `"explicit"` and `"current_business_date"`; leave a documented extension seam for future real task/project date fields, but do not invent a tier backed by `created_at`, review timestamps or text parsing. Tests must inject `today_provider`. [ASSUMED]

Add `as_of: date | None = Query(default=None)` to each direct POST generation endpoint. Old calls without a query remain valid and response models remain the same. Use HTTP 409 for readiness/governance block with an additive detail object; keep task-not-found 404, authorization 403/hidden 404, invalid date 422, and unhandled builder/runtime faults fail closed. This exact status choice is a recommendation under D-20. [ASSUMED]

## Prompt, Runtime, Confidentiality, and Retrieval-Log Constraints

The exact prompt runtime keys are `"scenario_business_mapping"`, `"scenario_technical_lineage"`, `"source_to_mart_mapping"`, and `"mart_to_ybt_mapping"`; keep them because stored PromptTemplateVersion rows are keyed by `prompt_key`. [VERIFIED: backend/app/services/llm/prompt_runtime.py:17-25,51-82; backend/app/models/entities.py:565-566]

The default system prompt already says not to invent tables/fields or executable SQL and to mark insufficient evidence as pending confirmation. Preserve this task instruction and add a fixed adapter preamble that Context content is quoted data, not instructions. [VERIFIED: backend/app/services/llm/prompt_runtime.py:43-48]

Pass confidentiality levels for every fact actually placed in the prompt, plus Project confidentiality; do not pass only retrieved-knowledge levels as the current generators do. `prepare_model_input` rejects disallowed external sends, audits denial, returns raw input only for local runtime and otherwise redacts. [VERIFIED: backend/app/services/mapping/source_to_mart_generator.py:50; backend/app/services/mapping/mart_to_ybt_generator.py:64; backend/app/services/mapping/scenario_draft_generator.py:18,45; backend/app/services/llm/prompt_runtime.py:95-119]

Context retrieval already creates a RetrievalLog even for zero results and exposes its ID through fact provenance/build metadata. Do not call HybridRetriever again in generators. Pass the sole/current first retrieval log ID to `execute_runtime_chat` for backward-compatible ModelCallLog linkage and preserve the complete sorted list in AuditLog for future multi-log builds. [VERIFIED: backend/app/services/semantic/context_collectors.py:1112-1243; backend/app/services/semantic/context_builder.py:67-97; backend/tests/test_regulatory_context_builder.py:188-214]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Shared fact aggregation | Another generator context dict or ORM query bundle | `RegulatoryContextBuilder` | Already enforces project/institution, temporal versions, authority/state, bounds and provenance. [VERIFIED: backend/app/services/semantic/context_builder.py:43-122] |
| Knowledge retrieval/filtering | Generator-specific RAG call/filter | Context `knowledge_evidence` + provenance | Collector reuses HybridRetriever as sole KnowledgeUnit visibility boundary and records retrieval logs. [VERIFIED: backend/app/services/semantic/context_collectors.py:1112-1243] |
| Authority ranking | Local if/else status weights | `AUTHORITY_RANKS`, `authority_for_source`, `FactState` | Unknown source types fail closed; authority and lifecycle are independent. [VERIFIED: backend/app/services/semantic/context_authority.py:14-57,95-142] |
| Conflict/question discovery | Prompt asks the model to decide gaps | Context conflict/question codes + deterministic readiness | Phase 9 emits stable sorted issues without choosing between contradictions. [VERIFIED: backend/app/services/semantic/context_conflicts.py:25-143] |
| Output parsing | Raw JSON/dict trust | Existing four Pydantic output schemas via `execute_runtime_chat` | Runtime calls `chat_structured` and dumps validated output. [VERIFIED: backend/app/services/llm/prompt_runtime.py:163-189; backend/app/services/llm/structured_outputs.py:15-89] |
| Confidentiality/redaction | Adapter regex/redaction | `prepare_model_input` | Central policy audits denied external sends. [VERIFIED: backend/app/services/llm/prompt_runtime.py:95-119] |
| Audit persistence | New generation trace table | Existing `AuditLog`, `ModelCallLog`, `RetrievalLog` | Existing stores already cover governance summary, model execution and retrieval provenance. [VERIFIED: backend/app/models/governance.py:182-200; backend/app/models/entities.py:559-581] |
| Tokenizer/package | New tokenizer dependency | Deterministic character/fact budgets | No package install is needed; exact prompt bounds can be tested without provider coupling. [ASSUMED] |

## Runtime State Inventory

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | Existing mapping/scenario rows retain draft/final/status/question fields; PromptTemplateVersion and ModelProfile rows retain prompt keys/runtime config; RetrievalLog, ModelCallLog and AuditLog retain historical traces. [VERIFIED: backend/app/models/entities.py:193-249,335-410,559-581; backend/app/models/governance.py:182-200] | No data migration. Preserve table/field names and prompt keys; new generation audit entries are additive. |
| Live service config | Prompt versions/model profiles are DB-resident and selected at runtime by stable prompt key; they are not exported generator config files. [VERIFIED: backend/app/services/llm/prompt_runtime.py:51-82; backend/app/models/entities.py:562-566] | No manual patch if keys remain unchanged. Test seeded/persisted prompt versions still resolve after refactor. |
| OS-registered state | None found: targeted repository search found no service/task registration naming the three generator modules; module references are Python/API/docs only. [VERIFIED: targeted `rg` audit 2026-08-23] | None. Keep module paths stable anyway to preserve imports. |
| Secrets/env vars | No generator-specific environment variable names were found; provider API key selection remains ModelProfile/settings runtime behavior. [VERIFIED: targeted `rg` audit 2026-08-23; backend/app/services/llm/prompt_runtime.py:65-81] | None; do not add generator-specific secrets. |
| Build artifacts / installed packages | No generated/installed artifact references to generator module names were found; this phase adds no package or migration. [VERIFIED: targeted `rg` audit 2026-08-23] | Normal Python process restart/reload only; no reinstall or artifact migration. |

**Canonical runtime-state conclusion:** after source edits, DB prompt/model configuration and historical log rows remain valid because the route names, prompt keys, table schemas and generator module paths are preserved. [VERIFIED: backend/app/services/llm/prompt_runtime.py:17-25; backend/app/api/mapping_rules.py:72-89,172-189; backend/app/api/scenario_mappings.py:76-96,177-197]

## Common Pitfalls

### Pitfall 1: Only Migrating Direct Routes

**What goes wrong:** background batch and Deliverable handlers keep calling the old two-argument Scenario functions, or silently omit authorized Project/as_of/actor trace.  
**How to avoid:** change all six call sites discovered by `rg`; add caller-contract tests for jobs and Deliverables. [VERIFIED: backend/app/api/jobs.py:135-140,167-181; backend/app/api/deliverables.py:407-444; backend/app/api/scenario_mappings.py:89-96,190-197]

### Pitfall 2: Builder Plus Legacy Query

**What goes wrong:** output appears correct but Generator performs a second retrieval/evidence/candidate query, defeating sole-entry semantics and doubling logs.  
**How to avoid:** remove imports and helper functions, assert one builder invocation, exactly one retrieval attempt for a non-empty query, adapter zero SQL, and fail-closed when builder raises. [VERIFIED: backend/app/services/mapping/source_to_mart_generator.py:1-7,17-25,50,98-120; backend/app/services/semantic/context_collectors.py:1112-1243]

### Pitfall 3: Mapping Gap Incorrectly Blocks Its Own Generator

**What goes wrong:** Phase 9 correctly emits missing-mapping questions, but a generic readiness policy blocks the very task intended to fill that gap.  
**How to avoid:** encode task-type exceptions for the exact `MISSING_SOURCE_MAPPING` and `MISSING_MART_TO_YBT_MAPPING` values; test each independently. [VERIFIED: backend/app/services/semantic/context_conflicts.py:92-105; .planning/phases/10-generator-refactor/10-CONTEXT.md:40-43]

### Pitfall 4: Existing Human Questions Disappear

**What goes wrong:** current `_questions_text(output) or mapping.open_questions` replaces non-empty existing questions whenever the model emits anything.  
**How to avoid:** stable three-source merge before assignment, with repeat-generation idempotence tests. [VERIFIED: backend/app/services/mapping/source_to_mart_generator.py:70; backend/app/services/mapping/mart_to_ybt_generator.py:81; backend/app/services/mapping/scenario_draft_generator.py:25,52]

### Pitfall 5: Confidence Cap Is Advisory Only

**What goes wrong:** prompt says low confidence but model returns `high`, and current code persists it verbatim.  
**How to avoid:** normalize and cap after Pydantic validation, before task mutation; audit raw normalized output level and effective persisted cap without raw content. [VERIFIED: backend/app/services/mapping/source_to_mart_generator.py:71; backend/app/services/mapping/mart_to_ybt_generator.py:82; backend/app/services/mapping/scenario_draft_generator.py:26,53]

### Pitfall 6: Physical-Source Hallucination Regression

**What goes wrong:** removing `_physical_value_allowed` allows an LLM to invent schema/table/field values; keeping it violates the sole Context entry.  
**How to avoid:** project evidence/lineage-connected CatalogColumn descriptors through Context metadata and validate exact tuple in the Scenario adapter; otherwise retain current values and add a question. [VERIFIED: backend/app/services/mapping/scenario_draft_generator.py:46-57,94-113]

### Pitfall 7: Confidentiality Checks Only Retrieved Knowledge

**What goes wrong:** a restricted semantic/regulatory/mapping fact enters the prompt but is omitted from the confidentiality level list.  
**How to avoid:** compute levels from every selected fact plus Project; test restricted external denial before model call and local-runtime allowance. [VERIFIED: backend/app/services/llm/prompt_runtime.py:95-119; backend/tests/test_llm_runtime.py:334-354]

### Pitfall 8: Prompt Non-Determinism

**What goes wrong:** `built_at`, fresh retrieval IDs, DB natural order, ORM dict order or uncontrolled truncation changes request hashes across identical facts.  
**How to avoid:** omit volatile values from prompt, retain them in audit, stable sort before cap, and compare exact prompt hashes for repeat builds after normalizing only legitimate volatile metadata. [VERIFIED: backend/tests/test_regulatory_context_builder.py:151-185,1548-1583]

### Pitfall 9: Mutating Governed Rows Before Readiness/Runtime Success

**What goes wrong:** a block or provider failure leaves partial task-field changes.  
**How to avoid:** build/project/readiness/prepare/runtime first; only then apply all output fields; commit once with logs/audit. On exception, ensure no task snapshot change. [VERIFIED: backend/app/services/llm/prompt_runtime.py:175-205; backend/app/services/mapping/source_to_mart_generator.py:50-53]

## Code Examples

### Deterministic Fact Key and Prompt Provenance

```python
# Proposed; AUTHORITY_RANKS is existing policy.
def fact_key(fact: ContextFact) -> tuple[int, str, str, int]:
    return (
        -AUTHORITY_RANKS[fact.authority],
        fact.fact_type,
        fact.source_type,
        fact.source_id or 0,
    )

def provenance_tag(fact: ContextFact) -> str:
    return f"[{fact.authority.value}/{fact.state.value} {fact.source_type}:{fact.source_id or '-'}]"
```

The exact authority values and numeric ranks come from the Phase 9 source of truth. [VERIFIED: backend/app/services/semantic/context_authority.py:14-57]

### Fail-Closed Generation Order

```python
# Proposed orchestration; no legacy branch is allowed.
task = load_task_row(db, task_id)
assert_task_editable(db, task)
resolved = resolve_generation_as_of(as_of, task, authorized_project)
context = build_one_context(db, authorized_project, task, resolved.date)
projection = adapter.project(context, task_snapshot(task))
if not projection.readiness.can_generate:
    audit_blocked_generation(db, task, context, projection, resolved)
    raise GenerationBlockedError(projection.readiness)
model_input = prepare_model_input(
    runtime,
    projection.prompt_text,
    projection.confidentiality_levels,
    db=db,
    project_id=task.project_id,
)
output = await execute_runtime_chat(...)
apply_capped_output_and_merge_questions(task, output, projection)
audit_successful_generation(...)
db.commit()
```

This ordering is recommended from the locked fail-closed and final-content boundaries; it is not current code. [ASSUMED]

## State of the Art in This Repository

| Old approach | Current Phase 9 capability | Phase 10 target | Impact |
|--------------|----------------------------|-----------------|--------|
| Generator-specific ORM/RAG prompt assembly | One versioned, bounded, provenance-carrying Context projection | One Context build + task adapter | Removes competing shared facts and duplicate retrieval. [VERIFIED: backend/app/services/semantic/context_builder.py:43-122] |
| Natural database order `.limit(50)` for source fields | Seven rank tiers, full sort before cap | Adapter consumes candidate facts | Prevents late best candidates from disappearing. [VERIFIED: backend/app/services/mapping/source_to_mart_generator.py:98-110; backend/app/services/semantic/context_collectors.py:63-69,1318-1467] |
| Prompt uses ORM `__dict__` | Strict bounded Contract values | Explicit task snapshot + selected facts | Removes ORM/internal fields from prompt. [VERIFIED: backend/app/services/mapping/scenario_draft_generator.py:63-73; backend/app/schemas/regulatory_context.py:31-32,489-505] |
| Model decides confidence/questions | Deterministic Context conflicts/questions | Readiness cap + stable merge | Missing facts become governed constraints, not prompt suggestions. [VERIFIED: backend/app/services/semantic/context_conflicts.py:25-143] |
| Scenario-only generation AuditLog | Existing shared AuditLog and ModelCallLog | Audit all four families with Context trace | Makes date/provenance/readiness reviewable. [VERIFIED: backend/app/services/mapping/scenario_draft_generator.py:28,57; backend/app/services/governance/audit.py:37-72] |

**Deprecated after Phase 10:** `_source_candidates`, `_source_to_mart_summary`, generator `_evidence_text`, generator direct `HybridRetriever.search`, Scenario `_context` ORM dump, and generator `_physical_value_allowed` direct catalog query. Their responsibilities move to Context collectors/adapters; do not retain them as fallback helpers. [VERIFIED: backend/app/services/mapping/source_to_mart_generator.py:98-133; backend/app/services/mapping/mart_to_ybt_generator.py:106-142; backend/app/services/mapping/scenario_draft_generator.py:63-73,94-113]

## Exact File and Symbol Change Map

| File | Symbols | Required action |
|------|---------|-----------------|
| `backend/app/services/semantic/context_collectors.py` | `collect_base_context`, metadata helpers, evidence/catalog batching | Add MartField/MartTable metadata and scoped catalog-column descriptors using existing `MetadataContextValue`; preserve project filters, stable ordering and 21-query ceiling or justify a new fixed ceiling. [VERIFIED: backend/app/services/semantic/context_collectors.py:120-365,370-406] |
| `backend/app/services/mapping/generator_context.py` | proposed `ResolvedGenerationDate`, `build_generation_context`, trace/question helpers | New shared seam; exactly one builder call; no fallback; no task-independent ORM queries. [ASSUMED] |
| `backend/app/services/mapping/context_adapters.py` | proposed SourceToMart, MartToYbt and Scenario adapters | Explicit zero-SQL projection, authority order, bounded prompt, compact provenance, confidentiality levels, technical whitelist. [ASSUMED] |
| `backend/app/services/mapping/generation_readiness.py` | proposed `GenerationReadiness`, `evaluate_readiness`, confidence cap | Central task-aware policy consuming existing conflict/question codes without changing Contract. [ASSUMED] |
| `backend/app/services/mapping/source_to_mart_generator.py` | `generate_source_to_mart_draft`, `_apply_output`, question/final-content helpers | Retain task row/output application; replace all shared reads with shared seam; add audit; remove `_source_candidates`/`_evidence_text`/RAG. [VERIFIED: backend/app/services/mapping/source_to_mart_generator.py:10-133] |
| `backend/app/services/mapping/mart_to_ybt_generator.py` | `generate_mart_to_ybt_draft`, `_apply_output`, summary/evidence helpers | Consume Context mapping `rule_text` for Source→Mart summary; remove `_source_to_mart_summary`/evidence/RAG; add audit. [VERIFIED: backend/app/services/mapping/mart_to_ybt_generator.py:18-142] |
| `backend/app/services/mapping/scenario_draft_generator.py` | `generate_business_draft`, `generate_technical_draft`, `_context`, `_physical_value_allowed` | Use Scenario adapter; explicit task snapshot; Context whitelist; keep distinct outputs/actions and task-local apply. [VERIFIED: backend/app/services/mapping/scenario_draft_generator.py:11-113] |
| `backend/app/api/mapping_rules.py` | four generate/adopt routes; two generator calls | Add optional query `as_of`, explicit principal→Project handoff and distinct blocked/error mapping; response/adopt routes unchanged. [VERIFIED: backend/app/api/mapping_rules.py:72-89,172-189] |
| `backend/app/api/scenario_mappings.py` | four generate/adopt routes; editability guard | Add optional query `as_of` and authorized Project handoff; preserve `ensure_scenario_mapping_editable`. [VERIFIED: backend/app/api/scenario_mappings.py:76-114,177-221] |
| `backend/app/api/jobs.py` | `_business_handler`, `_technical_handler`, `_draft_handler` | Pass job-scoped Project and actor into generators; no implicit old signature. [VERIFIED: backend/app/api/jobs.py:125-140,167-181] |
| `backend/app/api/deliverables.py` | `_deliverable_generate_handler` | Pass package/job-scoped Project and actor; retain existing skip of governed content. [VERIFIED: backend/app/api/deliverables.py:395-444] |
| `backend/tests/test_generator_context_adapters.py` | proposed unit tests | Wave 0: date priority, readiness matrix, ordering/truncation, confidentiality aggregation, question merge, technical whitelist, zero SQL. [ASSUMED] |
| `backend/tests/test_double_layer_mapping.py` | `test_double_layer_mapping_end_to_end_api` plus focused cases | Preserve route/output/final/adopt behavior; add as_of/temporal/summary/no-fallback/audit/query-growth cases. [VERIFIED: backend/tests/test_double_layer_mapping.py:13-203] |
| `backend/tests/test_scenario_traceability.py` | scenario mapping integration cases | Preserve business/technical/adopt/confirmation; add Context, physical refusal, question merge, governance, jobs/Deliverable callers. [VERIFIED: backend/tests/test_scenario_traceability.py:49-205] |
| `backend/tests/test_regulatory_context_builder.py` | metadata and 21-query tests | Cover narrow metadata enrichment and keep deterministic project/institution/confidentiality/query behavior. [VERIFIED: backend/tests/test_regulatory_context_builder.py:62-64,73-214,1326-1385] |

## Executable Plan Decomposition

### Plan 10-01 — Shared Generator Context Foundation

1. Add RED tests for resolved date, three adapter projections, readiness matrix, question merge, confidence cap and zero-SQL adapter behavior. [ASSUMED]
2. Add narrow Context collector tests for requested MartField/MartTable metadata and evidence/lineage-connected CatalogColumn metadata; assert foreign project/institution descriptors never appear. [ASSUMED]
3. Implement collector enrichment using existing Contract types, then implement `generator_context.py`, `context_adapters.py`, and `generation_readiness.py`. [ASSUMED]
4. Gate: adapter tests + Context builder/API suites; maintain deterministic order and fixed growth query count. [VERIFIED: backend/tests/test_regulatory_context_builder.py:1326-1385; backend/tests/test_regulatory_context_api.py:601-630]

### Plan 10-02 — Double-Layer Mapping Cutover

1. Add RED integration tests for optional `as_of`, authorized Project handoff, one Context build, no direct retrieval/evidence/candidate fallback, temporal version selection, Source→Mart gap exception, Mart→YBT upstream Source→Mart summary, blocked conflict, question preservation, confidence cap, audit and final-content immutability. [ASSUMED]
2. Refactor both mapping generators and API routes; preserve exact runtime keys and response/adopt contracts. [ASSUMED]
3. Remove deprecated helpers/imports and add static/dynamic no-fallback assertions. [ASSUMED]
4. Gate: `python -m pytest -q tests/test_generator_context_adapters.py tests/test_double_layer_mapping.py tests/test_regulatory_context_builder.py -x`. [ASSUMED]

### Plan 10-03 — Scenario Cutover and Background Callers

1. Add RED business/technical tests for same Context, distinct outputs, editability/governance blocks, explicit task snapshots, current physical-value retention, unsupported new tuple refusal/open question, provenance/confidentiality/audit and final-content preservation. [ASSUMED]
2. Refactor Scenario generator; remove direct Target/Scenario/peer/evidence/RAG/catalog shared reads. [ASSUMED]
3. Update direct API, job batch and Deliverable queued callers to pass scoped Project/actor/as_of (none for existing batch calls). [ASSUMED]
4. Gate: `python -m pytest -q tests/test_scenario_traceability.py tests/test_llm_runtime.py tests/test_governance.py -x`. [ASSUMED]

### Plan 10-04 — Cross-Cutting Regression and Qualification

1. Add two-project/two-institution generation isolation and restricted-external denial tests; assert no model call/no task mutation on block. [ASSUMED]
2. Add generator query-growth tests: adapter adds zero SQL; one Context build; row growth does not change total statement count; builder remains at or below the accepted fixed ceiling. [ASSUMED]
3. Run Phase 9 Contract/builder/API regressions, generator/runtime/governance/knowledge tests, compileall, then full backend suite; classify only the two documented Windows baseline failures if signatures remain identical. [VERIFIED: .planning/phases/09-regulatory-context/09-VERIFICATION.md:86-119,128-145]
4. Static scope fence: no frontend, SQL Generator, Semantic Impact or DataQualityExpectation production diff; no package, migration or new fact store. [VERIFIED: .planning/phases/10-generator-refactor/10-CONTEXT.md:7-9]

## Validation Architecture

`.planning/config.json` sets `workflow.nyquist_validation` to `false`, but the task explicitly requires this section, so this research includes a phase validation contract without changing config. [VERIFIED: .planning/config.json:7-13]

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 [VERIFIED: environment probe 2026-08-23] |
| Config file | No pytest config file was found; tests run from `backend/` using existing fixtures. [VERIFIED: targeted file inventory 2026-08-23] |
| Quick run command | `python -m pytest -q tests/test_generator_context_adapters.py tests/test_double_layer_mapping.py tests/test_scenario_traceability.py -x` [ASSUMED] |
| Core integration command | `python -m pytest -q tests/test_regulatory_context_api.py tests/test_regulatory_context_contract.py tests/test_regulatory_context_builder.py tests/test_semantic_layer.py tests/test_double_layer_mapping.py tests/test_scenario_traceability.py tests/test_llm_runtime.py -x` [ASSUMED] |
| Full suite command | `python -m pytest -q` [VERIFIED: .planning/phases/09-regulatory-context/09-VERIFICATION.md:128-145] |

### Phase Requirements → Test Map

| Req ID | Behavior | Test type | Automated command | File exists? |
|--------|----------|-----------|-------------------|--------------|
| GEN-01 | Source→Mart uses only Context shared facts; preserves API/output/instruction/final | unit + API integration | `python -m pytest -q tests/test_generator_context_adapters.py -k source_to_mart tests/test_double_layer_mapping.py -x` | ❌ Wave 0 adapter file; ✅ integration file |
| GEN-02 | Mart→YBT uses Context and preserves approved Source→Mart summary semantics | unit + API integration | `python -m pytest -q tests/test_generator_context_adapters.py -k mart_to_ybt tests/test_double_layer_mapping.py -x` | ❌ Wave 0 adapter file; ✅ integration file |
| GEN-03 | Scenario business/technical share Context; final/confirmed immutable; all callers migrated | unit + API/job integration | `python -m pytest -q tests/test_generator_context_adapters.py -k scenario tests/test_scenario_traceability.py tests/test_governance.py -x` | ❌ Wave 0 adapter file; ✅ existing integration files |
| GEN-04 | Missing evidence produces merged questions; physical facts cannot be invented; block/fallback behavior deterministic | unit + security integration | `python -m pytest -q tests/test_generator_context_adapters.py -k 'readiness or questions or physical' tests/test_semantic_retrieval_security.py -x` | ❌ Wave 0 adapter file; ✅ security file |

### High-Risk Regression Matrix

| Risk | Required assertion |
|------|--------------------|
| Legacy fallback | Builder exception produces diagnostic failure; monkeypatched legacy retriever/query helpers are never reached; no draft mutation. |
| Duplicate retrieval | Exactly one new retrieval attempt/log per non-empty generation Context; generator modules no longer import `HybridRetriever`. |
| Temporal drift | Explicit `as_of` selects the expected inclusive semantic version; omitted date uses injected current date and audits its source. |
| Scope leak | Cross-project task/context IDs return hidden/not-authorized failure; prompt/audit contains no foreign marker; institution comes from Project only. |
| Confidentiality | Restricted selected fact blocks external model before call and audits denial; local runtime accepts it; prompt audit contains no raw secret. |
| Human/final overwrite | Snapshot all task fields before block/failure; `final_content` and confirmed/approved statuses remain byte-for-byte unchanged after generation. |
| Question loss | Existing human + Context + AI questions survive; repeated generation is idempotent; source tags/codes retained. |
| Confidence inflation | Model `high` is persisted as low/medium when readiness caps it. |
| Physical hallucination | Unknown Catalog tuple is skipped and questioned; current tuple or Context-whitelisted tuple is accepted. |
| Call-site breakage | Direct routes, background batch and Deliverable queued generation all call the new signature. |
| Query growth | Same statement count after candidate/knowledge/evidence row growth; adapters execute zero SQL. |

### Sampling Rate

- **Per task commit:** quick run command above. [ASSUMED]
- **Per wave merge:** core integration command above. [ASSUMED]
- **Phase gate:** full backend suite plus `python -m compileall -q app`; compare the two known Windows-only failures by exact test identity/signature rather than hiding them. [VERIFIED: .planning/phases/09-regulatory-context/09-VERIFICATION.md:128-145]

### Wave 0 Gaps

- [ ] `backend/tests/test_generator_context_adapters.py` — adapter/date/readiness/question/confidence/whitelist/zero-SQL contract. [ASSUMED]
- [ ] Context builder tests for Mart metadata and scoped CatalogColumn projection. [ASSUMED]
- [ ] Test helpers to capture prompt input, model-call count and SQL statement count around one generation. [ASSUMED]
- [ ] Job/Deliverable caller regression covering explicit authorized Project handoff. [ASSUMED]

### Current Baseline Executed During Research

- `python -m pytest -q tests/test_double_layer_mapping.py tests/test_scenario_traceability.py` → **4 passed in 5.67s**. [VERIFIED: local pytest run 2026-08-23]
- `python -m pytest -q tests/test_llm_runtime.py` → **22 passed in 3.08s**. [VERIFIED: local pytest run 2026-08-23]
- Phase 9 records builder growth budget `21` and HTTP budget `22`; preserve the row-growth invariant and re-measure any fixed increase caused by narrowly enriched metadata. [VERIFIED: backend/tests/test_regulatory_context_builder.py:62-64,1326-1385; backend/tests/test_regulatory_context_api.py:49-50,601-630]

## Performance and Query Impact

Context construction currently performs one keyword-only HybridRetriever call with `top_k` bounded to 20..100 and ranks candidates before the request cap. Builder applies 500-per-section and 1,000-global fact caps. [VERIFIED: backend/app/services/semantic/context_collectors.py:1122-1147,1318-1467; backend/app/services/semantic/context_builder.py:23-40,125-137]

Absolute generator query count may be higher than the legacy happy path because Context intentionally aggregates more governed domains, but it must remain constant under data growth. Require: one task row load, one authorized Project handoff, one builder call, zero adapter SQL, two existing prompt-runtime selects, bounded log/audit writes and one final refresh. Avoid a brittle guessed total; lock the measured post-implementation count and assert the growth count is identical. [VERIFIED: backend/app/services/llm/prompt_runtime.py:51-82; backend/tests/test_regulatory_context_builder.py:1326-1385]

Collector enrichment must batch Mart table/field and evidence-connected CatalogColumn IDs. If it adds queries, the planner must update the fixed Context budget only with an explicit before/after rationale and retain constant growth. Do not introduce lazy relationships in adapters. [ASSUMED]

## Security Domain

Security enforcement is enabled because `.planning/config.json` does not set it false. [VERIFIED: .planning/config.json:1-18]

### Applicable ASVS Categories

| ASVS category | Applies | Standard control |
|---------------|---------|------------------|
| V2 Authentication | Yes | Existing current-principal dependencies and secured router guard; no new auth mechanism. [VERIFIED: backend/app/main.py:137,166,170; backend/app/services/auth/resource_guard.py:19-53] |
| V3 Session Management | No phase-specific change | Preserve existing auth/session dependencies; Phase 10 adds no session state. [VERIFIED: phase scope] |
| V4 Access Control | Yes | Resource guard plus explicit PermissionService Project object passed into Builder; background callers use previously authorized job/package project scope. [VERIFIED: backend/app/services/auth/resource_guard.py:19-53; backend/app/api/jobs.py:125-140; backend/app/api/deliverables.py:395-411] |
| V5 Input Validation | Yes | FastAPI date/ID validation, strict Context models, existing structured outputs, deterministic adapter whitelist/readiness. [VERIFIED: backend/app/schemas/regulatory_context.py:31-68,591-613; backend/app/services/llm/structured_outputs.py:6-89] |
| V6 Cryptography | No new cryptography | Continue existing provider secret/redaction policy; never hand-roll crypto. [VERIFIED: backend/app/services/llm/prompt_runtime.py:65-81,95-119] |

### Known Threat Patterns

| Pattern | STRIDE | Standard mitigation |
|---------|--------|---------------------|
| Cross-project task/context ID | Spoofing / Information disclosure | Resolve task via resource guard, re-authorize its Project, builder validates request ID and every collector is project scoped. [VERIFIED: backend/app/services/auth/resource_guard.py:89-107; backend/app/services/semantic/context_builder.py:49-58; backend/app/services/semantic/context_collectors.py:370-499] |
| Retrieved/regulatory prompt injection | Tampering | Treat Context strings as quoted data, not instructions; preserve fixed system prompt and task schema; never execute SQL from output. [VERIFIED: backend/app/services/llm/prompt_runtime.py:43-48; backend/app/services/mapping/source_to_mart_generator.py:75-95,131-133] |
| Restricted fact sent externally | Information disclosure | Aggregate all selected confidentiality levels and call `prepare_model_input` before model execution. [VERIFIED: backend/app/services/llm/prompt_runtime.py:95-119] |
| AI promotion of fact/status | Tampering / Elevation | Adapters never write authoritative state; existing adoption/review/evidence gates remain. [VERIFIED: backend/app/api/mapping_rules.py:80-99,259-284; backend/app/api/scenario_mappings.py:99-114,200-221] |
| Missing generation trace | Repudiation | Link ModelCallLog/one retrieval ID and AuditLog/full Context trace; audit blocked/failed/success outcomes. [VERIFIED: backend/app/models/entities.py:559-581; backend/app/models/governance.py:182-200] |
| Context/prompt amplification | Denial of service | Existing fact/candidate caps plus smaller deterministic adapter bounds and fixed-growth query tests. [VERIFIED: backend/app/services/semantic/context_builder.py:23-40,125-137; backend/app/services/semantic/context_collectors.py:294-301] |

## Scope Fence

Phase 10 may change backend generator/context-collector/API/caller/test files listed above. It must not implement frontend routes/components, a SQL Generator, Semantic Impact, DataQualityExpectation, a ReportingPeriod persistence model, a new Context contract/store/cache, external packages/services, or redesign Phase 9 authority/status/effective-date policy. [VERIFIED: .planning/phases/10-generator-refactor/10-CONTEXT.md:7-9,24-36,47-61]

The current worktree contains unrelated user frontend changes; Phase 10 planning/execution must preserve them and keep generator work backend-scoped. [VERIFIED: `git status --short --branch` probe 2026-08-23]

## Alternatives Considered and Rejected

| Rejected approach | Strongest case | Why rejected here |
|-------------------|----------------|-------------------|
| Keep direct ORM reads for descriptor gaps | Minimal diff and preserves old prompt detail | Violates locked sole-entry rule; instead enrich existing Context metadata narrowly. [VERIFIED: .planning/phases/10-generator-refactor/10-CONTEXT.md:18-22] |
| Trusted-mode Context only | Simplest governed input | Source/Mart generation needs explicit ranked candidates; candidate mode still excludes rejected/deprecated and preserves state. [VERIFIED: backend/app/services/semantic/status_policy.py:19-21; backend/app/services/semantic/context_collectors.py:63-85,282-301] |
| Universal Generator/Prompt adapter | Reduces repeated orchestration | Explicitly prohibited; four outputs/instructions and task write boundaries differ materially. [VERIFIED: .planning/phases/10-generator-refactor/10-CONTEXT.md:31-36; backend/app/services/llm/structured_outputs.py:15-89] |
| New persistent GenerationContext/ReportingPeriod | Easier replay/date selection | Adds a second fact/date store outside scope; existing Context metadata + AuditLog provides trace without new truth. [VERIFIED: .planning/phases/10-generator-refactor/10-CONTEXT.md:7-9,24-29; backend/app/services/semantic/context_builder.py:43-44] |
| Whole Context JSON in prompt | Maximum information with least adapter code | Violates no-dump decision, includes volatile/audit fields and can reach 1,000 facts. [VERIFIED: .planning/phases/10-generator-refactor/10-CONTEXT.md:33-36; backend/app/schemas/regulatory_context.py:489-533] |
| Production legacy shadow/fallback | Operational safety during migration | Explicitly forbidden; tests may compare but production output must have one authority path. [VERIFIED: .planning/phases/10-generator-refactor/10-CONTEXT.md:18-22] |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Proposed module/class names and the 6,000/12,000 character budgets are suitable. | Architecture Patterns / File Map | Low: names/budgets are discretion and can be adjusted while retaining deterministic tests. |
| A2 | HTTP 409 with additive detail is the preferred readiness-block response. | Effective Date Resolution | Medium: clients may expect another error shape; verify current frontend/client generic error handling before locking. |
| A3 | Prefixing Text questions with `[CTX:...]` and `[AI]` is acceptable user-visible storage. | Open-Question Merge | Medium: exports/UI may display prefixes; validate desired presentation or keep provenance only in AuditLog. |
| A4 | Context candidate mode should be used for every generator invocation. | Pattern 1 | Medium: it is required for ranked candidates but exposes draft/AI rows; adapter tests must prove lifecycle labels and no promotion. |
| A5 | Evidence/lineage-connected CatalogColumn projection is sufficient for technical physical-source safety. | Projection Completion | High: if current data lacks those links, the adapter will conservatively refuse new physical fields and produce questions, which is safe but may reduce generation usefulness. |

## Open Questions

1. **Question provenance in user-visible Text**
   - What we know: existing storage is a single Text field; Context has structured codes/evidence. [VERIFIED: backend/app/models/entities.py:193-246,335-388; backend/app/schemas/regulatory_context.py:431-449]
   - What's unclear: whether UI/export should show `[CTX:...]` prefixes.
   - Recommendation: keep stable prefixes unless product owners reject them; always retain full provenance in AuditLog. [ASSUMED]

2. **Catalog evidence completeness**
   - What we know: current technical safety accepts any exact enabled project CatalogColumn, while Context does not yet project CatalogColumn metadata. [VERIFIED: backend/app/services/mapping/scenario_draft_generator.py:94-113]
   - What's unclear: how many existing Scenario technical rows have catalog evidence or lineage links.
   - Recommendation: add a read-only fixture/data audit in Plan 10-01; do not weaken fail-closed physical-field behavior if coverage is sparse. [ASSUMED]

3. **Fixed query budget after metadata enrichment**
   - What we know: current builder baseline is 21 and row growth is bounded. [VERIFIED: backend/tests/test_regulatory_context_builder.py:62-64,1326-1385]
   - What's unclear: whether the narrow Mart/catalog batch can reuse existing queries or adds one/two fixed statements.
   - Recommendation: preserve 21 if practical; otherwise document the exact fixed delta and keep growth identical. [ASSUMED]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| Python | Backend/test execution | ✓ | 3.12.4 | — [VERIFIED: environment probe 2026-08-23] |
| pytest | Phase validation | ✓ | 8.4.2 | — [VERIFIED: environment probe 2026-08-23] |
| FastAPI/Pydantic/SQLAlchemy | Runtime and contracts | ✓ | 0.139.0 / 2.13.4 / 2.0.51 | Existing environment [VERIFIED: environment probe 2026-08-23] |
| Live PostgreSQL | No migration in Phase 10; release regression only | ✗ per Phase 9 verification | — | SQLite/local tests plus existing mandatory staging gate. [VERIFIED: .planning/phases/09-regulatory-context/09-VERIFICATION.md:120-145] |
| LLM provider | Structured runtime behavior | ✓ mock in tests | Existing mock | No live provider needed for phase tests. [VERIFIED: backend/app/services/llm/mock.py; backend/tests/test_llm_runtime.py:146-354] |

**Missing dependencies with no fallback:** none for implementation/testing. [VERIFIED: environment probes and no-package design above]

**Missing dependencies with fallback/release gate:** live PostgreSQL remains the existing staging gate; Phase 10 adds no migration and must not claim live PG qualification. [VERIFIED: .planning/phases/09-regulatory-context/09-VERIFICATION.md:120-145]

## Sources

### Primary (HIGH confidence)

- `.planning/phases/10-generator-refactor/10-CONTEXT.md` — locked scope, failure, date, adapter, readiness and compatibility decisions.
- `.planning/REQUIREMENTS.md` and `.planning/ROADMAP.md` — GEN-01..04 and phase success criteria.
- `backend/app/services/mapping/{source_to_mart_generator,mart_to_ybt_generator,scenario_draft_generator}.py` — current generator queries, prompt assembly, outputs and writes.
- `backend/app/schemas/regulatory_context.py`, `backend/app/services/semantic/context_{builder,collectors,authority,conflicts}.py` — verified Phase 9 Contract, projection, policy, gaps, bounds and provenance.
- `backend/app/api/{mapping_rules,scenario_mappings,jobs,deliverables}.py`, `backend/app/services/auth/{resource_guard,permission_service}.py` — direct/background call graph and permission handoff.
- `backend/app/services/llm/{structured_outputs,prompt_runtime}.py`, `backend/app/services/governance/audit.py` — output/runtime/confidentiality/audit boundaries.
- `backend/tests/test_{double_layer_mapping,scenario_traceability,regulatory_context_builder,regulatory_context_api,llm_runtime}.py` — regression and performance contracts.

### Secondary (MEDIUM confidence)

- `.planning/phases/09-regulatory-context/09-VERIFICATION.md`, `09-SECURITY.md`, `09-04-SUMMARY.md` — independent Phase 9 verification, security and release-gate evidence.
- `.planning/codebase/REGULATORY-SEMANTIC-ASSESSMENT.md` — prior architecture inventory cross-checked against current code.

### Tertiary (LOW confidence)

- None. No external web/training claim is used as implementation authority.

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — installed versions and requirements were probed locally.
- Current call graph and storage boundaries: HIGH — source files were opened with line-level evidence and current tests executed.
- Date-field inventory: HIGH — source-of-truth Project, Target, Mapping, Scenario and Semantic model definitions were opened; no project/task reporting date exists.
- Adapter/readiness/file decomposition: MEDIUM-HIGH — constrained by locked decisions and current Contract, with explicit assumptions/open questions.
- Pitfalls/security/performance: HIGH for observed risks; MEDIUM-HIGH for proposed exact bounds/status code.

**Research date:** 2026-08-23  
**Valid until:** 2026-09-22, or immediately stale if Phase 9 Contract/generator APIs change.
