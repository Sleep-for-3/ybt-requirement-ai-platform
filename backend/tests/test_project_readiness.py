from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app


def test_readiness_uses_critical_blockers_instead_of_simple_average() -> None:
    with _client() as client:
        project = _post(client, "/api/projects", {"name": "准备度示例项目"})

        readiness = client.get(f"/api/projects/{project['id']}/readiness")

        assert readiness.status_code == 200
        body = readiness.json()
        assert body["overall_status"] == "blocked"
        assert len(body["dimensions"]) == 17
        assert body["dimensions"]["target_field_definition"]["status"] == "blocked"
        assert any(item["code"] == "target_fields_missing" for item in body["critical_blockers"])
        assert any(item["code"] == "database_revision_not_head" for item in body["critical_blockers"])
        assert body["dimensions"]["project_configuration"]["status"] == "ready"
        assert all(set(item) == {"status", "score", "completed_count", "required_count", "blocking_reasons", "recommended_actions", "links"} for item in body["dimensions"].values())

        onboarding = client.get(f"/api/projects/{project['id']}/onboarding")
        assert onboarding.status_code == 200
        steps = onboarding.json()["steps"]
        assert len(steps) == 10
        assert steps[0]["status"] == "completed"
        assert steps[1]["status"] == "blocked"
        assert steps[1]["blocking_reasons"]


def test_uat_readiness_requires_all_four_approved_signoff_roles() -> None:
    with _client() as client:
        project = _post(client, "/api/projects", {"name": "UAT 签署准备度项目"})
        suite = _post(client, f"/api/projects/{project['id']}/uat-suites", {
            "suite_name": "签署准备度套件",
            "suite_type": "custom",
            "cases": [{
                "case_code": "PASS",
                "case_name": "自动通过",
                "case_category": "custom",
                "precondition_json": {"check_key": "always_pass"},
                "input_requirement_json": {"sanitized_fixture_only": True},
                "expected_result_json": {"status": "passed"},
                "execution_mode": "automatic",
                "severity": "critical",
                "display_order": 1,
            }],
        })
        run = _post(client, f"/api/uat-suites/{suite['id']}/runs", {"run_name": "签署准备度轮次"})
        run = _post(client, f"/api/uat-runs/{run['id']}/execute", {})["run"]

        before = client.get(f"/api/projects/{project['id']}/readiness").json()["dimensions"]["uat_status"]
        assert before["status"] == "blocked"
        assert before["blocking_reasons"][0]["code"] == "uat_signoff_incomplete"

        for role in ("business_owner", "technical_owner", "project_manager", "final_acceptance"):
            _post(client, f"/api/uat-runs/{run['id']}/signoff", {
                "signoff_role": role,
                "signoff_status": "approved",
                "comment": "公开脱敏签署",
            })
        after = client.get(f"/api/projects/{project['id']}/readiness").json()["dimensions"]["uat_status"]
        assert after["status"] == "ready"
        _post(client, f"/api/uat-runs/{run['id']}/signoff", {
            "signoff_role": "business_owner",
            "signoff_status": "rejected",
            "comment": "后续复核撤销业务验收",
        })
        revoked = client.get(f"/api/projects/{project['id']}/readiness").json()["dimensions"]["uat_status"]
        assert revoked["status"] == "blocked"
        assert revoked["blocking_reasons"][0]["code"] == "uat_signoff_incomplete"


def test_mapping_readiness_counts_each_field_scenario_pair() -> None:
    with _client() as client:
        project = _post(client, "/api/projects", {"name": "字段场景准备度项目"})
        table = _post(client, "/api/target-tables", {
            "project_id": project["id"],
            "table_code": "PAIR_TEST",
            "table_name": "字段场景测试表",
        })
        field = _post(client, "/api/fields", {
            "project_id": project["id"],
            "target_table_id": table["id"],
            "field_code": "PAIR_FIELD",
            "field_name": "字段场景测试字段",
        })
        first = _post(client, f"/api/projects/{project['id']}/scenarios", {"scenario_code": "FIRST", "scenario_name": "场景一"})
        _post(client, f"/api/projects/{project['id']}/scenarios", {"scenario_code": "SECOND", "scenario_name": "场景二"})
        disabled = _post(client, f"/api/projects/{project['id']}/scenarios", {"scenario_code": "DISABLED", "scenario_name": "已停用场景", "enabled": False})
        mapping = _post(client, f"/api/target-fields/{field['id']}/scenarios/{first['id']}/business-mapping", {
            "business_definition": "仅确认第一个场景",
            "final_content": "公开脱敏口径",
        })
        _post(client, f"/api/mappings/scenario_business/{mapping['id']}/evidence", {
            "evidence_type": "manual_note",
            "source_name": "公开脱敏场景证据",
            "evidence_summary": "仅覆盖第一个场景",
        })
        _post(client, f"/api/scenario-business-mappings/{mapping['id']}/confirm", {})
        disabled_mapping = _post(client, f"/api/target-fields/{field['id']}/scenarios/{disabled['id']}/business-mapping", {
            "business_definition": "停用场景不应计入覆盖率",
            "final_content": "公开脱敏口径",
        })
        _post(client, f"/api/mappings/scenario_business/{disabled_mapping['id']}/evidence", {
            "evidence_type": "manual_note",
            "source_name": "停用场景证据",
            "evidence_summary": "该记录只用于验证停用场景不会冒充启用场景。",
        })
        _post(client, f"/api/scenario-business-mappings/{disabled_mapping['id']}/confirm", {})

        dimension = client.get(f"/api/projects/{project['id']}/readiness").json()["dimensions"]["business_mapping"]

        assert dimension["completed_count"] == 1
        assert dimension["required_count"] == 2
        assert dimension["status"] == "blocked"


@contextmanager
def _client() -> Iterator[TestClient]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)

    def override() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def _post(client: TestClient, path: str, payload: dict) -> dict:
    response = client.post(path, json=payload)
    assert response.status_code in {200, 201}, response.text
    return response.json()
