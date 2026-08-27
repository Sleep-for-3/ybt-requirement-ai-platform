from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (
    admin,
    ai_runtime,
    auth,
    governance,
    global_search,
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
    quality,
    project_readiness,
    retrieval,
    regulatory_context,
    requirement_workspace,
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
    semantic,
    semantic_catalog,
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


def _error_contract(request: Request, status_code: int, detail, *, error_code: str | None = None, technical_message: str | None = None) -> dict:
    code = error_code or {
        400: "invalid_request", 401: "authentication_required", 403: "permission_denied",
        404: "resource_not_found", 409: "state_conflict", 422: "validation_failed",
        429: "rate_limited", 503: "dependency_unavailable",
    }.get(status_code, "internal_error")
    user_message = detail if isinstance(detail, str) and status_code < 500 else {
        400: "请求内容不正确", 401: "登录状态已失效", 403: "没有操作权限",
        404: "资源不存在或不可见", 409: "资源状态冲突", 422: "输入数据不完整或格式不正确",
        429: "请求过于频繁，请稍后重试", 503: "依赖服务暂不可用",
    }.get(status_code, "服务器处理失败")
    return {
        "detail": detail,
        "error_code": code,
        "user_message": user_message,
        "technical_message": technical_message,
        "trace_id": getattr(request.state, "request_id", None),
        "retryable": status_code in {429, 503},
        "suggested_actions": ["稍后重试"] if status_code in {429, 503} else ["检查输入或联系项目管理员"],
    }


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=_error_contract(request, exc.status_code, exc.detail), headers=exc.headers)


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(json.dumps(build_log_event("unhandled_exception", level="ERROR", request_id=getattr(request.state, "request_id", None), error_type=type(exc).__name__), ensure_ascii=False))
    return JSONResponse(status_code=500, content=_error_contract(request, 500, "服务器处理失败", technical_message=None))


@app.exception_handler(LLMRuntimeError)
async def llm_runtime_error_handler(request: Request, exc: LLMRuntimeError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={**_error_contract(request, 503, str(exc), error_code=exc.error_type), "error_type": exc.error_type},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    safe_errors = [
        {key: value for key, value in error.items() if key not in {"input", "ctx"}}
        for error in exc.errors()
    ]
    config_payload_rejected = any("config_json" in error.get("loc", ()) for error in exc.errors())
    if config_payload_rejected:
        return JSONResponse(
            status_code=400,
            content=_error_contract(request, 400, "Model profile config must not contain credentials or unsupported fields"),
        )
    return JSONResponse(status_code=422, content=_error_contract(request, 422, safe_errors))


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
app.include_router(semantic.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(semantic_catalog.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(quality.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(regulatory_context.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(global_search.router, prefix=settings.api_prefix, dependencies=secured)
app.include_router(requirement_workspace.router, prefix=settings.api_prefix, dependencies=secured)
