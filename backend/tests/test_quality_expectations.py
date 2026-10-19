import re
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models import DataQualityExpectation
from app.services.auth.resource_guard import _path_resource


def test_quality_expectations_keep_ai_suggestions_separate_and_reuse_confirmed_rules() -> None:
    with _client() as client:
        project = _post(client, "/api/projects", {"name": "质量治理项目"})
        table = _post(client, "/api/target-tables", {
            "project_id": project["id"], "table_code": "YBT_CUSTOMER", "table_name": "客户信息",
        })
        field = _post(client, "/api/fields", {
            "project_id": project["id"], "target_table_id": table["id"],
            "field_code": "CUSTOMER_NO", "field_name": "客户编号", "required_flag": True,
        })
        suite = _post(client, f"/api/projects/{project['id']}/uat-suites", {
            "suite_name": "客户编号质量验收", "suite_type": "custom", "cases": [{
                "case_code": "QUALITY-CUSTOMER-NO", "case_name": "客户编号非空", "case_category": "data",
                "execution_mode": "manual", "severity": "high",
            }],
        })
        uat_case_id = suite["cases"][0]["id"]

        created = _post(client, f"/api/projects/{project['id']}/quality-expectations", {
            "rule_code": "customer_no_not_null", "rule_name": "客户编号不得为空",
            "description": "监管报送客户记录必须提供客户编号。", "rule_type": "not_null",
            "status": "ai_suggested", "source_type": "ai_suggestion", "confidence_level": "medium",
            "bindings": [
                {"scope_type": "requirement", "entity_type": "target_field", "entity_id": field["id"]},
                {"scope_type": "uat", "entity_type": "uat_case", "entity_id": uat_case_id},
                {"scope_type": "monitoring", "entity_type": "monitoring_target", "entity_key": "customer_daily_quality"},
            ],
        })
        assert created["status"] == "ai_suggested"
        assert created["confirmed_by"] is None
        assert {item["scope_type"] for item in created["bindings"]} == {"requirement", "uat", "monitoring"}
        assert client.get(f"/api/projects/{project['id']}/quality-expectations?status=confirmed").json() == []

        confirmed = _post(client, f"/api/quality-expectations/{created['id']}/status", {
            "status": "confirmed", "comment": "已由数据治理负责人确认",
        })
        assert confirmed["status"] == "confirmed"
        assert confirmed["confirmed_by"] is not None
        assert confirmed["status_reason"] == "已由数据治理负责人确认"
        assert len(client.get(f"/api/projects/{project['id']}/quality-expectations?scope_type=uat").json()) == 1
        assert len(client.get(f"/api/projects/{project['id']}/quality-expectations?scope_type=monitoring").json()) == 1


def test_quality_expectation_rejects_unsafe_or_cross_project_binding_shapes() -> None:
    with _client() as client:
        project = _post(client, "/api/projects", {"name": "质量治理项目 A"})
        other_project = _post(client, "/api/projects", {"name": "质量治理项目 B"})
        other_table = _post(client, "/api/target-tables", {
            "project_id": other_project["id"], "table_code": "YBT_OTHER", "table_name": "其他表",
        })
        other_field = _post(client, "/api/fields", {
            "project_id": other_project["id"], "target_table_id": other_table["id"],
            "field_code": "OTHER_NO", "field_name": "其他编号",
        })
        invalid_expression = client.post(f"/api/projects/{project['id']}/quality-expectations", json={
            "rule_code": "unsafe", "rule_name": "不完整表达式", "rule_type": "custom_expression",
        })
        assert invalid_expression.status_code == 422
        cross_project = client.post(f"/api/projects/{project['id']}/quality-expectations", json={
            "rule_code": "cross_project", "rule_name": "跨项目绑定", "rule_type": "not_null",
            "bindings": [{"scope_type": "requirement", "entity_type": "target_field", "entity_id": other_field["id"]}],
        })
        assert cross_project.status_code == 422


def test_quality_binding_rejections_are_chinese_without_leaking_identifiers() -> None:
    """绑定校验失败时必须给出具体的中文业务原因，且不得把枚举值直出。

    历史实现里这些 422 的 detail 是纯英文（如
    "target_field cannot be used for uat quality scope"），会把
    entity_type / scope_type 这类机器标识符直接给用户看。本测试钉死两件事：
    1. detail 含中文且能区分不同失败原因（不是句泛化兑底）；
    2. detail 不含任何 ASCII 字母（也就不会漏出枚举值）。
    """
    ascii_letter = re.compile(r"[A-Za-z]")

    with _client() as client:
        project = _post(client, "/api/projects", {"name": "质量绑定文案项目"})
        table = _post(client, "/api/target-tables", {
            "project_id": project["id"], "table_code": "YBT_LABEL", "table_name": "文案表",
        })
        field = _post(client, "/api/fields", {
            "project_id": project["id"], "target_table_id": table["id"],
            "field_code": "LABEL_NO", "field_name": "文案编号",
        })

        # target_field 在 requirement 范围内合法，在 uat 范围内不合法 -> 走 :224 分支
        bad_combination = client.post(f"/api/projects/{project['id']}/quality-expectations", json={
            "rule_code": "bad_combo", "rule_name": "类型与范围不匹配", "rule_type": "not_null",
            "bindings": [{"scope_type": "uat", "entity_type": "target_field", "entity_id": field["id"]}],
        })
        # monitoring_target 只接受 entity_key -> 同时给 entity_id 走 :227 分支
        monitoring_with_id = client.post(f"/api/projects/{project['id']}/quality-expectations", json={
            "rule_code": "monitoring_bad", "rule_name": "监控目标形状错误", "rule_type": "not_null",
            "bindings": [{"scope_type": "monitoring", "entity_type": "monitoring_target", "entity_id": 1}],
        })

        for response, expected_fragment in (
            (bad_combination, "不能用于"),
            (monitoring_with_id, "监控目标只能填实体标识"),
        ):
            assert response.status_code == 422, response.text
            detail = response.json()["detail"]
            assert isinstance(detail, str), detail
            assert expected_fragment in detail, detail
            assert not ascii_letter.search(detail), f"detail 漏出了机器标识符：{detail!r}"

        # 两条失败原因必须可区分，不能被堰缩成同一句泛化兑底
        assert bad_combination.json()["detail"] != monitoring_with_id.json()["detail"]


def test_quality_binding_requires_entity_id_or_key_without_leaking_identifiers() -> None:
    """实体编号/标识互斥的两条分支，同样只能是中文。"""
    ascii_letter = re.compile(r"[A-Za-z]")

    with _client() as client:
        project = _post(client, "/api/projects", {"name": "质量绑定形状项目"})
        table = _post(client, "/api/target-tables", {
            "project_id": project["id"], "table_code": "YBT_SHAPE", "table_name": "形状表",
        })
        field = _post(client, "/api/fields", {
            "project_id": project["id"], "target_table_id": table["id"],
            "field_code": "SHAPE_NO", "field_name": "形状编号",
        })

        # 非 monitoring 实体同时给了 entity_key -> 走 :230 分支
        both_identity = client.post(f"/api/projects/{project['id']}/quality-expectations", json={
            "rule_code": "both_identity", "rule_name": "双重身份", "rule_type": "not_null",
            "bindings": [{
                "scope_type": "requirement", "entity_type": "target_field",
                "entity_id": field["id"], "entity_key": "LEGACY-KEY",
            }],
        })
        assert both_identity.status_code == 422, both_identity.text
        detail = both_identity.json()["detail"]
        assert isinstance(detail, str), detail
        assert "必须填实体编号" in detail, detail
        assert not ascii_letter.search(detail), f"detail 漏出了机器标识符：{detail!r}"


def test_quality_binding_cross_project_target_reports_chinese_reason() -> None:
    """跨项目目标走 :233 分支：「不属于当前项目」要能穿过两道中文闸门。"""
    ascii_letter = re.compile(r"[A-Za-z]")

    with _client() as client:
        project = _post(client, "/api/projects", {"name": "质量绑定项目甲"})
        other_project = _post(client, "/api/projects", {"name": "质量绑定项目乙"})
        other_table = _post(client, "/api/target-tables", {
            "project_id": other_project["id"], "table_code": "YBT_FAR", "table_name": "外向表",
        })
        other_field = _post(client, "/api/fields", {
            "project_id": other_project["id"], "target_table_id": other_table["id"],
            "field_code": "FAR_NO", "field_name": "外向编号",
        })

        response = client.post(f"/api/projects/{project['id']}/quality-expectations", json={
            "rule_code": "cross_project_binding", "rule_name": "跨项目绑定", "rule_type": "not_null",
            "bindings": [{
                "scope_type": "requirement", "entity_type": "target_field",
                "entity_id": other_field["id"],
            }],
        })
        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert isinstance(detail, str), detail
        assert "不属于当前项目" in detail, detail
        assert not ascii_letter.search(detail), f"detail 漏出了机器标识符：{detail!r}"


def test_resource_guard_resolves_quality_expectation_routes() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        expectation = DataQualityExpectation(
            project_id=17,
            rule_code="guarded_rule",
            rule_name="守卫规则",
            rule_type="not_null",
        )
        session.add(expectation)
        session.commit()

        resolved = _path_resource(
            session,
            f"/api/quality-expectations/{expectation.id}/status",
            {"expectation_id": str(expectation.id)},
        )

        assert resolved is expectation
        assert resolved.project_id == 17
    Base.metadata.drop_all(engine)


def _post(client: TestClient, path: str, payload: dict) -> dict:
    response = client.post(path, json=payload)
    assert response.status_code in {200, 201}, response.text
    return response.json()


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
