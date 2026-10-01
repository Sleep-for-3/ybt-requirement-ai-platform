"""Phase 11: crash recovery must not repeat business side effects."""
from __future__ import annotations

import pytest

from app.models import (
    AgentHumanDecision,
    AgentStep,
    AgentTask,
    AgentToolCall,
    AuditLog,
    Institution,
    Project,
    ProjectMembership,
    ReviewTask,
    TargetField,
    TargetTable,
    User,
)
from app.services.agent import planner, runtime, state_machine as sm
from app.services.agent.tools.registry import AgentToolSpec, ToolResult, register_tool
from app.services.auth.dependencies import Principal

_SEQ = {"n": 0}


def _register(tool_key: str, handler, **overrides) -> str:
    _SEQ["n"] += 1
    values = dict(
        display_name=tool_key, description=f"崩溃恢复测试工具 {tool_key}",
        input_schema={"type": "object", "properties": {}}, output_schema={"type": "object", "properties": {}},
        required_permissions=frozenset({"project.view"}), risk_level="low", timeout_seconds=5,
        retry_policy={"max_attempts": 1}, read_only=True, requires_human_confirmation=False,
        evidence_contract={"fact_kinds": [], "artifact_types": []}, audit_fields=(), handler=handler,
    )
    values.update(overrides)
    key = f"{tool_key}_{_SEQ['n']}"
    register_tool(AgentToolSpec(tool_key=key, **values))
    return key


def _ok(ctx) -> ToolResult:
    return ToolResult(output={"ok": True}, step_output={"ran": True})


@pytest.fixture()
def scope(db_session):
    institution = Institution(institution_code="crash-bank", institution_name="崩溃恢复银行",
                              institution_type="bank", status="active")
    user = User(username="crash_manager", display_name="崩溃恢复管理员", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="崩溃恢复项目", institution_id=institution.id, project_status="active")
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectMembership(project_id=project.id, user_id=user.id,
                                     project_role="project_manager", status="active"))
    table = TargetTable(project_id=project.id, table_code="YBT_CR", table_name="崩溃表")
    db_session.add(table)
    db_session.flush()
    field = TargetField(project_id=project.id, target_table_id=table.id,
                        field_code="CR_BAL", field_name="崩溃余额")
    db_session.flush()
    return {"db": db_session, "project": project, "user": user, "field": field,
            "principal": Principal(user.id, user.username, user.display_name)}


def _task_with_plan(db, scope, steps) -> AgentTask:
    task = AgentTask(institution_id=scope["project"].institution_id, project_id=scope["project"].id,
                     objective="崩溃恢复验收：分析崩溃余额字段", scenario_key="regulatory_field_analysis",
                     status=sm.TASK_CREATED, plan_version=1, created_by=scope["user"].id,
                     result_summary_json={"subject": {"target_field_id": scope["field"].id}})
    db.add(task)
    db.flush()
    draft = planner.PlanDraft(objective=task.objective, scenario_key=task.scenario_key, subject={},
                              steps=steps)
    runtime.materialize_plan(db, task, draft, planner_source="deterministic")
    db.commit()
    return task


def _planned(key: str, tool: str, **kwargs) -> planner.PlannedStep:
    return planner.PlannedStep(step_key=key, tool_key=tool, reason="崩溃恢复步骤", **kwargs)


def _calls(db, task) -> int:
    return db.query(AgentToolCall).filter_by(task_id=task.id).count()


def test_a_restart_after_a_completed_prefix_repeats_nothing(scope):
    db = scope["db"]
    first = _register("crash_a1", _ok)
    second = _register("crash_a2", _ok)
    task = _task_with_plan(db, scope, [_planned("s1", first), _planned("s2", second, depends_on=["s1"])])
    job = runtime.submit_task(db, scope["project"], scope["principal"], task)
    runtime.run_agent_task(db, job)
    calls_after_first = _calls(db, task)
    assert calls_after_first == 2

    # The worker restarts and runs the same job again: nothing may execute twice.
    db.expire_all()
    runtime.run_agent_task(db, job)
    assert _calls(db, task) == calls_after_first
    for key in ("s1", "s2"):
        step = db.query(AgentStep).filter_by(task_id=task.id, step_key=key).one()
        assert step.status == sm.STEP_COMPLETED and step.attempt_count == 1


def test_a_crash_after_the_tool_call_recovers_instead_of_rerunning(scope):
    db = scope["db"]
    tool_key = _register("crash_b", _ok)
    task = _task_with_plan(db, scope, [_planned("s1", tool_key)])
    job = runtime.submit_task(db, scope["project"], scope["principal"], task)
    runtime.run_agent_task(db, job)
    assert _calls(db, task) == 1

    # Simulate a crash after the tool call was recorded but before the status update.
    step = db.query(AgentStep).filter_by(task_id=task.id, step_key="s1").one()
    step.status = sm.STEP_RUNNING
    task.status = sm.TASK_RUNNING
    task.run_lease_until = None
    db.commit()

    runtime.run_agent_task(db, job)
    db.refresh(step)
    assert _calls(db, task) == 1, "the recorded tool call must be reused, not repeated"
    assert step.status == sm.STEP_COMPLETED
    assert (step.output_summary_json or {}).get("recovered_after_interruption")
    actions = {row.action for row in db.query(AuditLog).filter_by(project_id=scope["project"].id).all()}
    assert "agent_step_recovered" in actions


def test_a_crash_before_the_human_gate_keeps_one_gate_and_one_decision(scope):
    db = scope["db"]
    tool_key = _register("crash_c", _ok, requires_human_confirmation=True, risk_level="high")
    task = _task_with_plan(db, scope, [_planned("gate", tool_key)])
    job = runtime.submit_task(db, scope["project"], scope["principal"], task)
    runtime.run_agent_task(db, job)
    step = db.query(AgentStep).filter_by(task_id=task.id, step_key="gate").one()
    assert step.status == sm.STEP_WAITING_HUMAN
    assert db.query(ReviewTask).filter_by(workflow_instance_id=task.review_instance_id).count() == 1

    # A restarted worker must not open a second gate for the same step.
    db.expire_all()
    task = db.get(AgentTask, task.id)
    task.run_lease_until = None
    db.commit()
    runtime.run_agent_task(db, job)
    assert db.query(ReviewTask).filter_by(workflow_instance_id=task.review_instance_id).count() == 1
    assert db.query(AgentHumanDecision).filter_by(task_id=task.id).count() == 0

    runtime.decide(db, scope["principal"], task, step, sm.DECISION_APPROVE, comment="确认")
    assert db.query(AgentHumanDecision).filter_by(task_id=task.id).count() == 1
    # Replaying the same decision is idempotent.
    db.expire_all()
    step = db.query(AgentStep).filter_by(task_id=task.id, step_key="gate").one()
    task = db.get(AgentTask, task.id)
    runtime.decide(db, scope["principal"], task, step, sm.DECISION_APPROVE, comment="确认")
    assert db.query(AgentHumanDecision).filter_by(task_id=task.id).count() == 1


def test_a_cancelled_task_never_advances_again(scope):
    db = scope["db"]
    first = _register("crash_d1", _ok)
    second = _register("crash_d2", _ok)
    task = _task_with_plan(db, scope, [_planned("s1", first), _planned("s2", second, depends_on=["s1"])])
    # Cancel before the task ever runs: a cancelled task must not execute anything afterwards.
    runtime.cancel_task(db, scope["principal"], task)
    db.refresh(task)
    assert task.status == sm.TASK_CANCELLED

    job = runtime.submit_task(db, scope["project"], scope["principal"], task)
    db.expire_all()
    runtime.run_agent_task(db, job)
    assert _calls(db, task) == 0, "a cancelled task must not execute any tool"
    assert db.get(AgentTask, task.id).status == sm.TASK_CANCELLED


def test_planning_stage_interruption_is_recoverable(scope):
    db = scope["db"]
    tool_key = _register("crash_e", _ok)
    task = _task_with_plan(db, scope, [_planned("s1", tool_key)])
    # Crash right after planning, before any run: the plan is durable and the task is runnable.
    assert db.query(AgentStep).filter_by(task_id=task.id).count() == 1
    job = runtime.submit_task(db, scope["project"], scope["principal"], task)
    runtime.run_agent_task(db, job)
    db.refresh(task)
    assert task.status == sm.TASK_COMPLETED
    assert _calls(db, task) == 1
