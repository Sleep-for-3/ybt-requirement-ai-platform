# YBT Double Layer Mapping Design

## Goal

Add double-layer business mapping document production to the existing YBT requirement AI platform without rebuilding the project or removing current template, datasource, SQL parsing, natural-language task, and legacy field draft features.

The platform mainline becomes:

1. YBT fixed target fields from the regulatory template.
2. Regulatory mart table and field design.
3. Business system to regulatory mart mapping rules.
4. Regulatory mart to YBT mapping rules.
5. Formal Markdown business requirement document export.

## Scope

This increment adds:

- Business source layer models: `BusinessSystem`, `SourceTable`, `SourceField`.
- Regulatory mart layer models: `MartTable`, `MartField`.
- Double-layer mapping models: `SourceToMartMapping`, `MartToYbtMapping`.
- Mapping-level evidence and versioning: `MappingEvidenceReference`, `MappingVersion`.
- CRUD APIs for the source and mart layers.
- Mapping APIs for create, update, AI draft generation, approve, reject, save version, and evidence binding.
- Markdown export APIs for project, target table, and target field scopes.
- Frontend sections in the existing single workspace for source maintenance, mart maintenance, double-layer mapping, and export preview.

This increment does not add Coze Studio integration, Milvus runtime integration, Word export, complex agent orchestration, or free-form SQL generation.

## Architecture

The backend follows the current repository style: SQLAlchemy entities stay in `backend/app/models/entities.py`, Pydantic schemas stay in `backend/app/schemas/api.py`, routers are added under `backend/app/api`, and domain services are added under `backend/app/services`.

The new mapping services use the existing LLM gateway only. The LLM receives field metadata and evidence summaries, then returns JSON business-rule drafts. The service sanitizes and structures those outputs as business口径 text. It does not connect to any database and does not execute SQL. Existing SQL parsing, datasource safe query, natural-language task, and execution log data are only evidence sources.

The frontend remains a single operational workspace in `frontend/app/page.tsx`. This is intentional for MVP speed and compatibility with the current UI. Suggested future routes such as `/business-systems`, `/mart`, and `/export` can be added later when the product navigation is split.

## Data Flow

1. User uploads a YBT Excel template and applies it to create `TargetTable` and `TargetField`.
2. User maintains business systems, source tables, and source fields.
3. User maintains mart tables and mart fields, marking whether they already exist or are proposed.
4. User creates a `SourceToMartMapping` for a mart field.
5. User creates a `MartToYbtMapping` for a target field, optionally binding it to a mart field.
6. User binds evidence to each mapping. Evidence may reference templates, documents, SQL parse results, natural-language tasks, safe query logs, datasource records, source fields, mart fields, target fields, or manual notes.
7. User generates an AI draft. The result populates structured rule fields and `ai_generated_content`; users edit `final_content`.
8. User saves versions and approves or rejects mappings. Approval saves a version snapshot when final content exists.
9. Export endpoints render Markdown and clearly separate:
   - Business system to regulatory mart mapping.
   - Regulatory mart to YBT mapping.

## Review and Versioning

Both mapping types support statuses: `draft`, `reviewed`, `approved`, and `rejected`.

Approving a mapping sets status to `approved`, records reviewer metadata, and creates a `MappingVersion` snapshot from `final_content` or the AI draft if final content is empty. Explicit save-version also creates an incremented version.

## Evidence

Mapping evidence is polymorphic by `mapping_type` and `mapping_id`. There is no database foreign key to either mapping table, so the API validates mapping existence before creating evidence. This keeps the schema simple and avoids duplicating evidence tables.

Supported evidence types are:

- `template_parse_result`
- `document_chunk`
- `sql_file`
- `sql_parse_result`
- `natural_language_task`
- `sql_execution_log`
- `db_query_result`
- `datasource`
- `source_field`
- `mart_field`
- `target_field`
- `manual_note`

## Export

Markdown export includes:

- Project information.
- YBT target table information.
- Field-level basic information.
- Regulatory mart field design.
- Business system to regulatory mart mapping.
- Regulatory mart to YBT mapping.
- Evidence references.
- Open questions.
- Review status and version information.

Project and table exports are assembled by repeating the field-level section for each in-scope target field.

## Testing

Backend pytest coverage will cover:

- CRUD creation for business systems, source tables, source fields, mart tables, and mart fields.
- Creation and update of both mapping types.
- AI draft generation for both mapping types with Mock LLM.
- Evidence binding to both mapping types.
- Version save and approval or rejection.
- Field, table, and project Markdown export.
- Safety expectations that AI drafts are business-rule descriptions and not raw SQL final deliverables.

Smoke test coverage will exercise the end-to-end Docker-first MVP path from project creation through template apply, source/mart setup, mappings, evidence, AI drafts, approval, and Markdown export.
