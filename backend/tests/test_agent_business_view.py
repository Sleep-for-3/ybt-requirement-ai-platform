"""业务化改版的接口层单元测试。

覆盖三件事：
* 列表行的业务字段（业务对象、一句话结论、待办归属）稳定且不含技术字段；
* 详情里的技术诊断必须由服务端单独授权，不能只靠前端隐藏；
* 老数据（无产物、无 summary、无 review 任务）不会抛错，也不会露出空字符串。
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import app.models as _models  # noqa: F401  - populates Base.metadata
from app.api.agent import (
    _business_object,
    _clean_object_name,
    _pending_action,
    _result_brief,
    _task_row,
    get_agent_task_diagnostics,
)
from app.models import (
    AgentArtifact,
    AgentStep,
    AgentTask,
    Institution,
    Project,
    ProjectMembership,
    ReviewTask,
    User,
)
from app.services.auth.dependencies import Principal
from app.services.auth.permission_service import PermissionService


@pytest.fixture()
def scope(db_session):
    institution = Institution(
        institution_code="biz-bank", institution_name="业务银行", institution_type="bank", status="active",
    )
    manager = User(username="biz_manager", display_name="项目负责人", status="active")
    analyst = User(username="biz_analyst", display_name="业务分析员", status="active")
    db_session.add_all([institution, manager, analyst])
    db_session.flush()
    project = Project(
        name="业务化改版项目", institution_id=institution.id, project_status="active",
        bank_name="业务银行", description="列表与详情业务化",
    )
    db_session.add(project)
    db_session.flush()
    db_session.add_all([
        ProjectMembership(project_id=project.id, user_id=manager.id, project_role="project_manager", status="active"),
        ProjectMembership(project_id=project.id, user_id=analyst.id, project_role="business_analyst", status="active"),
    ])
    db_session.commit()
    return {
        "db": db_session,
        "project": project,
        "manager": Principal(manager.id, manager.username, manager.display_name),
        "analyst": Principal(analyst.id, analyst.username, analyst.display_name),
    }


def _task(db, project, **overrides) -> AgentTask:
    task = AgentTask(
        project_id=project.id,
        objective=overrides.pop("objective", "互联网贷款协议表都有哪些主要字段？"),
        status=overrides.pop("status", "completed"),
        scenario_key=overrides.pop("scenario_key", "knowledge_question"),
        created_by=overrides.pop("created_by", 1),
        **overrides,
    )
    db.add(task)
    db.commit()
    return task


def _artifact(db, task, artifact_type="knowledge_answer", status="confirmed", summary=None) -> AgentArtifact:
    artifact = AgentArtifact(
        task_id=task.id, artifact_type=artifact_type, title="问答：字段清单", status=status,
        summary_json=summary or {},
    )
    db.add(artifact)
    db.commit()
    return artifact


def test_clean_object_name_strips_verbs_and_rejects_noise():
    assert _clean_object_name("生成互联网贷款合作机构信息表") == "互联网贷款合作机构信息表"
    assert _clean_object_name("分析 hyf_ln_pa_online_info") == "hyf_ln_pa_online_info"
    # 带“字段/清单/变更”等词的短语不是表名，宁可返回 None 交给前端兜底。
    assert _clean_object_name("生成字段变更影响分析说明表") is None
    assert _clean_object_name("") is None


def test_business_object_prefers_real_artifact_subject_then_objective(scope):
    db, project = scope["db"], scope["project"]
    task = _task(db, project, objective="分析 hyf_ln_pa_online_info 字段变更对下游报表的影响")
    assert _business_object(task, []) == "hyf_ln_pa_online_info"

    chinese = _task(db, project, objective="生成互联网贷款合作机构信息表的字段口径说明草稿")
    assert _business_object(chinese, []) == "互联网贷款合作机构信息表"

    # 产物里真实命中的表名优先于目标描述里的猜测。
    artifact = _artifact(db, task, summary={"catalog_tables": ["hyf_ln_pa_agreement_info"]})
    assert _business_object(task, [artifact]) == "hyf_ln_pa_agreement_info"

    unknown = _task(db, project, objective="导出全部字段清单到 Excel")
    assert _business_object(unknown, []) is None


def test_result_brief_covers_every_business_state(scope):
    db, project = scope["db"], scope["project"]

    running = _task(db, project, status="running")
    assert _result_brief(running, [])["kind"] == "running"

    failed = _task(db, project, status="failed", error_code="timeout")
    brief = _result_brief(failed, [])
    assert brief["kind"] == "failed"
    assert "timeout" not in brief["headline"]

    cancelled = _task(db, project, status="cancelled")
    assert _result_brief(cancelled, [])["kind"] == "cancelled"

    waiting = _task(db, project, status="waiting_human")
    assert _result_brief(waiting, [])["kind"] == "waiting"

    no_result = _task(db, project, status="completed")
    assert _result_brief(no_result, []) == {
        "kind": "none", "headline": "任务已结束，暂无可展示结果。", "artifact_id": None,
    }

    answer = _task(db, project, status="completed")
    artifact = _artifact(db, answer, summary={"answer": "该表包含 4 个字段。", "answer_status": "grounded"})
    brief = _result_brief(answer, [artifact])
    assert brief["kind"] == "answer"
    assert brief["headline"] == "该表包含 4 个字段。"
    assert brief["artifact_id"] == artifact.id
    assert brief["artifact_status"] == "confirmed"

    draft = _task(db, project, status="completed")
    pending = _artifact(db, draft, artifact_type="requirement_document", status="pending_review",
                        summary={"title": "字段口径说明草稿"})
    assert _result_brief(draft, [pending])["kind"] == "draft"
    assert _result_brief(draft, [pending])["artifact_status"] == "pending_review"


def _plan(db, task):
    """AgentStep.plan_id 非空，测试里给每个任务配一份最小计划。"""
    from app.models import AgentPlan

    plan = AgentPlan(
        task_id=task.id, version_no=task.plan_version or 1, objective=task.objective or "",
        created_by=task.created_by, steps_json=[],
    )
    db.add(plan)
    db.flush()
    return plan


def test_pending_action_only_for_waiting_tasks_and_marks_owner(scope):
    db, project = scope["db"], scope["project"]
    task = _task(db, project, status="waiting_human")
    plan = _plan(db, task)
    step = AgentStep(
        task_id=task.id, plan_id=plan.id, step_key="clarify_subject", tool_key="clarify_subject",
        status="waiting_human", order_index=1, human_gate_key="clarify_subject",
        input_json={"required_permission": "final.review"},
        output_summary_json={"title": "确认分析对象"},
    )
    db.add(step)
    db.commit()

    manager_permissions = PermissionService(db, scope["manager"]).effective_project_permissions(project.id)
    analyst_permissions = PermissionService(db, scope["analyst"]).effective_project_permissions(project.id)

    mine = _pending_action(db, task, scope["manager"], manager_permissions, "project_manager")
    assert mine["mine"] is True
    assert mine["title"] == "确认分析对象"
    assert mine["step_key"] == "clarify_subject"

    theirs = _pending_action(db, task, scope["analyst"], analyst_permissions, "business_analyst")
    assert theirs["mine"] is False

    # 没有等待步骤时不应凭空造一个待办。
    completed = _task(db, project, status="completed")
    assert _pending_action(db, completed, scope["manager"], manager_permissions, "project_manager") is None


def test_pending_action_uses_review_assignee(scope):
    db, project = scope["db"], scope["project"]
    task = _task(db, project, status="waiting_human")
    plan = _plan(db, task)
    from app.models import WorkflowInstance

    workflow = WorkflowInstance(
        project_id=project.id, workflow_key="agent_draft", target_type="agent_task", target_id=task.id,
        status="running", current_step="review", created_by=task.created_by,
    )
    db.add(workflow)
    db.flush()
    review = ReviewTask(
        project_id=project.id, workflow_instance_id=workflow.id, step_key="review",
        task_type="agent_draft", target_type="agent_task", target_id=task.id,
        status="pending", assignee_user_id=scope["analyst"].user_id,
    )
    db.add(review)
    db.flush()
    db.add(AgentStep(
        task_id=task.id, plan_id=plan.id, step_key="review_draft", tool_key="draft_requirement_document",
        status="waiting_human", order_index=1, review_task_id=review.id,
        output_summary_json={"title": "等待复核"},
    ))
    db.commit()

    analyst_action = _pending_action(db, task, scope["analyst"], set(), "business_analyst")
    assert analyst_action["mine"] is True
    assert analyst_action["review_task_id"] == review.id

    manager_action = _pending_action(db, task, scope["manager"], set(), "project_manager")
    assert manager_action["mine"] is False


def test_task_row_exposes_business_fields_without_raw_error(scope):
    db, project = scope["db"], scope["project"]
    task = _task(db, project, status="failed", error_code="timeout", error_message="chain timeout after 30s")
    permissions = PermissionService(db, scope["manager"]).effective_project_permissions(project.id)
    row = _task_row(db, task, scope["manager"], permissions, "project_manager", [])

    assert row["updated_at"]
    assert row["object_label"] == "互联网贷款协议表"
    assert row["result_brief"]["kind"] == "failed"
    assert row["pending_action"] is None
    serialized = str(row)
    assert "chain timeout" not in serialized
    assert "timeout" not in row["result_brief"]["headline"]


def test_diagnostics_requires_audit_permission(scope):
    db, project = scope["db"], scope["project"]
    task = _task(db, project, status="completed")
    _artifact(db, task, summary={"answer": "ok"})

    payload = get_agent_task_diagnostics(task.id, scope["manager"], db)
    assert payload["task"]["id"] == task.id
    assert "steps" in payload and "plan" in payload

    with pytest.raises(HTTPException) as denied:
        get_agent_task_diagnostics(task.id, scope["analyst"], db)
    assert denied.value.status_code == 403
