from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    admin,
    ai_runtime,
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
from app.core.database import engine
from app.core.settings import get_settings
from app.core.observability import RequestContextMiddleware, build_log_event
from app.services.auth.resource_guard import guard_project_resource
from app.services.llm.base import LLMRuntimeError
from app.services.storage import get_storage_service
from app.services.task_queue import get_task_queue

settings = get_settings()
logger = logging.getLogger("app.lifecycle")


@asynccontextmanager
async def lifespan(_: FastAPI):
    runtime_settings = get_settings()
    issues = runtime_settings.validate_configuration()
    for issue in issues:
        level = logging.ERROR if issue["severity"] == "error" else logging.WARNING if issue["severity"] == "warning" else logging.INFO
        logger.log(level, json.dumps(build_log_event("configuration_validation", level=issue["severity"].upper(), code=issue["code"], message=issue["message"]), ensure_ascii=False))
    errors = [issue for issue in issues if issue["severity"] == "error"]
    if errors:
        raise RuntimeError("Invalid application configuration: " + ", ".join(issue["code"] for issue in errors))
    if runtime_settings.storage_provider == "local":
        Path(runtime_settings.storage_dir).mkdir(parents=True, exist_ok=True)
    storage = get_storage_service()
    queue = get_task_queue()
    try:
        yield
    finally:
        storage_client = getattr(storage, "client", None)
        if storage_client is not None and callable(getattr(storage_client, "close", None)):
            storage_client.close()
        celery_app = getattr(queue, "celery_app", None)
        if celery_app is not None and callable(getattr(celery_app, "close", None)):
            celery_app.close()
        get_storage_service.cache_clear()
        get_task_queue.cache_clear()
        engine.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(RequestContextMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(LLMRuntimeError)
async def llm_runtime_error_handler(_, exc: LLMRuntimeError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": str(exc), "error_type": exc.error_type},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_, exc: RequestValidationError) -> JSONResponse:
    safe_errors = [
        {key: value for key, value in error.items() if key not in {"input", "ctx"}}
        for error in exc.errors()
    ]
    config_payload_rejected = any("config_json" in error.get("loc", ()) for error in exc.errors())
    if config_payload_rejected:
        return JSONResponse(
            status_code=400,
            content={"detail": "Model profile config must not contain credentials or unsupported fields"},
        )
    return JSONResponse(status_code=422, content={"detail": safe_errors})


@app.get(f"{settings.api_prefix}/health")
def legacy_health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


secured = [Depends(guard_project_resource)]

app.include_router(projects.router, prefix=settings.api_prefix)
app.include_router(project_readiness.router, prefix=settings.api_prefix)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(admin.router, prefix=settings.api_prefix)
app.include_router(ai_runtime.router, prefix=settings.api_prefix)
app.include_router(governance.router, prefix=settings.api_prefix)
app.include_router(review_tasks.router, prefix=settings.api_prefix)
app.include_router(notifications.router, prefix=settings.api_prefix)
app.include_router(jobs.router, prefix=settings.api_prefix)
app.include_router(storage_files.router, prefix=settings.api_prefix)
app.include_router(audit.router, prefix=settings.api_prefix)
app.include_router(dashboard.router, prefix=settings.api_prefix)
app.include_router(health.router)
app.include_router(health.router, prefix=settings.api_prefix, include_in_schema=False)
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
