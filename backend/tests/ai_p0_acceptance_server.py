"""Loopback-only real-API fixture for the AI P0 browser acceptance."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("CORS_ORIGINS", "*")
os.environ.setdefault("AUTH_MODE", "required")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("EMBEDDING_PROVIDER", "mock")
os.environ.setdefault("VECTOR_STORE_PROVIDER", "mock")
os.environ.setdefault("TASK_QUEUE_PROVIDER", "inline")

from app.core.database import Base, get_db
from app.main import app
from app.models import (
    AIUserFeedback,
    Institution,
    InstitutionMembership,
    ModelCallLog,
    Project,
    ProjectMembership,
    PromptTemplateVersion,
    RagEvaluationCase,
    User,
)
from app.services.auth.dependencies import Principal, get_current_principal
from test_lineage_graph_contract import _seed_chain


def _seed_database(factory: sessionmaker) -> tuple[int, Principal]:
    with factory() as db:
        seeded = _seed_chain(db, code="P0")
        project = db.get(Project, seeded["project_id"])
        assert project is not None
        user = db.execute(select(User).where(User.username == "graph-user-P0")).scalar_one()
        project.name = "P0 浏览器隔离项目"
        project.bank_name = "P0 隔离银行"
        db.add(InstitutionMembership(institution_id=project.institution_id, user_id=user.id, role="institution_admin", status="active", created_by=user.id))
        platform = Institution(institution_code="P0_PLATFORM", institution_name="P0 平台运营方", institution_type="platform_operator", status="active")
        db.add(platform)
        db.flush()
        db.add(InstitutionMembership(institution_id=platform.id, user_id=user.id, role="institution_admin", status="active", created_by=user.id))
        db.add(ProjectMembership(project_id=project.id, user_id=user.id, project_role="project_manager", status="active", created_by=user.id))
        db.add(PromptTemplateVersion(
            prompt_key="lineage_edge_explanation",
            version_no=2,
            system_prompt="仅依据固定脚本事实和制度证据解释。",
            user_prompt_template="证据：{evidence}",
            output_schema_json={},
            enabled=True,
            change_note="P0 浏览器验收固定版本",
            created_by=user.username,
        ))
        db.flush()
        log = ModelCallLog(
            project_id=project.id,
            prompt_key="lineage_edge_explanation",
            prompt_version=2,
            skill_key="lineage_edge_explanation",
            skill_version="2",
            provider="mock",
            model_name="mock-lineage",
            execution_kind="mock_model",
            request_hash="d" * 64,
            context_hash="e" * 64,
            context_complete=False,
            context_budget_json={"unit": "characters", "used": 920, "limit": 800, "complete": False},
            input_summary="P0 browser acceptance fixture",
            output_summary="Mock lineage explanation",
            output_hash="f" * 64,
            citations_json=[],
            rejected_claims_json=[],
            execution_metadata_json={"execution_kind": "mock_model", "context_complete": False},
            status="succeeded",
            latency_ms=1,
            token_usage_json={},
            confidentiality_level="internal",
            created_by=user.username,
        )
        db.add(log)
        db.flush()
        db.add(AIUserFeedback(
            project_id=project.id,
            institution_id=project.institution_id,
            model_call_log_id=log.id,
            feedback_type="correction",
            target_type="lineage_edge",
            target_id=1,
            rating="negative",
            comment="来源说明需要补充过滤条件",
            output_hash="f" * 64,
            execution_kind="mock_model",
            execution_metadata_json={"execution_kind": "mock_model", "context_complete": False},
            created_by=user.username,
        ))
        db.add(RagEvaluationCase(
            project_id=project.id,
            institution_id=project.institution_id,
            case_name="P0 基线样例",
            case_type="rag",
            query_text="客户统一标识来自哪里",
            expected_knowledge_unit_ids_json=[],
            expected_source_system="客户信息系统",
            expected_table_name="客户基本信息表",
            expected_field_name="客户统一标识",
            expected_answer_keywords_json=["客户", "来源"],
            enabled=True,
            created_by=user.username,
        ))
        db.commit()
        return project.id, Principal(user.id, user.username, user.display_name)


_temp_dir = tempfile.TemporaryDirectory(prefix="ai-p0-acceptance-")
_database_path = Path(_temp_dir.name) / "acceptance.sqlite3"
engine = create_engine(f"sqlite:///{_database_path.as_posix()}", connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
factory = sessionmaker(bind=engine, autoflush=False)
project_id, principal = _seed_database(factory)


def isolated_db():
    session = factory()
    try:
        yield session
    finally:
        session.close()


app.dependency_overrides[get_db] = isolated_db
app.dependency_overrides[get_current_principal] = lambda: principal


if __name__ == "__main__":
    import uvicorn

    try:
        uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), lifespan="off", access_log=False)
    finally:
        engine.dispose()
        _temp_dir.cleanup()
