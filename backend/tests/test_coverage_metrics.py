"""Phase H (execution spec Phase 13): traceable coverage metrics.

The gates under test are: the numerator may only contain confirmed/approved
facts, the denominator must be a real eligible population (target fields x
enabled scenarios), and an empty denominator must stay unavailable instead of
being displayed as 0%.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.core.database import Base, get_db
from app.core.settings import get_settings
from app.models import (
    LineageNode,
    MappingEvidenceReference,
    ProductScenario,
    Project,
    ScenarioBusinessMapping,
    ScenarioTechnicalLineage,
    TargetField,
    TargetTable,
)
from app.services.analytics.metric_query_service import build_project_overview


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@contextmanager
def _coverage_client(monkeypatch) -> Iterator[tuple[TestClient, sessionmaker]]:
    monkeypatch.setenv("AUTH_MODE", "required")
    monkeypatch.setenv("JWT_SECRET_KEY", "tests-generate-this-non-production-secret")
    get_settings.cache_clear()
    from app.services.storage.factory import get_storage_service
    from app.services.task_queue.factory import get_task_queue

    get_storage_service.cache_clear()
    get_task_queue.cache_clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    from app.main import app

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client, session_factory
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        get_storage_service.cache_clear()
        get_task_queue.cache_clear()
        get_settings.cache_clear()


def _bootstrap(client: TestClient) -> dict[str, str]:
    password = "test-only-platform-bootstrap-password"
    response = client.post("/api/admin/bootstrap", json={
        "institution_code": "PLATFORM", "institution_name": "脱敏平台运营方", "institution_type": "platform_operator",
        "username": "platform_admin", "display_name": "平台管理员", "email": "platform@example.invalid", "password": password,
    })
    assert response.status_code == 201, response.text
    login = client.post("/api/auth/login", json={"username": "platform_admin", "password": password})
    assert login.status_code == 200, login.text
    return _bearer(login.json()["access_token"])


def _project(client: TestClient, headers: dict[str, str], name: str) -> int:
    bank = client.post("/api/admin/institutions", headers=headers, json={
        "institution_code": f"BANK_{name}", "institution_name": f"{name}银行", "institution_type": "bank",
    }).json()
    project = client.post("/api/projects", headers=headers, json={"name": name, "institution_id": bank["id"]}).json()
    return project["id"]


def _seed_scope(session_factory, project_id: int, *, business_status: str = "draft", open_questions: str | None = None) -> dict[str, int]:
    """One target field, one enabled scenario and one draft/confirmed business mapping."""

    with session_factory() as db:
        table = TargetTable(project_id=project_id, table_code="EAST_CUSTOMER", table_name="EAST 客户表")
        scenario = ProductScenario(project_id=project_id, scenario_code="MONTHLY", scenario_name="月度报送", enabled=True)
        db.add_all([table, scenario])
        db.flush()
        field = TargetField(project_id=project_id, target_table_id=table.id, field_code="CUSTOMER_ID", field_name="客户统一编号")
        db.add(field)
        db.flush()
        mapping = ScenarioBusinessMapping(
            project_id=project_id, target_field_id=field.id, scenario_id=scenario.id,
            business_definition="客户统一编号", business_confirm_status=business_status,
            ai_generated_content="AI 建议：来源于客户主表", open_questions=open_questions,
        )
        db.add(mapping)
        db.commit()
        return {"table_id": table.id, "scenario_id": scenario.id, "field_id": field.id, "business_mapping_id": mapping.id}


def test_empty_denominator_is_unavailable_everywhere(monkeypatch) -> None:
    with _coverage_client(monkeypatch) as (client, session_factory):
        headers = _bootstrap(client)
        project_id = _project(client, headers, "EMPTY")

        overview = client.get(f"/api/projects/{project_id}/analytics/overview", headers=headers)
        dashboard = client.get(f"/api/projects/{project_id}/dashboard", headers=headers)

        assert overview.status_code == 200, overview.text
        business = overview.json()["metrics"]["business_definition_coverage"]
        assert business["denominator"] == 0
        assert business["value"] is None

        assert dashboard.status_code == 200, dashboard.text
        coverage = dashboard.json()["metric_definitions"]["regulatory_coverage"]
        assert coverage["denominator"] == 0
        assert coverage["value"] is None
        assert coverage["scope"]
        assert coverage["definition"]["excluded_population"]


def test_ai_draft_never_counts_toward_official_coverage(monkeypatch) -> None:
    with _coverage_client(monkeypatch) as (client, session_factory):
        headers = _bootstrap(client)
        project_id = _project(client, headers, "DRAFT")
        scope = _seed_scope(session_factory, project_id, business_status="draft")

        draft = _overview(session_factory, project_id)["metrics"]["business_definition_coverage"]
        assert draft["denominator"] == 1
        assert draft["numerator"] == 0
        assert draft["value"] == 0.0

        with session_factory() as db:
            mapping = db.get(ScenarioBusinessMapping, scope["business_mapping_id"])
            mapping.business_confirm_status = "confirmed"
            db.commit()

        confirmed = _overview(session_factory, project_id)["metrics"]["business_definition_coverage"]
        assert confirmed["numerator"] == 1
        assert confirmed["value"] == 1.0
        assert confirmed["definition"]["numerator_definition"]


def test_disabled_scenario_stays_out_of_the_eligible_population(monkeypatch) -> None:
    with _coverage_client(monkeypatch) as (client, session_factory):
        headers = _bootstrap(client)
        project_id = _project(client, headers, "DISABLED")
        scope = _seed_scope(session_factory, project_id, business_status="confirmed")
        with session_factory() as db:
            disabled = ProductScenario(project_id=project_id, scenario_code="YEARLY", scenario_name="年度报送", enabled=False)
            db.add(disabled)
            db.flush()
            db.add(ScenarioBusinessMapping(
                project_id=project_id, target_field_id=scope["field_id"], scenario_id=disabled.id,
                business_definition="年度口径", business_confirm_status="confirmed",
            ))
            db.commit()

        overview = _overview(session_factory, project_id)
        metric = overview["metrics"]["business_definition_coverage"]
        assert metric["denominator"] == 1, "停用场景不得进入分母"
        assert metric["numerator"] == 1, "停用场景下的确认记录不得进入分子"
        assert overview["coverage_context"]["business_mapping_recorded"] == 1

        dashboard = client.get(f"/api/projects/{project_id}/dashboard", headers=headers).json()
        assert dashboard["coverage_context"]["eligible_field_scenario_pairs"] == 1
        assert dashboard["metric_definitions"]["regulatory_coverage"]["value"] == 1.0


def test_lineage_coverage_and_unresolved_rate_come_from_lineage_nodes(monkeypatch) -> None:
    with _coverage_client(monkeypatch) as (client, session_factory):
        headers = _bootstrap(client)
        project_id = _project(client, headers, "LINEAGE")
        scope = _seed_scope(session_factory, project_id, business_status="confirmed")
        with session_factory() as db:
            db.add_all([
                LineageNode(project_id=project_id, node_type="target_field", logical_name="客户统一编号", target_field_id=scope["field_id"], unresolved_flag=False),
                LineageNode(project_id=project_id, node_type="source_field", logical_name="未知来源", unresolved_flag=True),
            ])
            db.commit()

        overview = _overview(session_factory, project_id)
        coverage = overview["metrics"]["target_field_lineage_coverage"]
        unresolved = overview["metrics"]["lineage_unresolved_rate"]
        assert coverage["numerator"] == 1 and coverage["denominator"] == 1
        assert coverage["value"] == 1.0
        assert unresolved["numerator"] == 1 and unresolved["denominator"] == 2
        assert unresolved["value"] == 0.5
        assert overview["coverage_context"]["lineage_nodes"] == 2


def test_open_question_and_evidence_metrics_use_mapping_objects(monkeypatch) -> None:
    with _coverage_client(monkeypatch) as (client, session_factory):
        headers = _bootstrap(client)
        project_id = _project(client, headers, "EVIDENCE")
        scope = _seed_scope(session_factory, project_id, business_status="confirmed", open_questions="客户编号是否复用 ECIF 主键？")
        with session_factory() as db:
            db.add(ScenarioTechnicalLineage(
                project_id=project_id, target_field_id=scope["field_id"], scenario_id=scope["scenario_id"],
                business_mapping_id=scope["business_mapping_id"], tech_confirm_status="confirmed",
            ))
            db.flush()
            for index in range(2):
                db.add(MappingEvidenceReference(
                    project_id=project_id, mapping_type="scenario_business", mapping_id=scope["business_mapping_id"],
                    evidence_type="manual_note", source_name=f"人工确认-{index}", evidence_summary="客户编号口径确认",
                ))
            db.commit()

        overview = _overview(session_factory, project_id)
        evidence = overview["metrics"]["evidence_coverage"]
        assert evidence["numerator"] == 1, "多条证据引用只算一个映射对象"
        assert evidence["denominator"] == 2
        assert evidence["value"] == 0.5
        questions = overview["metrics"]["open_question_rate"]
        assert questions["numerator"] == 1 and questions["denominator"] == 2

        dashboard = client.get(f"/api/projects/{project_id}/dashboard", headers=headers).json()
        assert dashboard["metric_definitions"]["evidence_coverage"]["numerator"] == 1
        assert dashboard["metric_definitions"]["evidence_coverage"]["denominator"] == 2


def _overview(session_factory, project_id: int) -> dict:
    with session_factory() as db:
        return build_project_overview(db, project_id)
