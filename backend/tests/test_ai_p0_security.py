from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.settings import get_settings
from app.main import app
from app.models import (
    Institution,
    InstitutionMembership,
    ModelCallLog,
    Project,
    ProjectMembership,
    PromptTemplateVersion,
    RagEvaluationCase,
    RagEvaluationRun,
    User,
)
from app.services.auth.dependencies import Principal, get_current_principal


@contextmanager
def _client(monkeypatch) -> Iterator[tuple[TestClient, sessionmaker, dict[str, object]]]:
    monkeypatch.setenv("AUTH_MODE", "required")
    monkeypatch.setenv("APP_SECRET_KEY", "ai-p0-test-app-secret")
    monkeypatch.setenv("JWT_SECRET_KEY", "ai-p0-test-jwt-secret-with-more-than-32-characters")
    get_settings.cache_clear()

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)

    def override_db() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    with factory() as db:
        operator = Institution(
            institution_code="P0_OPERATOR",
            institution_name="平台运营方",
            institution_type="platform_operator",
        )
        bank_a = Institution(institution_code="P0_A", institution_name="甲银行")
        bank_b = Institution(institution_code="P0_B", institution_name="乙银行")
        db.add_all([operator, bank_a, bank_b])
        db.flush()

        admin = User(username="p0_platform_admin", display_name="平台管理员", status="active")
        analyst = User(username="p0_analyst", display_name="甲银行分析员", status="active")
        outsider = User(username="p0_outsider", display_name="乙银行分析员", status="active")
        db.add_all([admin, analyst, outsider])
        db.flush()
        db.add_all([
            InstitutionMembership(
                institution_id=operator.id,
                user_id=admin.id,
                role="institution_admin",
                status="active",
            ),
            InstitutionMembership(
                institution_id=bank_a.id,
                user_id=analyst.id,
                role="member",
                status="active",
            ),
            InstitutionMembership(
                institution_id=bank_b.id,
                user_id=outsider.id,
                role="member",
                status="active",
            ),
        ])
        project_a = Project(name="甲银行项目", institution_id=bank_a.id, project_status="active")
        project_b = Project(name="乙银行项目", institution_id=bank_b.id, project_status="active")
        db.add_all([project_a, project_b])
        db.flush()
        model_call = ModelCallLog(
            project_id=project_a.id,
            model_profile_id=None,
            prompt_key="lineage_edge_explanation",
            prompt_version=1,
            provider="mock",
            model_name="mock-llm",
            execution_kind="mock_model",
            request_hash="a" * 64,
            context_hash="j" * 64,
            context_complete=True,
            output_hash="b" * 64,
            status="success",
            latency_ms=1,
            confidentiality_level="internal",
            created_by=analyst.username,
        )
        requirement_call = ModelCallLog(
            project_id=project_a.id,
            model_profile_id=None,
            prompt_key="requirement_field_candidate",
            prompt_version=3,
            skill_key="requirement_field_candidate",
            skill_version="v3",
            provider="mock",
            model_name="mock-llm",
            execution_kind="mock_model",
            request_hash="d" * 64,
            context_hash="e" * 64,
            context_complete=True,
            output_hash="f" * 64,
            status="success",
            latency_ms=1,
            confidentiality_level="internal",
            created_by=analyst.username,
        )
        mapping_call = ModelCallLog(
            project_id=project_a.id,
            model_profile_id=None,
            prompt_key="source_to_mart_mapping",
            prompt_version=4,
            skill_key="source_to_mart_mapping",
            skill_version="v4",
            provider="mock",
            model_name="mock-llm",
            execution_kind="mock_model",
            request_hash="g" * 64,
            context_hash="h" * 64,
            context_complete=True,
            output_hash="i" * 64,
            status="success",
            latency_ms=1,
            confidentiality_level="internal",
            created_by=analyst.username,
        )
        db.add_all([
            ProjectMembership(
                project_id=project_a.id,
                user_id=analyst.id,
                project_role="project_manager",
                status="active",
            ),
            ProjectMembership(
                project_id=project_b.id,
                user_id=outsider.id,
                project_role="project_manager",
                status="active",
            ),
            PromptTemplateVersion(
                prompt_key="lineage_edge_explanation",
                version_no=1,
                system_prompt="test system",
                user_prompt_template="目标：{target}\n证据：{evidence}",
                enabled=True,
                created_by=admin.username,
            ),
            model_call,
            requirement_call,
            mapping_call,
        ])
        run = RagEvaluationRun(
            project_id=project_a.id,
            institution_id=bank_a.id,
            run_name="权限回归样例",
            status="completed",
            created_by=analyst.username,
        )
        db.add(run)
        db.commit()
        ids = {
            "admin": admin.id,
            "analyst": analyst.id,
            "outsider": outsider.id,
            "project_a": project_a.id,
            "project_b": project_b.id,
            "run": run.id,
            "model_call": model_call.id,
            "requirement_call": requirement_call.id,
            "mapping_call": mapping_call.id,
        }

    try:
        with TestClient(app) as client:
            yield client, factory, ids
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
        get_settings.cache_clear()


def _as(principal: Principal) -> None:
    app.dependency_overrides[get_current_principal] = lambda: principal


def _anonymous() -> None:
    app.dependency_overrides.pop(get_current_principal, None)


def test_ai_routes_require_authentication_and_platform_admin_for_prompts(monkeypatch) -> None:
    with _client(monkeypatch) as (client, _factory, ids):
        _anonymous()
        assert client.get("/api/prompt-versions").status_code == 401

        _as(Principal(int(ids["analyst"]), "p0_analyst", "甲银行分析员"))
        assert client.get("/api/prompt-versions").status_code == 403

        _as(Principal(int(ids["admin"]), "p0_platform_admin", "平台管理员"))
        response = client.get("/api/prompt-versions")
        assert response.status_code == 200
        assert response.json()[0]["prompt_key"] == "lineage_edge_explanation"
        assert response.json()[0]["runtime_binding"] == {
            "editable": False,
            "activation": "latest_enabled_by_prompt_key",
            "system_prompt": "effective",
            "user_prompt_template": "read_only_not_rendered",
            "note": "当前版本记录仅供技术查看；编辑、测试、发布和回滚尚未开放。",
        }


def test_evaluation_feedback_and_run_access_are_project_isolated(monkeypatch) -> None:
    with _client(monkeypatch) as (client, factory, ids):
        project_a = int(ids["project_a"])
        project_b = int(ids["project_b"])
        run_id = int(ids["run"])

        _as(Principal(int(ids["analyst"]), "p0_analyst", "甲银行分析员"))
        created_case = client.post(
            f"/api/projects/{project_a}/evaluations/cases",
            json={"case_name": "本人项目", "query_text": "贷款余额"},
        )
        assert created_case.status_code == 200, created_case.text
        assert created_case.json()["created_by"] == "p0_analyst"
        assert created_case.json()["institution_id"] is not None
        assert client.get(f"/api/projects/{project_a}/evaluations/cases").status_code == 200
        assert client.get(f"/api/projects/{project_b}/evaluations/cases").status_code in (403, 404)

        assert client.get(f"/api/evaluation-runs/{run_id}").status_code == 200
        assert client.get(f"/api/evaluation-runs/{run_id}/results").status_code == 200

        feedback = client.post(
            f"/api/projects/{project_a}/feedback",
            json={
                "feedback_type": "lineage_explanation",
                "target_type": "lineage_edge",
                "target_id": 7,
                "rating": "incorrect",
                "model_call_log_id": ids["model_call"],
                "output_hash": "c" * 64,
                "execution_kind": "real_model",
            },
        )
        assert feedback.status_code == 200, feedback.text
        assert feedback.json()["created_by"] == "p0_analyst"
        assert feedback.json()["institution_id"] is not None
        assert feedback.json()["model_call_log_id"] == ids["model_call"]
        assert feedback.json()["output_hash"] == "b" * 64
        assert feedback.json()["execution_kind"] == "mock_model"

        regression = client.post(
            f"/api/projects/{project_a}/feedback/{feedback.json()['id']}/evaluation-case",
            json={},
        )
        assert regression.status_code == 200, regression.text
        assert regression.json()["case_type"] == "feedback_regression"
        assert regression.json()["source_feedback_id"] == feedback.json()["id"]
        assert regression.json()["target_type"] == "lineage_edge"
        assert regression.json()["execution_kind"] == "mock_model"
        assert regression.json()["output_hash"] == "b" * 64
        assert regression.json()["assertions_json"][0] == {
            "assertion_type": "execution_kind_matches",
            "expected": "mock_model",
        }

        repeated = client.post(
            f"/api/projects/{project_a}/feedback/{feedback.json()['id']}/evaluation-case",
            json={},
        )
        assert repeated.status_code == 200
        assert repeated.json()["id"] == regression.json()["id"]

        cross_project_feedback = client.post(
            f"/api/projects/{project_b}/feedback",
            json={
                "feedback_type": "lineage_explanation",
                "target_type": "lineage_edge",
                "target_id": 7,
                "rating": "incorrect",
                "model_call_log_id": ids["model_call"],
            },
        )
        assert cross_project_feedback.status_code in (403, 404)
        cross_project_regression = client.post(
            f"/api/projects/{project_b}/feedback/{feedback.json()['id']}/evaluation-case",
            json={},
        )
        assert cross_project_regression.status_code in (403, 404)

        with factory() as db:
            persisted = db.query(RagEvaluationRun).filter_by(id=run_id).one()
            assert persisted.created_by == "p0_analyst"
            assert persisted.institution_id is not None
            assert db.query(RagEvaluationCase).filter_by(
                source_feedback_id=feedback.json()["id"]
            ).count() == 1


def test_feedback_regression_samples_cover_lineage_requirement_and_mapping(monkeypatch) -> None:
    samples = (
        (
            "lineage_explanation",
            "lineage_edge",
            11,
            "model_call",
            "lineage_edge_explanation",
            "b" * 64,
        ),
        (
            "requirement_candidate",
            "requirement_generation_item",
            12,
            "requirement_call",
            "requirement_field_candidate",
            "f" * 64,
        ),
        (
            "mapping_draft",
            "source_to_mart_mapping",
            13,
            "mapping_call",
            "source_to_mart_mapping",
            "i" * 64,
        ),
    )
    with _client(monkeypatch) as (client, _factory, ids):
        project_id = int(ids["project_a"])
        _as(Principal(int(ids["analyst"]), "p0_analyst", "甲银行分析员"))
        for feedback_type, target_type, target_id, log_key, skill_key, output_hash in samples:
            feedback = client.post(
                f"/api/projects/{project_id}/feedback",
                json={
                    "feedback_type": feedback_type,
                    "target_type": target_type,
                    "target_id": target_id,
                    "rating": "incorrect",
                    "model_call_log_id": ids[log_key],
                    "comment": f"回归 {skill_key}",
                },
            )
            assert feedback.status_code == 200, feedback.text
            regression = client.post(
                f"/api/projects/{project_id}/feedback/{feedback.json()['id']}/evaluation-case",
                json={},
            )
            assert regression.status_code == 200, regression.text
            payload = regression.json()
            assert payload["case_type"] == "feedback_regression"
            assert payload["target_type"] == target_type
            assertions = {
                item["assertion_type"]: item["expected"]
                for item in payload["assertions_json"]
            }
            assert assertions["skill_key_matches"] == skill_key
            assert assertions["output_hash_matches"] == output_hash
            assert assertions["execution_kind_matches"] == "mock_model"
            assert assertions["context_complete_is"] is True


def test_evaluation_run_creation_derives_creator_and_institution(monkeypatch) -> None:
    import app.api.knowledge_rag as knowledge_rag

    with _client(monkeypatch) as (client, _factory, ids):
        monkeypatch.setattr(knowledge_rag, "submit_project_job", lambda *args, **kwargs: None)
        _as(Principal(int(ids["analyst"]), "p0_analyst", "甲银行分析员"))
        response = client.post(
            f"/api/projects/{ids['project_a']}/evaluations/runs",
            json={"run_name": "权限用例"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["created_by"] == "p0_analyst"
        assert response.json()["institution_id"] is not None
