from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    admin,
    auth,
    governance,
    notifications,
    jobs,
    storage_files,
    audit,
    dashboard,
    health,
    review_tasks,
    business_systems,
    coze,
    datasources,
    db_profile,
    documents,
    mapping_evidence,
    mapping_export,
    mapping_rules,
    mart,
    knowledge_items,
    knowledge_rag,
    catalog,
    metadata_sync,
    metadata_imports,
    profiling,
    nl_tasks,
    projects,
    project_readiness,
    retrieval,
    scenarios,
    scenario_mappings,
    source_recommendations,
    sql_files,
    target_fields,
    target_tables,
    templates,
    traceability_templates,
    traceability_export,
    lineage,
    deliverables,
    uat,
)
from app.core.settings import get_settings
from app.core.observability import RequestContextMiddleware
from app.services.auth.resource_guard import guard_project_resource

settings = get_settings()

app = FastAPI(title=settings.app_name)
settings.validate_production_security()
app.add_middleware(RequestContextMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def ensure_storage_dir() -> None:
    Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)


@app.get(f"{settings.api_prefix}/health")
def legacy_health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


secured = [Depends(guard_project_resource)]

app.include_router(projects.router, prefix=settings.api_prefix)
app.include_router(project_readiness.router, prefix=settings.api_prefix)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(admin.router, prefix=settings.api_prefix)
app.include_router(governance.router, prefix=settings.api_prefix)
app.include_router(review_tasks.router, prefix=settings.api_prefix)
app.include_router(notifications.router, prefix=settings.api_prefix)
app.include_router(jobs.router, prefix=settings.api_prefix)
app.include_router(storage_files.router, prefix=settings.api_prefix)
app.include_router(audit.router, prefix=settings.api_prefix)
app.include_router(dashboard.router, prefix=settings.api_prefix)
app.include_router(health.router, prefix=settings.api_prefix)
app.include_router(templates.projects_router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(target_tables.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(target_fields.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(documents.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(sql_files.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(retrieval.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(coze.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(db_profile.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(templates.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(datasources.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(nl_tasks.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(business_systems.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(mart.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(mapping_rules.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(mapping_evidence.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(mapping_export.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(scenarios.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(scenario_mappings.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(knowledge_items.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(knowledge_rag.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(traceability_templates.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(traceability_export.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(source_recommendations.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(metadata_sync.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(catalog.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(metadata_imports.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(profiling.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(lineage.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(deliverables.router, prefix=settings.api_prefix)
app.include_router(uat.router, prefix=settings.api_prefix)
