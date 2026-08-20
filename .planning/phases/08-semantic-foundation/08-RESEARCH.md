# Phase 8 Research — Existing-Architecture Grounding

Research is codebase-local because `.planning/config.json` has `workflow.research: false` and the milestone forbids new external infrastructure.

## Reuse Map

- SQLAlchemy 2 mapped-column style and TimestampMixin: `backend/app/models/entities.py`.
- Project/institution authorization: `backend/app/services/auth/permission_service.py`.
- Generic audit trail: `backend/app/services/governance/audit.py` and AuditLog.
- Generic review targets: WorkflowInstance/ReviewTask use `target_type` + `target_id`; no new review engine is needed.
- API registration: routers are imported and explicitly included by `backend/app/main.py`.
- Migration compatibility: revision `202607300014` uses SQLAlchemy types, inspector guards and SQLite/PostgreSQL-aware indexes.
- Tests: in-memory SQLite `Base.metadata.create_all`, TestClient fixtures and explicit project membership patterns.

## Main Risks and Controls

| Risk | Control |
|------|---------|
| Entity type points to another project | Central BindingService target registry and mandatory project check |
| institution_id supplied by client is forged | Derive it from Project; never trust payload |
| AI bypasses human governance | Separate create/source actor type from explicit status transition; forbid AI→confirmed |
| graph cycle/DoS | Depth <= 5, visited set, frontier batching and max node count |
| naming collision with formal semantic index | Keep `semantic.py` business names and leave semantic_index package/migration untouched |
| SQLite/PostgreSQL divergence | Portable constraints/indexes and real Alembic SQLite upgrade/downgrade test |
| accidental API regression | Additive router plus full backend regression suite |

## Recommended Implementation Shape

1. `models/semantic.py`: three normalized tables, constraints and indexes.
2. `schemas/semantic.py`: strict enums/Literal-backed request and response models.
3. `services/semantic/binding_service.py`: entity registry, scope validation, CRUD helpers.
4. `services/semantic/graph_service.py`: bounded queries.
5. `services/semantic/resolver.py`: deterministic candidates only.
6. `api/semantic.py`: project-aware CRUD, status and query endpoints using existing permissions/audit.
7. `202608200015_regulatory_semantic_layer.py`: additive migration and downgrade.
8. `tests/test_semantic_layer.py`: behavioral/security coverage; `test_semantic_migration.py`: migration lifecycle.

