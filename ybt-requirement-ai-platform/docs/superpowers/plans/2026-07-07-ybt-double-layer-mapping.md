# YBT Double Layer Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add usable double-layer business mapping document production to the existing YBT requirement AI platform.

**Architecture:** Extend the current FastAPI, SQLAlchemy, Alembic, pytest, and Next.js single-workspace architecture. Keep SQL parsing and safe datasource querying as evidence collectors, while new mapping services produce business-rule text and Markdown documents.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Pydantic, pytest, Next.js 14, React, Tailwind, Docker Compose.

---

## File Structure

- Modify `backend/app/models/entities.py` to add the new source layer, mart layer, mapping, evidence, and version entities.
- Modify `backend/app/schemas/api.py` to add create, update, read, action, evidence, version, and export response schemas.
- Add `backend/app/api/business_systems.py` for business system, source table, and source field APIs.
- Add `backend/app/api/mart.py` for mart table and mart field APIs.
- Add `backend/app/api/mapping_rules.py` for both mapping APIs and review/version actions.
- Add `backend/app/api/mapping_evidence.py` for mapping evidence APIs.
- Add `backend/app/api/mapping_export.py` for Markdown export APIs.
- Add `backend/app/services/mapping/source_to_mart_generator.py` for first-layer AI draft generation.
- Add `backend/app/services/mapping/mart_to_ybt_generator.py` for second-layer AI draft generation.
- Add `backend/app/services/mapping/exporter.py` for Markdown assembly.
- Add `backend/alembic/versions/202607070003_double_layer_mapping.py` for schema migration.
- Add `backend/tests/test_double_layer_mapping.py` for backend behavior.
- Modify `backend/app/main.py` to register new routers.
- Modify `backend/app/services/llm/mock.py` to return mapping-specific JSON when prompted.
- Modify `frontend/lib/api.ts` to add frontend types and HTTP helpers.
- Modify `frontend/app/page.tsx` to add source, mart, mapping, evidence, and export UI sections.
- Modify `scripts/smoke_test.py` to cover the new business path.
- Modify `README.md` and `docs/使用与验收说明.md` to document the latest positioning and usage.

## Tasks

### Task 1: Backend Tests

- [ ] Add pytest helpers that create a project, target table, and target field using SQLAlchemy entities.
- [ ] Add tests for `BusinessSystem`, `SourceTable`, `SourceField`, `MartTable`, and `MartField` creation.
- [ ] Add tests for `SourceToMartMapping` and `MartToYbtMapping` creation, update, approve, reject, and save-version service behavior through FastAPI endpoints.
- [ ] Add tests for `MappingEvidenceReference` binding to both mapping types.
- [ ] Add tests for field, table, and project Markdown exports containing the required Chinese section headings.
- [ ] Add tests for Mock LLM draft generation ensuring final mapping content is business text rather than raw SQL.

### Task 2: Data Model and Migration

- [ ] Add SQLAlchemy models and relationships where useful.
- [ ] Add uniqueness constraint for `BusinessSystem(project_id, system_code)`.
- [ ] Add indexes through foreign-key columns consistent with existing entities.
- [ ] Create an Alembic migration that creates new tables with `checkfirst=True`, matching the existing defensive migration style.

### Task 3: Schemas

- [ ] Add create, update, and read schemas for all source and mart entities.
- [ ] Add mapping create, update, read, review, and version schemas.
- [ ] Add evidence create/read schemas and Markdown export response schema.
- [ ] Keep datasource response schemas redacted by not exposing `encrypted_password`.

### Task 4: Source and Mart APIs

- [ ] Implement CRUD endpoints for business systems, source tables, source fields, mart tables, and mart fields.
- [ ] Validate parent records exist before creating child records.
- [ ] Preserve project_id consistency between parent and child records.

### Task 5: Mapping APIs and Services

- [ ] Implement create/list/get/update/delete for both mapping types.
- [ ] Implement draft generation actions through `source_to_mart_generator.py` and `mart_to_ybt_generator.py`.
- [ ] Implement approve/reject and save-version actions.
- [ ] Ensure approval saves a version snapshot.

### Task 6: Evidence and Export

- [ ] Implement mapping evidence create/list/delete endpoints with mapping existence validation.
- [ ] Implement Markdown exporter for project, target table, and target field scopes.
- [ ] Include evidence, open questions, review status, and version information in exports.

### Task 7: Frontend

- [ ] Add source layer forms and lists to the existing workspace.
- [ ] Add mart layer forms and lists.
- [ ] Add double-layer mapping editor sections with AI draft, save version, approve, reject, and manual evidence note controls.
- [ ] Add export preview and Markdown download controls.
- [ ] Keep existing template, datasource, natural-language task, SQL parsing, and legacy field draft controls working.

### Task 8: Smoke Test and Documentation

- [ ] Update smoke test to run the new end-to-end path.
- [ ] Update README with latest product positioning, API usage, and limitations.
- [ ] Update usage and acceptance docs with Docker-first startup and verification commands.

### Task 9: Verification

- [ ] Run `python -m pytest -q`.
- [ ] Run `python -m compileall -q app` inside `backend`.
- [ ] Run `python -m alembic upgrade head` inside `backend`.
- [ ] Run `npm run build` inside `frontend`.
- [ ] Start Docker Compose with `docker compose up --build -d`.
- [ ] Run `python scripts/smoke_test.py` against `http://127.0.0.1:8000/api`.
- [ ] Confirm frontend is available at `http://localhost:3000`.

## Self Review

This plan covers the requested models, APIs, AI draft services, evidence, versioning, Markdown export, frontend MVP controls, smoke test, and documentation. It keeps existing functionality intact and keeps SQL/database features as auxiliary evidence instead of the primary deliverable.
