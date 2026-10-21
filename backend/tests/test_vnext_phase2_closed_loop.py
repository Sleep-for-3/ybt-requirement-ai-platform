"""阶段2 最小闭环（Lead 本轮新增）：需求 → 待确认 → 快照 → 三级审批 → 正式交付 → 修订留痕。

任务书阶段2 要求：至少一个完整案例从需求输入到可审核文档交付且证据可回溯，
并覆盖「不确定时提待确认问题而非自定口径」「正式交付后修订不覆盖历史版本」。

本测试把既有分散覆盖串成一条链路（全部走 HTTP API，SQLite + TestClient）：
1. 需求已录入（scope_fixture 提供项目/目标字段/需求），业务提出待确认问题；
2. 冻结内容版本（POST /revisions）→ 待确认问题进入 content_json.gaps；
3. review-readiness 因 manual:<id> 阻断，提交审核返回 409（AI 不能绕过人工门控）；
4. 人工回答 + 结案 → 实时文档不再出现该问题；
5. 采纳完整候选内容（模拟 generation adopt 后的内容）→ readiness 通过；
6. 提交三级审核 → 审批前 finalize 409 → 三级通过 → finalize 201；
7. 导出 xlsx/docx，断言正文含已确认口径与快照哈希头；
8. 对已确认版本发起修订 → 新版本 draft、历史版本与已冻结交付不变。

标签：TESTED_MOCK（SQLite/TestClient/Mock，无真实模型与真实审批系统）。
"""

from __future__ import annotations

from copy import deepcopy
from io import BytesIO

import pytest
from docx import Document as DocxDocument
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select

from app.api import deliverables, requirements
from app.core.database import get_db
from app.models import ProjectMembership, RequirementFormalDelivery, ReviewTask, User
from app.services.auth.dependencies import Principal, get_current_principal
from app.services.auth.resource_guard import guard_project_resource
from app.services.governance.workflow import decide_task
from app.services.requirement_revisions import load_revision
from app.services.requirement_scope import content_digest
from app.services.storage import get_storage_service
from test_requirement_draft_snapshots import fixture as draft_fixture
from test_requirement_formal_delivery import _reviewers
from test_requirement_snapshot_api import snapshot_db  # noqa: F401  隔离 SQLite 夹具


@pytest.fixture()
def closed_loop_client(snapshot_db, tmp_path, monkeypatch):
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


def _adopt_complete_content(db, revision, field) -> None:
    """模拟 generation adopt：把人工确认过的完整候选写进内容版本（不改历史版本）。"""
    content = deepcopy(revision.content_json)
    record = content["fields"][0]
    record["business"] = {
        **(record.get("business") or {}),
        "business_definition": "监管客户唯一标识",
        "final_content": "按产品ID+期限唯一确定有效产品记录后形成客户编号。",
    }
    record["lineage"] = {
        **(record.get("lineage") or {}),
        "source_system_name": "客户主数据系统",
        "source_table_english_name": "ODS_CUSTOMER",
        "source_field_english_name": "CUSTOMER_ID",
        "processing_logic": "关联有效客户后直接映射；空值阻断报送。",
    }
    record["mart_mappings"] = [{
        "id": 301, "mart_field_id": 201, "mapping_status": "draft",
        "join_condition": "M.CUSTOMER_ID = C.CUSTOMER_ID",
        "filter_condition": "C.STATUS = 'ACTIVE'",
        "null_handling_rule": "CUSTOMER_ID IS NULL 时阻断",
    }]
    record["source_mappings"] = {"201": [{
        "id": 101, "mapping_status": "draft",
        "join_condition": "M.CUSTOMER_ID = C.CUSTOMER_ID",
        "filter_condition": "C.STATUS = 'ACTIVE'",
    }]}
    record["evidence"] = [{
        "source_name": "隔离合成字段字典",
        "location_text": "客户主键定义第 2 行",
        "quoted_content": "CUSTOMER_ID 为有效客户唯一标识",
    }]
    content["gaps"] = []
    content["assessment"] = "clear"
    if not content.get("lineage_graph") or not content["lineage_graph"].get("edges"):
        content["lineage_graph"] = {
            "nodes": [], "tables": [],
            "edges": [{"id": "synthetic:101", "source_node_id": "asset:source_field:101",
                       "target_node_id": f"asset:target_field:{field.id}"}],
            "root_ids": [f"asset:target_field:{field.id}"], "truncated": False,
        }
    revision.content_json = content
    revision.content_hash = content_digest(content)
    db.commit()


def test_requirement_closed_loop_blocks_until_manual_question_closed(closed_loop_client):
    client, db, project, field, requirement = closed_loop_client
    base = f"/projects/{project.id}/requirements/{requirement.id}"

    # 1) 业务提出待确认问题：产品ID因期限/方案重复，报送唯一性规则待人工确认
    asked = client.post(f"/projects/{project.id}/questions", json={
        "target_table_id": field.target_table_id,
        "target_field_id": field.id,
        "question_type": "uniqueness",
        "question_text": "产品ID因期限/方案存在重复，请确认报送唯一性规则",
        "priority": "high",
        "assigned_role": "business",
    })
    assert asked.status_code == 201, asked.text
    question_id = asked.json()["id"]

    # 2) 冻结内容版本：未解决的人工问题必须进入快照 gaps（而不是被静默忽略）
    assert client.post(base + "/revisions", json={"expected_version": 1}).status_code == 201
    revision = load_revision(db, project.id, requirement.id, 1)
    assert revision.content_json["gaps"], "冻结内容必须包含未解决的人工问题"
    assert f"manual:{question_id}" in {gap["id"] for gap in revision.content_json["gaps"]}

    # 3) 阻断：readiness 不可用、提交审核 409（AI 不能绕过人工确认）
    readiness = client.get(base + "/review-readiness", params={"content_version": 1})
    assert readiness.status_code == 200, readiness.text
    assert readiness.json()["eligible"] is False
    assert f"manual:{question_id}" in {reason["code"] for reason in readiness.json()["reasons"]}
    blocked_submit = client.post(base + "/review-submissions", json={
        "expected_content_version": 1,
        "expected_content_hash": revision.content_hash,
        "assignments": {},
    })
    assert blocked_submit.status_code == 409

    # 4) 人工回答并结案，同时采纳完整候选内容（模拟 generation adopt）
    answered = client.post(f"/questions/{question_id}/answer", json={
        "resolution_text": "按产品ID+期限确定唯一有效产品记录，不拼接字段破坏外部引用",
    })
    assert answered.status_code == 200, answered.text
    assert client.post(f"/questions/{question_id}/close").status_code == 200
    listed = client.get(f"/projects/{project.id}/questions", params={"target_field_id": field.id})
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["question_status"] == "closed"
    # 冻结快照不会因结案自动清除 gap（快照即权威）；真实链路靠重新生成/采纳已确认内容刷新。
    _adopt_complete_content(db, revision, field)

    # 5) 内容完整后 readiness 通过
    ready = client.get(base + "/review-readiness", params={"content_version": 1})
    assert ready.status_code == 200, ready.text
    assert ready.json()["eligible"] is True, ready.json()
    revision = load_revision(db, project.id, requirement.id, 1)

    # 6) 三级审核：审批前不能定稿
    reviewers = _reviewers(db, project.id)
    submitted = client.post(base + "/review-submissions", json={
        "expected_content_version": 1,
        "expected_content_hash": revision.content_hash,
        "assignments": {role: user.id for role, user in reviewers.items()},
    })
    assert submitted.status_code == 201, submitted.text
    submission_id = submitted.json()["id"]
    assert client.post(base + f"/review-submissions/{submission_id}/finalize").status_code == 409

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

    # 7) 正式交付：xlsx 与 docx 都带快照哈希，正文含已确认口径
    finalized = client.post(base + f"/review-submissions/{submission_id}/finalize")
    assert finalized.status_code == 201, finalized.text
    delivery_id = finalized.json()["id"]
    frozen_hash = revision.content_hash
    delivery_row = db.get(RequirementFormalDelivery, delivery_id)
    again_finalize = client.post(base + f"/review-submissions/{submission_id}/finalize")
    assert again_finalize.status_code == 201
    assert again_finalize.json()["id"] == delivery_id
    assert again_finalize.json()["deduplicated"] is True
    assert delivery_row.content_hash == frozen_hash          # 交付固定的是审核通过的那一版内容
    assert delivery_row.content_json["formal_delivery"]["content_version"] == 1
    assert delivery_row.content_json["formal_delivery"]["version_no"] == 1
    snapshot_hash = delivery_row.snapshot_hash               # 交付快照 = 内容 + 审批记录

    xlsx = client.get(base + f"/formal-deliveries/{delivery_id}/export", params={"format": "xlsx"})
    assert xlsx.status_code == 200, xlsx.text
    assert xlsx.headers["X-Requirement-Snapshot-Hash"] == snapshot_hash
    book = load_workbook(BytesIO(xlsx.content))
    assert "正式交付" in book["需求范围"]["B2"].value

    docx = client.get(base + f"/formal-deliveries/{delivery_id}/export", params={"format": "docx"})
    assert docx.status_code == 200, docx.text
    assert docx.headers["X-Requirement-Snapshot-Hash"] == snapshot_hash
    text = "\n".join(p.text for p in DocxDocument(BytesIO(docx.content)).paragraphs)
    assert "监管客户唯一标识" in text
    assert "按产品ID+期限唯一确定有效产品记录后形成客户编号。" in text

    # 8) 修订留痕：对已确认版本发起修订 → 新版本 draft，历史版本与交付文件不变
    frozen_content = deepcopy(load_revision(db, project.id, requirement.id, 1).content_json)
    revised = client.post(base + "/revisions/1/revise", json={
        "expected_content_version": 1, "reason": "监管口径补充说明",
    })
    assert revised.status_code == 201, revised.text
    new_revision = load_revision(db, project.id, requirement.id, 2)
    assert new_revision.status == "draft"
    assert load_revision(db, project.id, requirement.id, 1).content_json == frozen_content
    again = client.get(base + f"/formal-deliveries/{delivery_id}/export", params={"format": "xlsx"})
    assert again.headers["X-Requirement-Snapshot-Hash"] == snapshot_hash
    assert again.content == xlsx.content
