"""Observe -> Replan: bounded, validated patches over the unexecuted plan."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.models import (
    AgentPlan,
    AgentStep,
    AgentTask,
    Institution,
    Project,
    ProjectMembership,
    TargetField,
    TargetTable,
    User,
)
from app.services.agent import planner, runtime, state_machine as sm, observation
from app.services.agent.tools.registry import AgentToolSpec, ToolResult, register_tool
from app.services.auth.dependencies import Principal

_SEQ = {"n": 0}


def _register(tool_key: str, handler, **overrides) -> str:
    _SEQ["n"] += 1
    values = dict(
        display_name=tool_key, description=f"自适应测试工具 {tool_key}",
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
    institution = Institution(institution_code="adapt-bank", institution_name="自适应银行",
                              institution_type="bank", status="active")
    user = User(username="adapt_manager", display_name="自适应管理员", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="自适应项目", institution_id=institution.id, project_status="active")
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectMembership(project_id=project.id, user_id=user.id,
                                     project_role="project_manager", status="active"))
    table = TargetTable(project_id=project.id, table_code="YBT_AD", table_name="自适应表")
    db_session.add(table)
    db_session.flush()
    field = TargetField(project_id=project.id, target_table_id=table.id,
                        field_code="AD_BAL", field_name="自适应余额")
    db_session.add(field)
    db_session.flush()
    return {"db": db_session, "project": project, "user": user, "field": field,
            "principal": Principal(user.id, user.username, user.display_name)}


def _task_with_plan(db, scope, steps) -> AgentTask:
    task = AgentTask(
        institution_id=scope["institution"].id if "institution" in scope else scope["project"].institution_id,
        project_id=scope["project"].id, objective="自适应验收：分析自适应余额字段",
        scenario_key="regulatory_field_analysis", status=sm.TASK_RUNNING, plan_version=1,
        created_by=scope["user"].id, adaptive=True, result_summary_json={"subject": {}},
    )
    db.add(task)
    db.flush()
    draft = planner.PlanDraft(objective=task.objective, scenario_key=task.scenario_key,
                              subject={}, steps=steps)
    runtime.materialize_plan(db, task, draft, planner_source="deterministic")
    db.commit()
    return task



def _planned(key: str, tool: str, **kwargs) -> planner.PlannedStep:
    return planner.PlannedStep(step_key=key, tool_key=tool, reason="自适应测试步骤", **kwargs)


def test_patch_adds_steps_and_marks_gaps_without_touching_completed_rows(scope):
    db = scope["db"]
    first = _register("adapt_first", _ok)
    second = _register("adapt_second", _ok)
    third = _register("adapt_third", _ok)
    task = _task_with_plan(db, scope, [_planned("s1", first), _planned("s2", second)])
    row = db.query(AgentStep).filter_by(task_id=task.id, step_key="s1").one()
    row.status = sm.STEP_COMPLETED
    db.commit()

    patch = planner.PlanPatch(rationale="首轮证据不足，追加一个检索步骤", ops=[
        planner.PlanPatchOp(op="add_step", step_key="s3", tool_key=third, reason="补充证据",
                            depends_on=["s2"], input={}),
        planner.PlanPatchOp(op="mark_gap", step_key="s2", reason="无匹配条款", gap_code="no_clause"),
    ])
    plan = runtime.apply_plan_patch(db, task, patch)

    assert plan.version_no == 2 and plan.planner_source == "observe_replan"
    assert task.plan_version == 2 and task.replanning_count == 1
    keys = [step["step_key"] for step in plan.steps_json]
    assert keys == ["s1", "s2", "s3"], "completed steps must stay in the new plan"
    assert db.query(AgentStep).filter_by(task_id=task.id, step_key="s1").one().status == sm.STEP_COMPLETED
    summary = task.result_summary_json or {}
    assert summary["observations"][-1]["applied"] is True
    assert summary["observations"][-1]["gaps"][0]["code"] == "no_clause"


def test_patch_may_not_change_a_completed_step(scope):
    db = scope["db"]
    first = _register("adapt_a", _ok)
    task = _task_with_plan(db, scope, [_planned("s1", first)])
    row = db.query(AgentStep).filter_by(task_id=task.id, step_key="s1").one()
    row.status = sm.STEP_COMPLETED
    db.commit()
    patch = planner.PlanPatch(rationale="改已完成步骤", ops=[
        planner.PlanPatchOp(op="update_step", step_key="s1", reason="改参数", input={}),
    ])
    with pytest.raises(HTTPException) as exc:
        runtime.apply_plan_patch(db, task, patch)
    assert exc.value.detail["error_code"] == "plan_patch_invalid"
    assert any("cannot be changed" in item for item in exc.value.detail["errors"])


def test_patch_may_not_drop_a_required_step(scope):
    db = scope["db"]
    first = _register("adapt_b", _ok)
    task = _task_with_plan(db, scope, [_planned("s1", first)])
    patch = planner.PlanPatch(rationale="删必需步骤", ops=[
        planner.PlanPatchOp(op="drop_step", step_key="s1", reason="不需要了"),
    ])
    with pytest.raises(HTTPException) as exc:
        runtime.apply_plan_patch(db, task, patch)
    assert exc.value.detail["error_code"] == "plan_patch_invalid"


def test_patch_dropping_a_step_also_drops_its_dependents(scope):
    db = scope["db"]
    first = _register("adapt_c1", _ok)
    optional = _register("adapt_c2", _ok)
    dependent = _register("adapt_c3", _ok)
    task = _task_with_plan(db, scope, [
        _planned("s1", first),
        _planned("s2", optional, required=False),
        _planned("s3", dependent, depends_on=["s2"]),
    ])
    patch = planner.PlanPatch(rationale="可选步骤无意义，移除并连带下游", ops=[
        planner.PlanPatchOp(op="drop_step", step_key="s2", reason="该来源不存在"),
    ])
    plan = runtime.apply_plan_patch(db, task, patch)
    keys = [step["step_key"] for step in plan.steps_json]
    assert keys == ["s1"], "a dropped step must take its dependents with it"


def test_patch_adding_an_unregistered_tool_is_rejected_at_materialization(scope):
    db = scope["db"]
    first = _register("adapt_d", _ok)
    task = _task_with_plan(db, scope, [_planned("s1", first)])
    patch = planner.PlanPatch(rationale="试图新增未注册工具", ops=[
        planner.PlanPatchOp(op="add_step", step_key="s9", tool_key="not_a_registered_tool", reason="越权"),
    ])
    with pytest.raises(HTTPException) as exc:
        runtime.apply_plan_patch(db, task, patch)
    assert exc.value.detail["error_code"] == "plan_invalid"


def test_patch_validation_refuses_ops_beyond_the_active_plan(scope):
    db = scope["db"]
    first = _register("adapt_e", _ok)
    task = _task_with_plan(db, scope, [_planned("s1", first)])
    patch = planner.PlanPatch(rationale="引用不存在的步骤", ops=[
        planner.PlanPatchOp(op="update_step", step_key="ghost", reason="改参数", input={}),
    ])
    with pytest.raises(HTTPException) as exc:
        runtime.apply_plan_patch(db, task, patch)
    assert any("not part of the active plan" in item for item in exc.value.detail["errors"])


def test_observer_patch_is_applied_during_the_run(monkeypatch, scope):
    db = scope["db"]
    first = _register("adapt_run1", _ok)
    added = _register("adapt_run2", _ok)
    task = _task_with_plan(db, scope, [_planned("s1", first)])
    db.commit()

    async def fake_patch(db_, project_, *, state, digest, confidentiality="internal", permitted=None):
        assert "completed_steps" in state and "remaining_budget" in state
        return planner.PlanPatch(rationale="首轮后追加确认步骤", ops=[
            planner.PlanPatchOp(op="add_step", step_key="s2", tool_key=added, reason="追加证据步骤",
                                depends_on=["s1"], input={}),
        ]), {"model_name": "fake"}, None

    monkeypatch.setattr(planner, "plan_patch_with_llm", fake_patch)
    job = runtime.submit_task(db, scope["project"], scope["principal"], task)
    runtime.run_agent_task(db, job)
    db.refresh(task)

    statuses = {row.step_key: row.status for row in db.query(AgentStep).filter_by(task_id=task.id)}
    assert statuses.get("s2") == sm.STEP_COMPLETED, "the observer's added step must run"
    plan = db.query(AgentPlan).filter_by(task_id=task.id).order_by(AgentPlan.version_no.desc()).first()
    assert plan.planner_source == "observe_replan"
    observations = (task.result_summary_json or {})["observations"]
    assert any(item.get("applied") for item in observations), "the applied patch must be recorded"
    assert task.replanning_count >= 1, "a rejected patch must consume the replan budget"


def test_non_adaptive_task_never_observes(monkeypatch, scope):
    db = scope["db"]
    first = _register("adapt_run3", _ok)
    task = _task_with_plan(db, scope, [_planned("s1", first)])
    task.adaptive = False
    db.commit()

    async def boom(*args, **kwargs):
        raise AssertionError("the observer must not run for a non-adaptive task")

    monkeypatch.setattr(planner, "plan_patch_with_llm", boom)
    job = runtime.submit_task(db, scope["project"], scope["principal"], task)
    runtime.run_agent_task(db, job)
    db.refresh(task)
    assert db.query(AgentPlan).filter_by(task_id=task.id).count() == 1
    assert not (task.result_summary_json or {}).get("observations")
