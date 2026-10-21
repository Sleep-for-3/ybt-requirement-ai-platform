"""阶段2 验收：人工待确认问题必须阻断需求文档交付，且只有「结案且有解决依据」才解除。

背景（阶段0/2 审计缺口）：仓库中 `PendingQuestion`（人工待确认问题）此前没有任何
测试；而 `requirement_scope.document_content` 在 live facts 模式下会把未解决的人工
问题投影成 `manual:<id>` gap，`requirement_review.review_readiness` 再据此阻断送审。
这条「AI 不自定口径 → 提人工待确认 → 人工给出依据并结案 → 解除阻断」的链路是任务书
阶段2.1 的核心保护，必须有回归测试。

口径以仓库既有规格为准（tests/test_requirement_scope.py:54-58）：
- accepted（已接收待处理）仍阻断；
- closed/resolved 但**没有** resolution_text 仍阻断；
- resolved 且有 resolution_text 才解除；
- rejected 视为问题不成立，解除阻断（本测试不覆盖，避免与既有口径冲突时误判）。

本测试为 TESTED_MOCK（SQLite + TestClient + 无模型调用），不证明真实库/真实审批。
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import deliverables, requirements
from app.core.database import get_db
from app.models import ProjectMembership, User
from app.models.deliverables import PendingQuestion
from app.services.auth.dependencies import Principal, get_current_principal
from app.services.auth.resource_guard import guard_project_resource
from test_requirement_draft_snapshots import fixture as draft_fixture
from test_requirement_snapshot_api import snapshot_db  # noqa: F401  复用隔离 SQLite 夹具


@pytest.fixture()
def workspace(snapshot_db):
    db = snapshot_db
    project, field, requirement, _content = draft_fixture(db)
    user = db.scalar(select(User))
    membership = ProjectMembership(
        project_id=project.id, user_id=user.id, project_role="project_manager", status="active"
    )
    db.add(membership)
    db.flush()
    app = FastAPI()
    app.include_router(requirements.router, dependencies=[Depends(guard_project_resource)])
    app.include_router(deliverables.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_principal] = lambda: Principal(user.id, user.username, None)
    with TestClient(app) as client:
        yield client, db, project, field, requirement


def _ask(client, project_id: int, table_id: int, field_id: int, text: str) -> dict:
    response = client.post(
        f"/projects/{project_id}/questions",
        json={
            "target_table_id": table_id,
            "target_field_id": field_id,
            "question_type": "uniqueness",
            "question_text": text,
            "priority": "high",
            "assigned_role": "business",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _manual_gaps(client, project_id: int, requirement_id: int) -> list[dict]:
    response = client.get(f"/projects/{project_id}/requirements/{requirement_id}/document")
    assert response.status_code == 200, response.text
    return [gap for gap in response.json()["gaps"] if gap.get("origin") == "manual"]


def test_pending_question_blocks_document_until_closed_with_evidence(workspace) -> None:
    client, db_session, project, field, requirement = workspace
    question = _ask(
        client,
        project.id,
        field.target_table_id,
        field.id,
        "产品ID因期限/方案存在重复，请确认报送唯一性规则",
    )
    assert question["question_status"] in {"open", "assigned"}

    gaps = _manual_gaps(client, project.id, requirement.id)
    assert gaps, "未解决的人工待确认问题必须投影为 manual gap"
    assert gaps[0]["id"] == f"manual:{question['id']}"
    assert gaps[0]["status"] in {"open", "assigned"}

    # 1) 回答给出解决依据，但状态是 answered，仍应阻断（人工结案前不得解锁）
    answered = client.post(
        f"/questions/{question['id']}/answer",
        json={"resolution_text": "按产品ID+期限唯一确定，产品代码沿用监管码值"},
    )
    assert answered.status_code == 200, answered.text
    row = db_session.get(PendingQuestion, question["id"])
    db_session.refresh(row)
    assert row.resolution_text
    assert _manual_gaps(client, project.id, requirement.id), "回答但未结案仍应阻断"

    # 2) accept = 已接收待处理，按仓库既有规格仍阻断
    accepted = client.post(f"/questions/{question['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    assert _manual_gaps(client, project.id, requirement.id), "accepted 表示待处理，不应解锁"

    # 3) 结案（closed）且已有解决依据 → 解除阻断
    closed = client.post(f"/questions/{question['id']}/close")
    assert closed.status_code == 200, closed.text
    assert _manual_gaps(client, project.id, requirement.id) == [], "结案且有依据应解除阻断"


def test_closed_question_without_resolution_still_blocks(workspace) -> None:
    client, _db, project, field, requirement = workspace
    question = _ask(
        client,
        project.id,
        field.target_table_id,
        field.id,
        "过滤条件是否包含已注销客户？",
    )
    # 直接关闭但从未给出解决依据：按规格仍阻断，提示"缺少解决依据"
    closed = client.post(f"/questions/{question['id']}/close")
    assert closed.status_code == 200, closed.text
    gaps = _manual_gaps(client, project.id, requirement.id)
    assert gaps, "无解决依据的结案问题仍应阻断"
    assert "缺少解决依据" in gaps[0]["message"]
