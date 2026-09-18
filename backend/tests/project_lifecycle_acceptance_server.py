"""Loopback-only project lifecycle fixture using an explicitly isolated PostgreSQL database."""

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import settings as settings_module


def _isolated_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL", "")
    database_name = make_url(database_url).database if database_url else ""
    if not database_url.startswith("postgresql") or not (database_name or "").startswith("ybt_codex_acceptance_"):
        raise RuntimeError("Project lifecycle acceptance requires an isolated ybt_codex_acceptance_* PostgreSQL database")
    return database_url


database_url = _isolated_database_url()
workspace = TemporaryDirectory(prefix="project-lifecycle-acceptance-")
settings = settings_module.Settings(
    _env_file=None,
    database_url=database_url,
    environment="test",
    auth_mode="required",
    llm_provider="mock",
    embedding_provider="mock",
    vector_store_provider="mock",
    storage_dir=workspace.name,
    storage_provider="local",
    task_queue_provider="inline",
    cors_origins="*",
    app_secret_key="synthetic-project-lifecycle-not-a-secret",
    jwt_secret_key="synthetic-project-lifecycle-not-a-secret",
)
settings_module.get_settings = lambda: settings

from app.core.database import Base, get_db
from app.main import app
from app.models import Institution, InstitutionMembership, Project, ProjectMembership, User
from app.services.auth.dependencies import Principal, get_current_principal


engine = create_engine(database_url, pool_pre_ping=True)
with engine.begin() as connection:
    connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
    connection.execute(text("CREATE SCHEMA public"))
Base.metadata.create_all(engine)

with Session(engine) as db:
    user = User(
        username="project-lifecycle-acceptance",
        display_name="项目生命周期隔离验收",
        email="project-lifecycle@example.invalid",
        status="active",
    )
    db.add(user)
    db.flush()
    institution = Institution(
        institution_code="PROJECT_LIFECYCLE_BANK",
        institution_name="项目生命周期隔离银行",
        institution_type="bank",
        status="active",
    )
    db.add(institution)
    db.flush()
    db.add(InstitutionMembership(
        institution_id=institution.id,
        user_id=user.id,
        role="institution_admin",
        status="active",
        created_by=user.id,
    ))
    existing = Project(
        name="已有隔离项目",
        bank_name=institution.institution_name,
        institution_id=institution.id,
        project_status="active",
    )
    db.add(existing)
    db.flush()
    db.add(ProjectMembership(
        project_id=existing.id,
        user_id=user.id,
        project_role="project_manager",
        status="active",
        created_by=user.id,
    ))
    db.commit()
    principal = Principal(user.id, user.username, user.display_name)


def isolated_db():
    with Session(engine) as db:
        yield db


app.dependency_overrides[get_db] = isolated_db
app.dependency_overrides[get_current_principal] = lambda: principal


if __name__ == "__main__":
    import uvicorn

    try:
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=int(sys.argv[1]),
            lifespan="off",
            access_log=False,
        )
    finally:
        engine.dispose()
        workspace.cleanup()
