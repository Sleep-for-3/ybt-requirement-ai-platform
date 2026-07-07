# 一表通模板数据源自然语言任务 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Excel template import/apply, named SQL data sources, safe natural-language query tasks, and evidence-aware mapping generation to the existing MVP without removing current behavior.

**Architecture:** Extend current FastAPI modules with focused services for template parsing, data source management, safe SQL execution, and rule-based task parsing. Keep the frontend as a simple operational workspace, adding compact sections rather than complex field-detail forms.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, openpyxl, cryptography, sqlglot, SQLite/PostgreSQL via SQLAlchemy, pytest, Next.js, React, TypeScript, Tailwind CSS.

---

### Task 1: Tests First For Core Services

**Files:**
- Create: `ybt-requirement-ai-platform/backend/tests/test_template_parser.py`
- Create: `ybt-requirement-ai-platform/backend/tests/test_template_apply.py`
- Create: `ybt-requirement-ai-platform/backend/tests/test_datasources.py`
- Create: `ybt-requirement-ai-platform/backend/tests/test_safe_sql_executor_v2.py`
- Create: `ybt-requirement-ai-platform/backend/tests/test_natural_language_tasks.py`

- [x] Write tests covering Excel parsing, template apply, data source naming/password redaction, safe SQL rejection/limit/sensitive-column removal, NL task parsing, execution logs, and evidence type constants.
- [x] Run tests and confirm they fail because production modules/models do not exist yet.

### Task 2: Backend Models, Schemas, Settings, Migration

**Files:**
- Modify: `backend/app/models/entities.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/schemas/api.py`
- Modify: `backend/app/core/settings.py`
- Create: `backend/app/core/crypto.py`
- Create: `backend/alembic/versions/202607070002_template_datasource_nl_task.py`
- Modify: `backend/requirements.txt`
- Modify: `backend/.env.example`

- [ ] Add TemplateDocument, TemplateParseResult, DataSource, SqlExecutionLog, NaturalLanguageTask.
- [ ] Add Pydantic request/response schemas with password redaction.
- [ ] Add APP_SECRET_KEY and Safe SQL settings.
- [ ] Add migration for new tables and new draft summary columns.

### Task 3: Backend Services

**Files:**
- Create: `backend/app/services/template_parser/excel_parser.py`
- Create: `backend/app/services/template_service.py`
- Create: `backend/app/services/datasource_service.py`
- Create: `backend/app/services/db/safe_sql_executor.py`
- Modify: `backend/app/services/db_probe/safe_sql_executor.py`
- Create: `backend/app/services/task_parser/natural_language_task_parser.py`
- Create: `backend/app/services/natural_language_task_service.py`
- Modify: `backend/app/services/mapping_generator.py`

- [ ] Implement Excel parsing and apply.
- [ ] Implement data source validation, encrypted password storage, connection testing.
- [ ] Implement safe SQL validation/execution/logging and sensitive field filtering.
- [ ] Implement NL task parse/run with fixed SQL templates.
- [ ] Enhance mapping generation with template/NL/log evidence.

### Task 4: Backend API Routes

**Files:**
- Create: `backend/app/api/templates.py`
- Create: `backend/app/api/datasources.py`
- Create: `backend/app/api/nl_tasks.py`
- Modify: `backend/app/api/target_fields.py`
- Modify: `backend/app/main.py`

- [ ] Add template upload/list/detail/parse-results/apply APIs.
- [ ] Add data source CRUD/test/safe-query APIs.
- [ ] Add NL task create/list/detail/run APIs.
- [ ] Update generate-mapping request body.

### Task 5: Frontend Incremental UI

**Files:**
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/app/page.tsx`

- [ ] Add types and API calls for templates, data sources, and NL tasks.
- [ ] Add template upload/apply section.
- [ ] Add data source management section.
- [ ] Add natural language task section.
- [ ] Keep field analysis page simple and avoid query controls inside field details.

### Task 6: Smoke Test And Docs

**Files:**
- Modify: `scripts/smoke_test.py`
- Modify: `README.md`
- Modify: `docs/使用与验收说明.md`

- [ ] Update smoke test to create Excel template, SQLite data source, test table/data, NL task, safe execution, logs/evidence, and mapping generation.
- [ ] Update README and usage docs with Excel columns, data source naming, SafeSqlExecutor limits, and model/SQL safety rationale.
- [ ] Run backend tests, frontend build, smoke test, and app import checks.
