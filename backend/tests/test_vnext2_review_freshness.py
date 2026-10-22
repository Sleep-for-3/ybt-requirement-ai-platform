"""VNext2 P0-A 回归：冻结快照之后新增的人工待确认问题必须继续阻断送审/审批/正式交付。

缺陷（改前可复现）：`review_readiness` 只检查冻结的 `RequirementRevision.content_json`
里的 gaps。快照建立时没有问题 → 快照 gaps 为空；之后业务新增 PendingQuestion 时，
旧快照仍被判为可送审、可审批、可正式交付。`finalize_formal_delivery` 更是只有
脚本依据/口径比较/路径检查，完全没有当前风险检查。

设计：冻结快照保持不可变（历史事实层），另加“当前交付安全检查层”，在
review-readiness / submit-for-review / 审批结论 / finalize-formal-delivery 四个节点
查当前库中作用于同一项目+目标表(+字段/场景)的未解决人工问题。

本文件为 TESTED_MOCK（SQLite/TestClient/Mock 模型，无真实库与真实审批人）。
并发串行化证据见 tests/test_vnext2_review_freshness_pg.py（真实 PostgreSQL）。
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import deliverables, requirements
from app.core.database import get_db
from app.models import (
    PendingQuestion,
    ProjectMembership,
    Requirement,
    ReviewTask,
    TargetTable,
    User,
)
from app.services.auth.dependencies import Principal, get_current_principal
from app.services.auth.resource_guard import guard_project_resource
from app.services.governance.workflow import decide_task
from app.services.requirement_revisions import load_revision
from app.services.storage import get_storage_service
from test_requirement_draft_snapshots import fixture as draft_fixture
from test_requirement_formal_delivery import _reviewers
from test_requirement_snapshot_api import snapshot_db  # noqa: F401  隔离 SQLite 夹具
from test_vnext_phase2_closed_loop import _adopt_complete_content


@pytest.fixture()
def fresh_client(snapshot_db, tmp_path, monkeypatch):
    from app.core.settings import get_settings

    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    get_storage_service.cache_clear()
    get_settings.cache_clear()
    db = snapshot_db
    project, field, requirement, _content = draft_fixture(db)
    user = db.scalar(select(User))
    db.add(ProjectMembership(project_id=project.id, user_id=user.id,
                             project_role="project_manager", status="active"))
    db.flush()
    app = FastAPI()
    app.include_router(requirements.router, dependencies=[Depends(guard_project_resource)])
    app.include_router(deliverables.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_principal] = lambda: Principal(user.id, user.username, None)
    with TestClient(app) as client:
        yield client, db, project, field, requirement
    get_storage_service.cache_clear()
    get_settings.cache_clear()


def _freeze_complete_revision(client, db, project, requirement, field):
    """冻结内容版本 1，并补齐为“可审核”的完整内容（模拟已 adopt 的完整候选）。"""
    base = f"/projects/{project.id}/requirements/{requirement.id}"
    frozen = client.post(base + "/revisions", json={"expected_version": requirement.version})
    assert frozen.status_code == 201, frozen.text
    revision = load_revision(db, project.id, requirement.id, 1)
    _adopt_complete_content(db, revision, field)
    ready = client.get(base + "/review-readiness", params={"content_version": 1})
    assert ready.status_code == 200, ready.text
    assert ready.json()["eligible"] is True, ready.json()
    return revision


def _ask(client, project, field, text, **overrides):
    payload = {
        "target_table_id": field.target_table_id,
        "target_field_id": field.id,
        "question_type": "uniqueness",
        "question_text": text,
        "priority": "high",
        "assigned_role": "business",
        **overrides,
    }
    response = client.post(f"/projects/{project.id}/questions", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _readiness(client, project, requirement):
    response = client.get(
        f"/projects/{project.id}/requirements/{requirement.id}/review-readiness",
        params={"content_version": 1},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _submit(client, db, project, requirement, revision):
    return client.post(
        f"/projects/{project.id}/requirements/{requirement.id}/review-submissions",
        json={
            "expected_content_version": 1,
            "expected_content_hash": revision.content_hash,
            "assignments": {},
        },
    )


def test_question_created_after_freeze_blocks_readiness_and_submission(fresh_client):
    client, db, project, field, requirement = fresh_client
    revision = _freeze_complete_revision(client, db, project, requirement, field)
    assert _readiness(client, project, requirement)["eligible"] is True

    # 快照建立之后业务才提出关键问题（例如产品ID+期限唯一性依据不明）
    question = _ask(client, project, field, "产品ID因期限/方案存在重复，请确认报送唯一性规则")

    readiness = _readiness(client, project, requirement)
    assert readiness["eligible"] is False, "冻结后新增的关键问题必须阻断送审"
    assert f"manual:{question['id']}" in {reason["code"] for reason in readiness["reasons"]}
    blocked = _submit(client, db, project, requirement, revision)
    assert blocked.status_code == 409, "冻结快照不得绕过新增问题继续送审"


def test_answered_but_unclosed_question_after_freeze_still_blocks(fresh_client):
    client, db, project, field, requirement = fresh_client
    _freeze_complete_revision(client, db, project, requirement, field)
    question = _ask(client, project, field, "过滤条件是否包含已注销客户？")
    answered = client.post(f"/questions/{question['id']}/answer",
                           json={"resolution_text": "已注销客户不纳入报送范围"})
    assert answered.status_code == 200, answered.text
    assert _readiness(client, project, requirement)["eligible"] is False


def test_accepted_question_after_freeze_still_blocks(fresh_client):
    client, db, project, field, requirement = fresh_client
    _freeze_complete_revision(client, db, project, requirement, field)
    question = _ask(client, project, field, "口径是否包含跨行理财？")
    assert client.post(f"/questions/{question['id']}/accept").status_code == 200
    assert _readiness(client, project, requirement)["eligible"] is False


def test_closed_question_without_resolution_after_freeze_still_blocks(fresh_client):
    client, db, project, field, requirement = fresh_client
    _freeze_complete_revision(client, db, project, requirement, field)
    question = _ask(client, project, field, "金额单位是元还是万元？")
    assert client.post(f"/questions/{question['id']}/close").status_code == 200
    readiness = _readiness(client, project, requirement)
    assert readiness["eligible"] is False, "结案但缺少解决依据仍应阻断"
    reason = next(item for item in readiness["reasons"] if item["code"] == f"manual:{question['id']}")
    assert "缺少解决依据" in reason["message"]


def test_closed_question_with_resolution_after_freeze_unblocks(fresh_client):
    client, db, project, field, requirement = fresh_client
    revision = _freeze_complete_revision(client, db, project, requirement, field)
    question = _ask(client, project, field, "金额单位是元还是万元？")
    assert client.post(f"/questions/{question['id']}/answer",
                       json={"resolution_text": "按合成制度要求以元为单位报送"}).status_code == 200
    assert client.post(f"/questions/{question['id']}/close").status_code == 200
    readiness = _readiness(client, project, requirement)
    assert readiness["eligible"] is True, readiness
    assert _submit(client, db, project, requirement, revision).status_code == 201


def test_unrelated_table_or_field_question_does_not_block(fresh_client):
    """无关目标表/无关字段/无关场景的问题不得误阻断本需求（场景 G）。"""
    client, db, project, field, requirement = fresh_client
    _freeze_complete_revision(client, db, project, requirement, field)
    other_table = TargetTable(project_id=project.id, table_code="YBT_OTHER", table_name="无关目标表")
    db.add(other_table)
    db.flush()
    db.add(PendingQuestion(
        institution_id=None, project_id=project.id, target_table_id=other_table.id,
        target_field_id=None, scenario_id=None, question_type="other",
        question_text="无关目标表的字段口径待确认", question_status="open", priority="high",
    ))
    # 同一项目、同一目标表，但属于需求范围之外的字段（需求只绑定了一个字段）
    db.add(PendingQuestion(
        institution_id=None, project_id=project.id, target_table_id=field.target_table_id,
        target_field_id=None, scenario_id=field.target_table_id + 100000,
        question_type="other", question_text="其他场景的统计时点待确认",
        question_status="open", priority="high",
    ))
    db.commit()
    readiness = _readiness(client, project, requirement)
    assert readiness["eligible"] is True, f"无关问题误阻断：{readiness['reasons']}"


def test_new_question_blocks_remaining_review_approval(fresh_client):
    """审核过程中出现新风险：后续审批必须转保守（场景 H）。"""
    client, db, project, field, requirement = fresh_client
    revision = _freeze_complete_revision(client, db, project, requirement, field)
    reviewers = _reviewers(db, project.id)
    submitted = client.post(
        f"/projects/{project.id}/requirements/{requirement.id}/review-submissions",
        json={
            "expected_content_version": 1,
            "expected_content_hash": revision.content_hash,
            "assignments": {role: user.id for role, user in reviewers.items()},
        },
    )
    assert submitted.status_code == 201, submitted.text
    submission_id = submitted.json()["id"]
    tasks = {task.step_key: task for task in db.scalars(select(ReviewTask).where(
        ReviewTask.target_type == "requirement_review_submission",
        ReviewTask.target_id == submission_id,
    ))}
    business = reviewers["business_reviewer"]
    decide_task(db, tasks["business_review"], Principal(business.id, business.username, None),
                "approved", "业务口径核验通过")
    db.commit()

    _ask(client, project, field, "审核中新增：是否存在跨期限产品方案？")

    technical = reviewers["technical_reviewer"]
    with pytest.raises(HTTPException) as error:
        decide_task(db, tasks["technical_review"], Principal(technical.id, technical.username, None),
                    "approved", "技术核验通过")
    assert error.value.status_code == 409


def test_question_after_final_approval_blocks_formal_delivery(fresh_client):
    """审批全部通过后、定稿前新增问题：finalize 必须再次检查（TOCTOU 的业务侧）。"""
    client, db, project, field, requirement = fresh_client
    revision = _freeze_complete_revision(client, db, project, requirement, field)
    reviewers = _reviewers(db, project.id)
    submitted = client.post(
        f"/projects/{project.id}/requirements/{requirement.id}/review-submissions",
        json={
            "expected_content_version": 1,
            "expected_content_hash": revision.content_hash,
            "assignments": {role: user.id for role, user in reviewers.items()},
        },
    )
    assert submitted.status_code == 201, submitted.text
    submission_id = submitted.json()["id"]
    tasks = {task.step_key: task for task in db.scalars(select(ReviewTask).where(
        ReviewTask.target_type == "requirement_review_submission",
        ReviewTask.target_id == submission_id,
    ))}
    for step, role in (("business_review", "business_reviewer"),
                       ("technical_review", "technical_reviewer"),
                       ("final_review", "final_reviewer")):
        user = reviewers[role]
        decide_task(db, tasks[step], Principal(user.id, user.username, None), "approved", "核验通过")
    db.commit()

    # 全部审核通过后才出现的新风险
    _ask(client, project, field, "定稿前新增：历史制度版本与当前制度适用范围冲突")

    finalized = client.post(
        f"/projects/{project.id}/requirements/{requirement.id}/review-submissions/{submission_id}/finalize")
    assert finalized.status_code == 409, "审核通过后新增的关键问题必须阻断正式交付"
    assert "待确认" in finalized.text or "阻断" in finalized.text or "依据" in finalized.text


def test_formal_delivery_immutable_after_later_question(fresh_client):
    """正式交付完成后新增问题：历史交付文件不被修改，且后续检查仍能看到该问题。"""
    client, db, project, field, requirement = fresh_client
    revision = _freeze_complete_revision(client, db, project, requirement, field)
    reviewers = _reviewers(db, project.id)
    submitted = client.post(
        f"/projects/{project.id}/requirements/{requirement.id}/review-submissions",
        json={
            "expected_content_version": 1,
            "expected_content_hash": revision.content_hash,
            "assignments": {role: user.id for role, user in reviewers.items()},
        },
    )
    assert submitted.status_code == 201, submitted.text
    submission_id = submitted.json()["id"]
    tasks = {task.step_key: task for task in db.scalars(select(ReviewTask).where(
        ReviewTask.target_type == "requirement_review_submission",
        ReviewTask.target_id == submission_id,
    ))}
    for step, role in (("business_review", "business_reviewer"),
                       ("technical_review", "technical_reviewer"),
                       ("final_review", "final_reviewer")):
        user = reviewers[role]
        decide_task(db, tasks[step], Principal(user.id, user.username, None), "approved", "核验通过")
    db.commit()
    finalized = client.post(
        f"/projects/{project.id}/requirements/{requirement.id}/review-submissions/{submission_id}/finalize")
    assert finalized.status_code == 201, finalized.text
    delivery_id = finalized.json()["id"]
    base = f"/projects/{project.id}/requirements/{requirement.id}"
    first_export = client.get(base + f"/formal-deliveries/{delivery_id}/export", params={"format": "xlsx"})
    assert first_export.status_code == 200

    _ask(client, project, field, "交付后新增：统计口径是否需要重算历史数据")

    # 历史交付文件与快照完全不变
    again = client.get(base + f"/formal-deliveries/{delivery_id}/export", params={"format": "xlsx"})
    assert again.status_code == 200
    assert again.content == first_export.content
    assert again.headers["X-Requirement-Snapshot-Hash"] == first_export.headers["X-Requirement-Snapshot-Hash"]
    # 但当前风险已在当前交付安全检查层可见（新修订/复核必须先解决）
    readiness = _readiness(client, project, requirement)
    assert readiness["eligible"] is False
