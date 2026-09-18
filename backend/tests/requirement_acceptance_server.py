"""Loopback-only full-app acceptance server with disposable in-memory data.

No .env file, startup hooks, external database, queue, or model is used.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import settings as settings_module

settings = settings_module.Settings(_env_file=None, database_url="sqlite://", environment="test",
    auth_mode="optional", llm_provider="mock", embedding_provider="mock", vector_store_provider="mock",
    app_secret_key="isolated-acceptance-secret-not-production", jwt_secret_key="isolated-acceptance-jwt-not-production")
settings_module.get_settings = lambda: settings

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool
from app.core.database import Base, get_db
from app.main import app
from app.models import ProductScenario, ProjectMembership, Requirement, TargetField
from app.services.auth.dependencies import Principal, get_current_principal
from test_lineage_paths import _seed_assets

engine = create_engine("sqlite:///file:requirement_acceptance?mode=memory&cache=shared&uri=true",
    poolclass=QueuePool, connect_args={"check_same_thread": False, "timeout": 30})
Base.metadata.create_all(engine)
with Session(engine) as db:
    _, user, project, target, _, _ = _seed_assets(db)
    project.name = "隔离合成需求版本验收"
    db.add(ProjectMembership(project_id=project.id, user_id=user.id, project_role="project_manager", status="active"))
    scenario = ProductScenario(project_id=project.id, scenario_code="SYNTH", scenario_name="合成客户报送")
    db.add(scenario)
    db.flush()
    ids = [target.id]
    for i in range(7):
        field = TargetField(project_id=project.id, target_table_id=target.target_table_id,
            field_code=f"SYNTH_{i}", field_name=f"合成客户字段{i}")
        db.add(field)
        db.flush()
        ids.append(field.id)
    scope = {"target_table_id": target.target_table_id, "scenario_id": scenario.id,
        "field_ids": ids, "background": "隔离样本，不用于生产报送", "objective": "独立版本验收",
        "effective_date": None, "inclusion": "活跃客户", "exclusion": "注销客户",
        "document_ids": [], "source_table_ids": [], "mart_table_ids": []}
    db.add_all([Requirement(project_id=project.id, name="合成需求A", version=1, scope_json=scope),
                Requirement(project_id=project.id, name="合成需求B", version=1, scope_json=scope)])
    db.commit()
    principal = Principal(user.id, user.username, "隔离验收用户")


def isolated_db():
    with Session(engine) as db:
        yield db


app.dependency_overrides[get_db] = isolated_db
app.dependency_overrides[get_current_principal] = lambda: principal

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), lifespan="off", access_log=False)
