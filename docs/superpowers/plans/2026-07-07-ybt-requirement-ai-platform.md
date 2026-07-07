# 银行一表通字段级口径智能辅助平台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable Docker-first MVP monorepo for field-level 一表通 requirement drafting with RAG, SQL parsing, evidence references, and review flow.

**Architecture:** FastAPI owns persistence and AI orchestration; Next.js owns the operator workflow. PostgreSQL stores all business artifacts, MockVectorStore provides MVP semantic retrieval, and all LLM calls go through an abstract gateway.

**Tech Stack:** Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL, sqlglot, pytest, Next.js, React, TypeScript, Tailwind CSS, Docker Compose.

---

### Task 1: Backend Test Skeleton

**Files:**
- Create: `ybt-requirement-ai-platform/backend/tests/test_text_processing.py`
- Create: `ybt-requirement-ai-platform/backend/tests/test_sql_parser.py`
- Create: `ybt-requirement-ai-platform/backend/tests/test_safe_sql_executor.py`
- Create: `ybt-requirement-ai-platform/backend/tests/test_llm_gateway.py`

- [x] Add tests for deterministic chunking, SQL parser extraction, safe SQL validation, and mock LLM output.
- [x] Run pytest before implementation and confirm these tests fail because production modules do not exist yet.

### Task 2: Backend Core

**Files:**
- Create: backend app package, settings, database session, SQLAlchemy models, Pydantic schemas, repositories, and routers under `ybt-requirement-ai-platform/backend/app/`.
- Create: `requirements.txt`, `Dockerfile`, `.env.example`, `alembic.ini`, `alembic/env.py`, and initial migration.

- [ ] Implement database models for users, projects, target tables/fields, documents/chunks, SQL parse results, field analysis tasks, drafts, evidence references, and DB profile tasks.
- [ ] Implement routers for projects, target tables, target fields, documents, SQL files, retrieval, mapping generation, review, Coze health, and DB profile placeholder.
- [ ] Run focused backend tests.

### Task 3: AI, RAG, SQL, And Safety Services

**Files:**
- Create: `app/services/llm/*`
- Create: `app/services/vector/*`
- Create: `app/services/retrieval.py`
- Create: `app/services/sql_parser.py`
- Create: `app/services/mapping_generator.py`
- Create: `app/services/coze/connector.py`
- Create: `app/services/db_probe/safe_sql_executor.py`

- [ ] Implement OpenAI-compatible gateway, mock fallback, embedding helper, and provider factory.
- [ ] Implement VectorStore abstraction, MockVectorStore, and Milvus placeholder with Knowhere comment.
- [ ] Implement text chunking, document ingestion, retrieval fusion, SQL parsing, mapping generation, Coze connector, and safe SQL validation.
- [ ] Run backend tests.

### Task 4: Frontend MVP

**Files:**
- Create: `frontend/app/*`
- Create: `frontend/components/*`
- Create: `frontend/lib/api.ts`
- Create: `package.json`, `Dockerfile`, Tailwind and TypeScript config.

- [ ] Implement a single operational workspace with project/table/field creation, uploads, SQL parse display, field analysis, evidence chain display, and review actions.
- [ ] Run frontend build.

### Task 5: Docker And Docs

**Files:**
- Create: `docker-compose.yml`
- Create: `README.md`
- Create: root `.gitignore`

- [ ] Compose PostgreSQL, backend, and frontend for local development.
- [ ] Document local startup, env vars, workflow, model switching, Coze reservation, Milvus/Knowhere relationship, and roadmap.
- [ ] Run final backend tests and frontend build.
- [ ] Commit the completed MVP skeleton.
