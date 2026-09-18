# Resources / Data Backend Handoff

## Baseline
- Initial `git status --short` showed 31 modified tracked files and many untracked files.
- Existing changes span requirements, lineage, authorization, model runtime, frontend and documentation.
- No root AGENTS.md was present; supplied task instructions were used.
- No commit, push, migration, deployment, browser, frontend build or production operation was performed.
- Existing resource_guard.py requirements permission changes were preserved; only the preview/content guard exception is new.

## A1 / A2 / A3 Status
- A1 implemented: optional regulatory/data_field modes on the existing ask route; omitted mode preserves legacy retrieval and response keys, with additive answer_mode=null and sections=null.
- Knowledge type allowlists are intersected with nonempty caller filters. An empty intersection uses a nonmatching sentinel, never an unrestricted retrieval.
- Regulatory sections remain null, as permitted; conclusion/scope/evidence-summary extraction is not implemented.
- Document citations now carry type, label, server-owned relative href, locator and old top-level location fields.
- A2 implemented conservatively: bounded, read-only field evidence service, deterministic sections, extractive model claims, citation membership and evidence containment checks, degraded responses.
- Data-field output is evidence extraction, not unrestricted synthesized prose. No user SQL or business-row query is executed.
- A3 implemented: authenticated preview/content, version ownership checks, safe metadata and file headers, stable fallback locators, parser locator enrichment.
- No PDF Range support: content responds with the full file. No OCR or document conversion service.
- Verification is minimal; no claim of completed authorization or field-answer acceptance testing.

## Changed Files
- backend/app/api/knowledge_rag.py
- backend/app/services/auth/resource_guard.py (additive change to an already modified file)
- backend/app/services/knowledge_evidence.py (new)
- backend/app/services/rag/data_field_answer_service.py (new)
- backend/app/services/rag/document_preview_service.py (new)
- backend/app/services/rag/grounded_answer_service.py
- backend/app/services/retrieval/hybrid_retriever.py
- backend/app/services/knowledge_ingestion/parsers.py
- docs/handoff/resources-data-astra-handoff.md (new)

## Request / Response Contract
Paths below are router-relative; existing application API prefix still applies.

```json
{"query":"CERT_TYPE 来源与码值规则","answer_mode":"data_field","target_field_id":12,"scenario_id":3,"knowledge_types":["data_dictionary","sql_evidence"],"top_k":8,"retrieval_mode":"keyword_only"}
```

Target/scenario IDs above are illustrative: use existing IDs from the authorized project.
Legacy clients omit answer_mode. Explicit regulatory mode accepts only regulatory_policy,
regulatory_qa, business_research, manual_note, historical_mapping.
Explicit data_field mode accepts field_explanation, data_dictionary, code_mapping,
technical_research, historical_traceability, sql_evidence, east_mapping.

```json
{
  "answer":"现有证据不足，结论待确认。",
  "confidence_level":"low",
  "citations":[],
  "supported_claims":[],
  "unsupported_claims":[],
  "open_questions":["缺少真实来源字段证据。"],
  "retrieval_log_id":null,
  "answer_status":"needs_confirmation",
  "answer_mode":"data_field",
  "sections":{
    "target_field":null,
    "source_paths":[],
    "join_conditions":[],
    "transformations":[],
    "code_mappings":[],
    "gaps":["缺少真实来源字段证据。"]
  }
}
```

Illustrative citation shape (IDs are not fixture data):
```json
{
  "citation_id":"knowledge-unit-42",
  "citation_type":"knowledge_document",
  "source_type":"data_dictionary",
  "project_id":1,
  "label":"字段定义",
  "quoted_content":"证件类型字段定义",
  "href":"/knowledge/documents/7/preview?project_id=1&version_id=9",
  "document_id":7,
  "document_version_id":9,
  "knowledge_unit_id":42,
  "source_page_no":2,
  "source_sheet_name":null,
  "source_cell_range":null,
  "locator":{"block_id":"knowledge-unit-42","page_no":2,"text_quote":"证件类型字段定义"}
}
```

- Other citation types: catalog_column, lineage_edge, mapping.
- SourceField evidence uses citation_type=mapping, source_type=source_field and real source_field_id/source_table_id; it does not fabricate mapping_id. Consumers must discriminate source_type.
- Persisted mappings carry mapping_type and mapping_id; IDs alone are not globally unique across mapping tables.
- source_paths uses source_system/database/schema/table/field/status/citation_ids plus available entity IDs.
- Rule sections contain rule_type/text/status/citation_ids. Optional sections.scenario contains real scenario context.
- No client-provided or document-provided URL is accepted as a citation href.

## Evidence Selection
1. Validate and load target/scenario context.
2. Resolve explicit mapping evidence associations, then catalog exact names/IDs before existing search_catalog text-ranked results; keep 8 catalog columns.
3. Source fields: explicit IDs, exact codes/physical names, then field-name substring matches; keep 8.
4. Persisted scenario technical mappings (6), Mart-to-YBT (6), and their explicitly related Source-to-Mart mappings (6).
5. Select up to 30 associated lineage nodes and 10 enabled persisted edges; verify both endpoint projects.
6. Retrieve at most 8 technical knowledge units through HybridRetriever using existing visibility rules.
- Deduplicate citation IDs. Mapping relation lookups happen early for ranking, but evidence presentation follows the source order above.
- Catalog service may inspect up to its existing 5000-row search limit; only bounded results enter the prompt.
- Each structured citation quote is capped at 4000 characters; document quotes at 1500.
- Similar names remain candidates, not lineage. Missing identifiers are not inferred. Draft/unresolved statuses produce gaps.
- Model claims must use an input citation ID and verbatim text from that citation; qualified identifiers are checked against its quote.
- Rejected claims are hidden and flagged. Model errors retain deterministic sections and evidence with degraded status.
- Retrieval errors are reported as gaps; retrieval_log_id can be null. No-evidence returns needs_confirmation.

## Authorization / Versions / Preview
- Ask explicitly requires knowledge.search; explicit modes validate target and scenario project ownership.
- Catalog/source/mapping/lineage queries are project-scoped, including joined source tables/systems and lineage endpoints.
- Preview/content explicitly require knowledge.search on the requesting project; global nonrestricted and same-bank institution nonrestricted documents may be shared.
- Restricted documents are not shared across projects. Archived documents are unavailable.
- Preview/content authorization, missing document, mismatched version and storage failures return generic 404 without paths or internal errors.
- Shared guard skips only GET knowledge document preview/content so endpoint-owned shared-document visibility can run; authentication dependency remains.
- Version must belong to the document and its owning project; omitted version selects current_version_no. Historical units may be disabled but remain previewable.
- Preview is built from ordered version units, capped at 2000 blocks with truncated warning. No pagination yet.
- Document warnings are generic rather than raw parser messages. Old-version warnings are not borrowed from the current version.
- Original bytes use the persisted version storage key. MIME is allowlisted; Markdown/SQL are text/plain.
- Headers: inline Content-Disposition with UTF-8 filename*, no-store, nosniff, sandbox CSP.
- XLSX locator: sheet/cells/row; DOCX: ordered paragraphs/tables/rows/headings; PDF: page only; normalized text and SQL: paragraph/line/character ranges.
- Historical units derive stable knowledge-unit IDs and available legacy positions without rewriting old indexes.

## Actual Checks
- Python py_compile passed for all 8 changed/new Python modules, including API and resource guard.
- One existing test ran: tests/test_knowledge_rag.py::test_knowledge_upload_returns_accepted_background_job_for_async_queue.
- Result: 1 passed, 1 existing Starlette/httpx deprecation warning, 7.71 seconds.
- First invocation from the parent directory failed collection with ModuleNotFoundError: app; rerunning from backend resolved it.
- Test configuration selected mock model/embedding/vector providers. No real model call was made.
- No complete field evidence, preview authorization or parser regression suite was executed, per task scope.

## Explicit Next Tasks
- Implement frontend explicit mode selector and typed section/citation rendering; keep omitted-mode clients compatible.
- Fetch content through Authorization-bearing fetch, create/revoke Blob URLs, and never embed protected URLs anonymously.
- Resolve document citations by version and block_id, including legacy page/Sheet/cell fallback; treat text as untrusted plain text.
- Add focused mock-backed tests for both mode allowlists, empty intersections, foreign target/scenario IDs, catalog/source/edge project isolation, invented identifiers/citations and provider failures.
- Add authenticated preview/content tests for missing/foreign versions, shared/restricted documents, archived files, storage failures and response headers.
- Add all-six-format parser locator tests and an old disabled-version preview fixture.
- Decide whether source_field merits a fifth citation type; current four-type compatibility uses mapping plus source_type=source_field.
- Validate model adapter behavior with DataFieldOutput.claims using mocks; do not assume existing regulatory mock emits this schema.
- Add preview pagination or block_id selection before relying on clickable citations for documents exceeding 2000 units.
- If PDF viewers require seeking, implement and test complete single-range semantics (206/416); current implementation intentionally does not support Range.
- Review stricter regulatory claim validation separately: this phase retains existing grounded-answer behavior and returns sections=null.
