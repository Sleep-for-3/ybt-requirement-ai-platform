"""A failed run must never leave the task running with the lease held."""
from __future__ import annotations

import pytest

from app.models import AgentStep, AgentTask, Institution, Project, ProjectMembership, TargetField, TargetTable, User
from app.services.agent import planner, runtime, state_machine as sm
from app.services.auth.dependencies import Principal


@pytest.fixture()
def scope(db_session):
    institution = Institution(institution_code="halt-bank", institution_name="中止银行",
                              institution_type="bank", status="active")
    user = User(username="halt_manager", display_name="中止管理员", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="中止项目", institution_id=institution.id, project_status="active")
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectMembership(project_id=project.id, user_id=user.id,
                                     project_role="project_manager", status="active"))
    table = TargetTable(project_id=project.id, table_code="YBT_HALT", table_name="中止表")
    db_session.add(table)
    db_session.flush()
    field = TargetField(project_id=project.id, target_table_id=table.id,
                        field_code="HT_BAL", field_name="中止余额")
    db_session.flush()
    return {"db": db_session, "project": project, "user": user, "field": field,
            "principal": Principal(user.id, user.username, user.display_name)}


def _task(db, scope) -> AgentTask:
    task = AgentTask(
        institution_id=scope["project"].institution_id, project_id=scope["project"].id,
        objective="中止验收：分析中止余额字段", scenario_key="regulatory_field_analysis",
        status=sm.TASK_CREATED, plan_version=1, created_by=scope["user"].id,
        result_summary_json={"subject": {"target_field_id": scope["field"].id}},
    )
    db.add(task)
    db.flush()
    draft = planner.PlanDraft(objective=task.objective, scenario_key=task.scenario_key, subject={},
                              steps=[planner.PlannedStep(step_key="s1", tool_key="search_metadata",
                                                         reason="一步", input={})])
    runtime.materialize_plan(db, task, draft, planner_source="deterministic")
    db.commit()
    return task


def test_a_planner_failure_records_the_reason_and_releases_the_lease(scope, monkeypatch):
    db = scope["db"]
    task = _task(db, scope)
    job = runtime.submit_task(db, scope["project"], scope["principal"], task)

    async def boom(*args, **kwargs):
        raise ValueError("1 validation error for PlanDraft: depends on non-earlier steps")

    monkeypatch.setattr(runtime, "_run_task", boom)
    task = db.get(AgentTask, task.id)
    task.run_lease_until = None
    db.commit()
    result = runtime.run_agent_task(db, job)

    assert result["failed_count"] == 1
    assert "PlanDraft" in result["error"]
    task = db.get(AgentTask, task.id)
    assert task.error_code == "agent_run_failed"
    assert "PlanDraft" in (task.error_message or "")
    assert (task.result_summary_json or {}).get("halt_reason", {}).get("code") == "run_failed"
    assert task.run_lease_until is None, "a failed run must still release the single-runner lease"
    assert task.status != sm.TASK_RUNNING, "a failed run must not leave the task running"


def test_a_refused_run_keeps_recording_the_refusal(scope, monkeypatch):
    db = scope["db"]
    from fastapi import HTTPException

    task = _task(db, scope)
    job = runtime.submit_task(db, scope["project"], scope["principal"], task)

    async def refused(*args, **kwargs):
        raise HTTPException(status_code=403, detail={"error_code": "missing_permission"})

    monkeypatch.setattr(runtime, "_run_task", refused)
    task = db.get(AgentTask, task.id)
    task.run_lease_until = None
    db.commit()
    result = runtime.run_agent_task(db, job)

    assert result["failed_count"] == 1
    task = db.get(AgentTask, task.id)
    assert task.error_code == "agent_run_refused"
    assert task.run_lease_until is None


def test_pending_steps_are_settled_after_a_failed_run(scope, monkeypatch):
    db = scope["db"]
    task = _task(db, scope)
    job = runtime.submit_task(db, scope["project"], scope["principal"], task)

    async def boom(*args, **kwargs):
        raise RuntimeError("planner exploded")

    monkeypatch.setattr(runtime, "_run_task", boom)
    task = db.get(AgentTask, task.id)
    task.run_lease_until = None
    db.commit()
    runtime.run_agent_task(db, job)

    statuses = {step.status for step in db.query(AgentStep).filter_by(task_id=task.id).all()}
    assert statuses <= {sm.STEP_COMPLETED, sm.STEP_BLOCKED, sm.STEP_SKIPPED, sm.STEP_FAILED}
    assert sm.STEP_PENDING not in statuses and sm.STEP_RUNNING not in statuses, \
        "a failed run must not leave a step silently pending or running"
