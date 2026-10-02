"""A task must complete once the live plan's steps are done, even after a replan."""
from __future__ import annotations

import pytest

from app.models import AgentPlan, AgentStep, AgentTask, Institution, Project, ProjectMembership, TargetField, TargetTable, User
from app.services.agent import planner, runtime, state_machine as sm
from app.services.agent.tools.registry import AgentToolSpec, ToolResult, register_tool
from app.services.auth.dependencies import Principal

_SEQ = {"n": 0}


def _register(tool_key: str, handler) -> str:
    _SEQ["n"] += 1
    key = f"{tool_key}_{_SEQ['n']}"
    register_tool(AgentToolSpec(
        tool_key=key, display_name=tool_key, description=f"完成度测试工具 {tool_key}",
        input_schema={"type": "object", "properties": {}}, output_schema={"type": "object", "properties": {}},
        required_permissions=frozenset({"project.view"}), risk_level="low", timeout_seconds=5,
        retry_policy={"max_attempts": 1}, read_only=True, requires_human_confirmation=False,
        evidence_contract={"fact_kinds": [], "artifact_types": []}, audit_fields=(), handler=handler,
    ))
    return key


def _ok(ctx) -> ToolResult:
    return ToolResult(output={"ok": True}, step_output={"ran": True})


@pytest.fixture()
def scope(db_session):
    institution = Institution(institution_code="done-bank", institution_name="完成银行",
                              institution_type="bank", status="active")
    user = User(username="done_manager", display_name="完成管理员", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="完成项目", institution_id=institution.id, project_status="active")
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectMembership(project_id=project.id, user_id=user.id,
                                     project_role="project_manager", status="active"))
    table = TargetTable(project_id=project.id, table_code="YBT_DONE", table_name="完成表")
    db_session.add(table)
    db_session.flush()
    field = TargetField(project_id=project.id, target_table_id=table.id,
                        field_code="DN_BAL", field_name="完成余额")
    db_session.flush()
    return {"db": db_session, "project": project, "user": user, "field": field,
            "principal": Principal(user.id, user.username, user.display_name)}


def test_a_replanned_task_completes_when_the_live_steps_are_done(scope):
    db = scope["db"]
    first = _register("done_a", _ok)
    second = _register("done_b", _ok)
    task = AgentTask(
        institution_id=scope["project"].institution_id, project_id=scope["project"].id,
        objective="完成度验收：分析完成余额字段", scenario_key="regulatory_field_analysis",
        status=sm.TASK_CREATED, plan_version=1, created_by=scope["user"].id, adaptive=False,
        result_summary_json={"subject": {"target_field_id": scope["field"].id}},
    )
    db.add(task)
    db.flush()
    runtime.materialize_plan(db, task, planner.PlanDraft(
        objective=task.objective, scenario_key=task.scenario_key, subject={},
        steps=[planner.PlannedStep(step_key="s1", tool_key=first, reason="一步", input={})]),
        planner_source="deterministic")
    db.commit()

    # A replan supersedes the plan: the old rows stay behind for the same step key.
    runtime.apply_plan_patch(db, task, planner.PlanPatch(rationale="追加第二步", ops=[
        planner.PlanPatchOp(op="add_step", step_key="s2", tool_key=second, reason="追加", depends_on=["s1"],
                            input={}),
    ]))
    db.commit()

    job = runtime.submit_task(db, scope["project"], scope["principal"], task)
    runtime.run_agent_task(db, job)
    db.expire_all()
    task = db.get(AgentTask, task.id)
    db.refresh(task)
    live = db.query(AgentStep).filter_by(task_id=task.id).count()
    assert live >= 2
    assert task.status == sm.TASK_COMPLETED, f"task stayed {task.status} after its live steps completed"
    assert task.pending_steps == 0
    assert int(task.completed_steps) >= 2
