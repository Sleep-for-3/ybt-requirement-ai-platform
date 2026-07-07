from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import coze, datasources, db_profile, documents, nl_tasks, projects, retrieval, sql_files, target_fields, target_tables, templates
from app.core.settings import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)

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
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


app.include_router(projects.router, prefix=settings.api_prefix)
app.include_router(templates.projects_router, prefix=settings.api_prefix)
app.include_router(target_tables.router, prefix=settings.api_prefix)
app.include_router(target_fields.router, prefix=settings.api_prefix)
app.include_router(documents.router, prefix=settings.api_prefix)
app.include_router(sql_files.router, prefix=settings.api_prefix)
app.include_router(retrieval.router, prefix=settings.api_prefix)
app.include_router(coze.router, prefix=settings.api_prefix)
app.include_router(db_profile.router, prefix=settings.api_prefix)
app.include_router(templates.router, prefix=settings.api_prefix)
app.include_router(datasources.router, prefix=settings.api_prefix)
app.include_router(nl_tasks.router, prefix=settings.api_prefix)
