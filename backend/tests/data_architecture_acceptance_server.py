"""Loopback-only architecture acceptance fixture; no environment file or real account."""
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import settings as settings_module

workspace = TemporaryDirectory(prefix="architecture-acceptance-")
settings = settings_module.Settings(_env_file=None, database_url="sqlite://", environment="test",
    auth_mode="required", llm_provider="mock", embedding_provider="mock", vector_store_provider="mock",
    storage_dir=workspace.name, storage_provider="local", task_queue_provider="inline", cors_origins="*",
    app_secret_key="synthetic-acceptance-only-not-a-secret", jwt_secret_key="synthetic-acceptance-only-not-a-secret")
settings_module.get_settings = lambda: settings

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.core.database import Base, get_db
from app.main import app
from app.models import (CatalogTable, CatalogSchema, DataSource, Institution, InstitutionMembership,
                        Project, ProjectMembership, User)
from app.services.auth.dependencies import Principal, get_current_principal

engine = create_engine("sqlite:///file:architecture_acceptance?mode=memory&cache=shared&uri=true",
                       connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
with Session(engine) as db:
    user = User(username="isolated-architecture", display_name="架构隔离验收")
    db.add(user); db.flush()
    for index, name in enumerate(["隔离甲行直报项目", "隔离乙行数仓项目"]):
        bank = Institution(institution_code=f"architecture-bank-{index}", institution_name=name)
        db.add(bank); db.flush()
        project = Project(name=name, institution_id=bank.id)
        db.add(project); db.flush()
        db.add(ProjectMembership(project_id=project.id, user_id=user.id, project_role="project_manager"))
        db.add(InstitutionMembership(institution_id=bank.id, user_id=user.id, role="institution_admin"))
        source = DataSource(project_id=project.id, name=f"隔离离线样本-{index}", db_type="sqlite")
        db.add(source); db.flush()
        schema = CatalogSchema(project_id=project.id, datasource_id=source.id, schema_name="sample")
        db.add(schema); db.flush()
        db.add(CatalogTable(project_id=project.id, datasource_id=source.id, catalog_schema_id=schema.id,
            database_name=f"bank_{index}", schema_name="sample", table_name="REG_CUSTOMER"))
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
        uvicorn.run(app, host="127.0.0.1", port=18741, lifespan="off", access_log=False)
    finally:
        engine.dispose()
        workspace.cleanup()
