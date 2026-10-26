"""导出软门禁：字段级有据可查率只标记、不阻断。

这层 gate 的存在理由是真实事故形态：有据率只写在离线报告里，导出接口不看它，
任何一次误操作都能把"正文还是 AI 草稿/待业务补充"的文档当正式文件发出去，
而且没人能在交付链路上看到"这份文档有多少字段被证据支撑"。

固定四件事：

1. 结论进响应头（``X-Requirement-Quality-Gate`` 等），且写进审计 ``quality_gate``；
2. 低于阈值只标 ``mark``，**不返回 4xx**——软门禁不能把能出的文档卡死；
3. 统计失败时给 ``unknown`` 并写明原因，不能因为"算不出来"而拦住导出；
4. 阈值 0.7 时，真实项目 18 字段里只有 16 个被支撑也必须能导出。
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.requirements import router
from app.core.database import get_db
from app.models import (
    AuditLog,
    Institution,
    ProductScenario,
    Project,
    ProjectMembership,
    Requirement,
    TargetField,
    TargetTable,
    User,
)
from app.services.auth.dependencies import Principal, get_current_principal
from app.services.auth.resource_guard import guard_project_resource
from app.services.requirement_scope import ScopeInput


def _summary(*, coverage: float, per_field: list[dict]) -> dict:
    return {
        "coverage": {"all_fields": coverage, "fields_with_candidate": coverage},
        "per_field": per_field,
    }


def test_quality_gate_marks_unsupported_fields_without_blocking():
    from app.services.requirement_grounding import quality_gate

    summary = _summary(coverage=0.5, per_field=[
        {"field_code": "E010001", "ai_draft_only": False, "supported": 2,
         "sections": {"business": {"has_candidate": True}, "lineage": {"has_candidate": True}}},
        {"field_code": "SFJJGDM", "ai_draft_only": True, "supported": 0,
         "sections": {"business": {"has_candidate": False}, "lineage": {"has_candidate": False}}},
    ])
    gate = quality_gate(summary)

    assert gate["mode"] == "mark"
    assert gate["verdict"] == "mark"
    assert gate["coverage_all_fields"] == 0.5
    assert gate["fields_without_support"] == ["SFJJGDM"]
    assert gate["ai_draft_fields"] == ["SFJJGDM"]
    # 阈值未过 + 只有 AI 草稿 + 没有采纳候选 = 三条原因，逐条可读。
    assert len(gate["reasons"]) == 3
    assert "50%" in gate["reasons"][0]
    assert "AI 草稿" in gate["reasons"][1]
    assert "还没有采纳候选" in gate["reasons"][2]


def test_quality_gate_passes_when_every_field_is_supported():
    from app.services.requirement_grounding import quality_gate

    summary = _summary(coverage=1.0, per_field=[
        {"field_code": "E010001", "ai_draft_only": False, "supported": 3,
         "sections": {"business": {"has_candidate": True}, "lineage": {"has_candidate": True}}},
    ])
    gate = quality_gate(summary)

    assert gate["verdict"] == "pass"
    assert gate["reasons"] == []
    assert gate["threshold"] == 0.7


def test_quality_gate_reports_unknown_instead_of_raising():
    from app.services.requirement_grounding import quality_gate

    gate = quality_gate(None)
    assert gate["verdict"] == "unknown"
    assert gate["reasons"] and "无法统计" in gate["reasons"][0]


def test_gate_headers_are_short_and_machine_readable():
    from app.services.requirement_grounding import gate_headers

    headers = gate_headers({"verdict": "mark", "coverage_all_fields": 0.888888,
                            "reasons": ["a", "b"]})
    assert headers == {
        "X-Requirement-Quality-Gate": "mark",
        "X-Requirement-Grounding-Coverage": "0.8889",
        "X-Requirement-Grounding-Reason-Count": "2",
    }
    assert gate_headers({"verdict": "unknown", "coverage_all_fields": None, "reasons": []})[
        "X-Requirement-Grounding-Coverage"] == "unknown"


@pytest.fixture()
def gate_api(db_session):
    institution = Institution(institution_code="GATE", institution_name="Gate Bank")
    user = User(username="gate-user", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="门禁项目", institution_id=institution.id)
    db_session.add(project)
    db_session.flush()
    membership = ProjectMembership(project_id=project.id, user_id=user.id,
                                   project_role="project_manager", status="active")
    target_table = TargetTable(project_id=project.id, table_code="T_GATE", table_name="门禁表")
    db_session.add_all([membership, target_table])
    db_session.flush()
    field = TargetField(project_id=project.id, target_table_id=target_table.id,
                        field_code="E010001", field_name="产品ID")
    scenario = ProductScenario(project_id=project.id, scenario_code="GATE", scenario_name="门禁场景")
    db_session.add_all([field, scenario])
    db_session.flush()
    payload = ScopeInput(name="门禁需求", target_table_id=target_table.id, field_ids=[field.id],
                         scenario_id=scenario.id, background="只有软门禁，不阻断导出")
    requirement = Requirement(project_id=project.id, name=payload.name, version=1,
                              scope_json=payload.model_dump(mode="json", exclude={"expected_version", "name"}))
    db_session.add(requirement)
    db_session.flush()

    app = FastAPI()
    app.include_router(router, dependencies=[Depends(guard_project_resource)])
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_principal] = lambda: Principal(user.id, user.username, None)
    with TestClient(app) as client:
        yield client, db_session, project, requirement


def test_freeze_and_export_attaches_gate_headers_and_audit(gate_api):
    client, db, project, requirement = gate_api
    base = f"/projects/{project.id}/requirements/{requirement.id}"
    preview = client.get(base + "/document").json()

    response = client.post(base + "/freeze-and-export", data={
        "format": "xlsx", "layout": "standard",
        "expected_version": str(requirement.version), "expected_hash": preview["content_hash"],
    })

    assert response.status_code == 200, response.text
    verdict = response.headers.get("x-requirement-quality-gate")
    assert verdict in {"pass", "mark", "unknown"}
    coverage = response.headers.get("x-requirement-grounding-coverage")
    assert coverage == "unknown" or 0.0 <= float(coverage) <= 1.0
    reasons = response.headers.get("x-requirement-grounding-reason-count")
    assert reasons is not None and int(reasons) >= 0

    audits = db.scalars(
        select(AuditLog).where(AuditLog.action == "export_requirement_document")
        .order_by(AuditLog.id.desc())
    ).all()
    assert audits
    gate = (audits[0].after_summary_json or {}).get("quality_gate") or {}
    assert gate.get("mode") == "mark"
    assert gate.get("verdict") == verdict
    assert isinstance(gate.get("reasons"), list)


def test_gate_computes_from_frozen_snapshot_content(gate_api):
    """统一导出端点按"导出用的那份冻结内容"算门禁，这里直接验服务函数。

    走 HTTP 会受测试用 ``sqlite:///:memory:`` 每条连接一个库的限制（快照查询落到新连接
    就 `no such table`），所以冻结这一层单独验证；路由层的接线由 freeze-and-export 用例覆盖。
    """

    from app.api.requirements import _quality_gate_for_frozen_source
    from app.services.requirement_delivery import freeze_draft
    from app.services.requirement_grounding import gate_headers

    client, db, project, requirement = gate_api
    base = f"/projects/{project.id}/requirements/{requirement.id}"
    preview = client.get(base + "/document").json()
    actor_id = db.scalar(select(User.id).where(User.username == "gate-user"))

    snapshot, created = freeze_draft(db, project.id, requirement.id, requirement.version,
                                     preview["content_hash"], actor_id)
    assert created is True

    gate = _quality_gate_for_frozen_source(db, project.id, requirement.id, None, snapshot.id)
    assert gate["mode"] == "mark"
    assert gate["verdict"] in {"pass", "mark", "unknown"}
    assert "reasons" in gate and isinstance(gate["reasons"], list)
    # 种子需求只有一个字段、没有采纳候选 → 必须是 mark 且原因可读，绝不抛 4xx。
    assert gate["verdict"] == "mark"
    assert gate["fields_without_candidate"] == ["E010001"]

    headers = gate_headers(gate)
    assert headers["X-Requirement-Quality-Gate"] == "mark"
    assert headers["X-Requirement-Grounding-Reason-Count"] == str(len(gate["reasons"]))
