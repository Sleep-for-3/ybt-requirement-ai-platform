"""需求字段覆盖核对：这张监管表的字段，有多少进了本需求，没进的各是什么性质。

三条固定行为：
1. 进了范围 / 没进范围按 `scope_json.field_ids` 算，与正文写没写无关；
2. 没进范围的字段分三类：有集市映射（模板要求填）、只在脚本血缘里出现过、两者都没有；
3. 这个接口只读：不补字段、不改需求、不写任何库。
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.requirements import router
from app.core.database import Base, get_db
from app.services.auth.dependencies import Principal, get_current_principal
from app.models import (
    LineageNode,
    MartField,
    MartTable,
    MartToYbtMapping,
    Project,
    ProjectMembership,
    Requirement,
    TargetField,
    TargetTable,
    User,
)
from app.services.auth.resource_guard import guard_project_resource
from app.services.requirement_field_coverage import (
    COVERAGE_VERSION,
    CoverageError,
    build_field_coverage,
)


@pytest.fixture()
def coverage_db():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed(db: Session) -> dict:
    user = User(username="coverage-owner", password_hash="x", status="active")
    db.add(user)
    db.flush()
    project = Project(name="覆盖核对合成项目")
    db.add(project)
    db.flush()
    db.add(
        ProjectMembership(
            project_id=project.id, user_id=user.id, project_role="project_manager", status="active"
        )
    )
    table = TargetTable(
        project_id=project.id,
        table_code="T_9_9",
        table_name="覆盖核对合成表",
        reporting_domain_name="合成数据域",
    )
    db.add(table)
    db.flush()
    covered_a = TargetField(
        project_id=project.id, target_table_id=table.id, field_code="A001", field_name="在范围内甲"
    )
    covered_b = TargetField(
        project_id=project.id, target_table_id=table.id, field_code="A002", field_name="在范围内乙"
    )
    mapped = TargetField(
        project_id=project.id,
        target_table_id=table.id,
        field_code="A003",
        field_name="有集市映射但没进范围",
        required_flag=True,
    )
    script_only = TargetField(
        project_id=project.id, target_table_id=table.id, field_code="A004", field_name="只在脚本里"
    )
    unreferenced = TargetField(
        project_id=project.id, target_table_id=table.id, field_code="A005", field_name="都没有"
    )
    foreign = TargetField(
        project_id=project.id, target_table_id=table.id + 1, field_code="B001", field_name="别的表的字段"
    )
    db.add_all([covered_a, covered_b, mapped, script_only, unreferenced, foreign])
    db.flush()

    mart_table = MartTable(project_id=project.id, table_code="HYF_T_9_9", table_name="合成集市表")
    db.add(mart_table)
    db.flush()
    mart_field = MartField(
        project_id=project.id, mart_table_id=mart_table.id, field_code="A003", field_name="集市甲"
    )
    db.add(mart_field)
    db.flush()
    db.add(
        MartToYbtMapping(
            project_id=project.id,
            target_field_id=mapped.id,
            mart_field_id=mart_field.id,
            mapping_status="confirmed",
        )
    )
    db.add(
        LineageNode(
            project_id=project.id,
            node_type="target",
            logical_name=f"T_9_9.{script_only.field_code}",
            table_name="T_9_9",
            column_name=script_only.field_code,
            target_table_id=table.id,
            target_field_id=script_only.id,
        )
    )
    requirement = Requirement(
        project_id=project.id,
        name="覆盖核对合成需求",
        scope_json={
            "target_table_id": table.id,
            "field_ids": [covered_a.id, covered_b.id, foreign.id],
        },
    )
    db.add(requirement)
    db.flush()
    return {
        "user": user,
        "project": project,
        "table": table,
        "covered_a": covered_a,
        "covered_b": covered_b,
        "mapped": mapped,
        "script_only": script_only,
        "unreferenced": unreferenced,
        "foreign": foreign,
        "requirement": requirement,
    }


def test_coverage_splits_uncovered_fields_into_three_buckets(coverage_db):
    data = _seed(coverage_db)
    payload = build_field_coverage(coverage_db, data["project"].id, data["requirement"].id)

    assert payload["coverage_version"] == COVERAGE_VERSION
    assert payload["table"]["table_code"] == "T_9_9"
    counts = payload["counts"]
    assert counts["table_fields"] == 5
    assert counts["covered"] == 2
    assert counts["uncovered"] == 3
    assert counts["buckets"] == {"mapped": 1, "script_only": 1, "unreferenced": 1}
    # 范围内但不在本表的字段单独列出：可能是绑错表，也可能跨表，不能当成覆盖。
    assert [row["field_code"] for row in payload["outside_scope_fields"]] == ["B001"]
    assert counts["outside_scope"] == 1

    buckets = {row["field_code"]: row for row in payload["uncovered"]}
    assert buckets["A003"]["bucket"] == "mapped"
    assert buckets["A003"]["mapping_statuses"] == ["confirmed"]
    assert buckets["A003"]["required_flag"] is True
    assert buckets["A004"]["bucket"] == "script_only"
    assert buckets["A004"]["in_script_lineage"] is True
    assert buckets["A005"]["bucket"] == "unreferenced"
    assert buckets["A005"]["in_script_lineage"] is False
    assert "不改需求、不补字段" in payload["note"]
    # 只读：调用一次不会新增任何映射或血缘。
    assert len(coverage_db.scalars(select(MartToYbtMapping)).all()) == 1
    assert len(coverage_db.scalars(select(LineageNode)).all()) == 1


def test_coverage_sample_caps_rows_but_counts_stay_complete(coverage_db):
    data = _seed(coverage_db)
    payload = build_field_coverage(
        coverage_db, data["project"].id, data["requirement"].id, sample=1
    )
    assert len(payload["uncovered"]) == 1
    assert payload["counts"]["uncovered"] == 3
    assert sum(payload["counts"]["buckets"].values()) == 3


def test_coverage_without_bound_table_says_so(coverage_db):
    data = _seed(coverage_db)
    requirement = Requirement(project_id=data["project"].id, name="没绑表的需求", scope_json={})
    coverage_db.add(requirement)
    coverage_db.flush()
    payload = build_field_coverage(coverage_db, data["project"].id, requirement.id)
    assert payload["table"] is None
    assert payload["counts"]["table_fields"] == 0
    assert "没有绑定监管表" in payload["note"]


def test_coverage_rejects_unknown_or_foreign_requirement(coverage_db):
    data = _seed(coverage_db)
    with pytest.raises(CoverageError) as missing:
        build_field_coverage(coverage_db, data["project"].id, 999999)
    assert missing.value.code == "requirement_not_found"

    other = Project(name="别人的项目")
    coverage_db.add(other)
    coverage_db.flush()
    with pytest.raises(CoverageError):
        build_field_coverage(coverage_db, other.id, data["requirement"].id)


def test_http_endpoint_returns_coverage(coverage_db):
    data = _seed(coverage_db)
    app = FastAPI()
    app.include_router(router, dependencies=[Depends(guard_project_resource)])
    app.dependency_overrides[get_db] = lambda: coverage_db
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        data["user"].id, data["user"].username, None
    )
    with TestClient(app) as client:
        response = client.get(
            f"/projects/{data['project'].id}/requirements/{data['requirement'].id}/field-coverage"
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["counts"]["uncovered"] == 3
        assert payload["bucket_labels"]["mapped"] == "模板要求填，且有集市映射"
        missing = client.get(
            f"/projects/{data['project'].id}/requirements/999999/field-coverage"
        )
        assert missing.status_code == 404, missing.text
        assert missing.json()["detail"]["code"] == "requirement_not_found"
