"""Phase 11: one runner per task, and a duplicate consumer must not execute steps twice."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import (
    AgentStep,
    AgentTask,
    AgentToolCall,
    BackgroundJob,
    Institution,
    Project,
    ProjectMembership,
    TargetField,
    TargetTable,
    User,
)
from app.services.agent import runtime, state_machine as sm
from app.services.agent.tools.registry import AgentToolSpec, ToolResult, register_tool
from app.services.auth.dependencies import Principal

_SEQ = {"n": 0}


def _register(tool_key: str, handler, **overrides) -> str:
    _SEQ["n"] += 1
    values = dict(
        display_name=tool_key, description=f"并发租约测试工具 {tool_key}",
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
    institution = Institution(institution_code="lease-bank", institution_name="租约银行",
                              institution_type="bank", status="active")
    user = User(username="lease_manager", display_name="租约管理员", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="租约项目", institution_id=institution.id, project_status="active")
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectMembership(project_id=project.id, user_id=user.id,
                                     project_role="project_manager", status="active"))
    table = TargetTable(project_id=project.id, table_code="YBT_LEASE", table_name="租约表")
    db_session.add(table)
    db_session.flush()
    field = TargetField(project_id=project.id, target_table_id=table.id,
                        field_code="LEASE_BAL", field_name="租约余额")
    db_session.add(field)
    db_session.flush()
    return {"db": db_session, "project": project, "user": user, "field": field,
            "principal": Principal(user.id, user.username, user.display_name)}


def _task(db, scope) -> AgentTask:
    task = AgentTask(
        institution_id=scope["project"].institution_id, project_id=scope["project"].id,
        objective="租约验收：分析租约余额字段", scenario_key="regulatory_field_analysis",
        status=sm.TASK_CREATED, plan_version=1, created_by=scope["user"].id,
        result_summary_json={"subject": {"target_field_id": scope["field"].id}},
    )
    db.add(task)
    db.flush()
    return task


def test_the_claim_is_atomic_and_exclusive(scope):
    db = scope["db"]
    task = _task(db, scope)
    db.commit()

    assert runtime._claim_task_run(db, task.id) is True, "the first runner takes the lease"
    assert runtime._claim_task_run(db, task.id) is False, "a second runner must be refused"
    db.refresh(task)
    assert task.run_lease_until is not None

    runtime._release_task_run(db, task.id)
    db.refresh(task)
    assert task.run_lease_until is None
    assert runtime._claim_task_run(db, task.id) is True, "the lease is reusable after release"


def test_an_expired_lease_can_be_taken_over(scope):
    db = scope["db"]
    task = _task(db, scope)
    task.run_lease_until = runtime._now() - timedelta(seconds=1)
    db.commit()
    assert runtime._claim_task_run(db, task.id) is True, "a dead runner must not block the task forever"


def test_a_duplicate_consumer_executes_nothing(scope):
    db = scope["db"]
    tool_key = _register("lease_probe", _ok)
    task = _task(db, scope)
    from app.services.agent import planner
    draft = planner.PlanDraft(objective=task.objective, scenario_key=task.scenario_key, subject={},
                              steps=[planner.PlannedStep(step_key="only", tool_key=tool_key,
                                                         reason="唯一步骤", input={})])
    runtime.materialize_plan(db, task, draft, planner_source="deterministic")
    db.commit()

    job = runtime.submit_task(db, scope["project"], scope["principal"], task)
    # The inline queue may already have run it once; the refused duplicate must add nothing.
    before = db.query(AgentToolCall).filter_by(task_id=task.id).count()
    task = db.get(AgentTask, task.id)
    task.run_lease_until = runtime._now() + timedelta(seconds=runtime.TASK_RUN_LEASE_SECONDS)
    db.commit()
    result = runtime.run_agent_task(db, job)

    assert result.get("skipped") == "run_lease_held"
    assert db.query(AgentToolCall).filter_by(task_id=task.id).count() == before, \
        "a refused duplicate consumer must not call any tool"
    step = db.query(AgentStep).filter_by(task_id=task.id, step_key="only").one()
    assert step.attempt_count <= 1, "the duplicate consumer must not add an attempt"


def test_the_lease_is_released_after_a_normal_run(scope):
    db = scope["db"]
    tool_key = _register("lease_probe2", _ok)
    task = _task(db, scope)
    from app.services.agent import planner
    draft = planner.PlanDraft(objective=task.objective, scenario_key=task.scenario_key, subject={},
                              steps=[planner.PlannedStep(step_key="only", tool_key=tool_key,
                                                         reason="唯一步骤", input={})])
    runtime.materialize_plan(db, task, draft, planner_source="deterministic")
    db.commit()
    job = runtime.submit_task(db, scope["project"], scope["principal"], task)
    runtime.run_agent_task(db, job)
    db.refresh(task)
    assert task.run_lease_until is None, "a finished run must not hold the lease"
    assert db.query(AgentToolCall).filter_by(task_id=task.id).count() >= 1


def test_two_sequential_runs_never_repeat_a_completed_step(scope):
    db = scope["db"]
    tool_key = _register("lease_probe3", _ok)
    task = _task(db, scope)
    from app.services.agent import planner
    draft = planner.PlanDraft(objective=task.objective, scenario_key=task.scenario_key, subject={},
                              steps=[planner.PlannedStep(step_key="only", tool_key=tool_key,
                                                         reason="唯一步骤", input={})])
    runtime.materialize_plan(db, task, draft, planner_source="deterministic")
    db.commit()
    job = runtime.submit_task(db, scope["project"], scope["principal"], task)
    runtime.run_agent_task(db, job)
    calls_after_first = db.query(AgentToolCall).filter_by(task_id=task.id).count()

    # A restarted worker re-runs the same job: the step must stay completed exactly once.
    task = db.get(AgentTask, task.id)
    task.run_lease_until = None
    db.commit()
    runtime.run_agent_task(db, job)
    assert db.query(AgentToolCall).filter_by(task_id=task.id).count() == calls_after_first
    step = db.query(AgentStep).filter_by(task_id=task.id, step_key="only").one()
    assert step.status == sm.STEP_COMPLETED
    assert step.attempt_count == 1
