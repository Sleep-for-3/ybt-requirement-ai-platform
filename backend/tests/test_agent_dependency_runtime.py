"""V2 dependency semantics through the real runtime (no any(completed) shortcut)."""
from __future__ import annotations

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
from app.services.agent import planner, runtime, state_machine as sm
from app.services.agent.tools.registry import AgentToolSpec, ToolExecutionError, ToolResult, register_tool
from app.services.auth.dependencies import Principal

_SEQ = {"n": 0}


def _register(tool_key: str, handler, **overrides) -> str:
    _SEQ["n"] += 1
    values = dict(
        display_name=tool_key, description=f"依赖语义测试工具 {tool_key}",
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


def _blocked(ctx) -> ToolResult:
    return ToolResult(status="blocked", output={"ok": False},
                      gaps=[{"code": "upstream_missing", "message": "上游依据不足"}])


def _fails(ctx) -> ToolResult:
    raise ToolExecutionError("dependency_probe_failure", "依赖语义测试用失败", retryable=False)


@pytest.fixture()
def scope(db_session):
    institution = Institution(institution_code="dep-bank", institution_name="依赖语义测试银行",
                              institution_type="bank", status="active")
    user = User(username="dep_manager", display_name="依赖测试管理员", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="依赖语义项目", institution_id=institution.id, project_status="active")
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectMembership(project_id=project.id, user_id=user.id,
                                     project_role="project_manager", status="active"))
    table = TargetTable(project_id=project.id, table_code="YBT_DEP", table_name="依赖测试表")
    db_session.add(table)
    db_session.flush()
    field = TargetField(project_id=project.id, target_table_id=table.id,
                        field_code="DEP_BAL", field_name="依赖测试余额")
    db_session.add(field)
    db_session.flush()
    return {"db": db_session, "institution": institution, "project": project, "user": user,
            "principal": Principal(user.id, user.username, user.display_name), "field": field}


def _task(db, scope) -> AgentTask:
    task = AgentTask(
        institution_id=scope["institution"].id, project_id=scope["project"].id,
        objective="依赖语义验收：分析依赖测试余额字段", scenario_key="regulatory_field_analysis",
        status="created", plan_version=1, created_by=scope["user"].id,
        result_summary_json={"subject": {"target_field_id": scope["field"].id}},
    )
    db.add(task)
    db.flush()
    return task


def _plan(db, task, steps, *, subject=None):
    draft = planner.PlanDraft(objective=task.objective, scenario_key=task.scenario_key,
                              subject=subject or {}, steps=steps)
    plan = runtime.materialize_plan(db, task, draft, planner_source="deterministic")
    db.commit()
    return plan


def _step(key: str, tool: str, **kwargs) -> planner.PlannedStep:
    return planner.PlannedStep(step_key=key, tool_key=tool, reason="依赖语义测试步骤", **kwargs)


def _run(db, scope, task) -> BackgroundJob:
    job = runtime.submit_task(db, scope["project"], scope["principal"], task)
    runtime.run_agent_task(db, job)
    db.refresh(task)
    return job


def _step_row(db, task, key: str) -> AgentStep:
    return db.query(AgentStep).filter_by(task_id=task.id, step_key=key).order_by(AgentStep.id.desc()).first()


def test_required_blocked_dependency_blocks_the_dependent_step(scope):
    db = scope["db"]
    good = _register("dep_good", _ok)
    blocked = _register("dep_blocked", _blocked)
    downstream = _register("dep_downstream", _ok)
    task = _task(db, scope)
    _plan(db, task, [
        _step("s1", good),
        # Ungated-but-blocked dependency: the run continues, so the dependent step is evaluated.
        _step("s2", blocked, required=False),
        _step("s3", downstream, depends_on=["s1", "s2"]),
    ])
    _run(db, scope, task)

    assert _step_row(db, task, "s1").status == sm.STEP_COMPLETED
    assert _step_row(db, task, "s2").status == sm.STEP_BLOCKED
    s3 = _step_row(db, task, "s3")
    assert s3.status == sm.STEP_BLOCKED, "a blocked required dependency must not be treated as success"
    assert s3.error_code == "dependency_failed"
    assert db.query(AgentToolCall).filter_by(step_id=s3.id).count() == 0
    assert (task.result_summary_json or {}).get("incomplete") is not True


def test_required_skipped_dependency_skips_the_dependent_step(scope):
    db = scope["db"]
    good = _register("dep_good2", _ok)
    failing = _register("dep_failing", _fails)
    downstream = _register("dep_downstream2", _ok)
    task = _task(db, scope)
    _plan(db, task, [
        _step("s1", good),
        _step("s2", failing, required=False),          # optional plan step -> skipped on failure
        _step("s3", downstream, depends_on=["s1", "s2"]),
    ])
    _run(db, scope, task)

    assert _step_row(db, task, "s2").status == sm.STEP_SKIPPED
    s3 = _step_row(db, task, "s3")
    assert s3.status == sm.STEP_SKIPPED, "a skipped required dependency is not success"
    assert s3.error_code == "dependency_gap"
    assert "dependency_gap" in (s3.gap_codes_json or [])
    assert db.query(AgentToolCall).filter_by(step_id=s3.id).count() == 0
    assert (task.result_summary_json or {}).get("incomplete") is True


def test_optional_missing_dependency_still_runs_with_a_gap(scope):
    db = scope["db"]
    good = _register("dep_good3", _ok)
    failing = _register("dep_failing3", _fails)
    downstream = _register("dep_downstream3", _ok)
    task = _task(db, scope)
    _plan(db, task, [
        _step("s1", good),
        _step("s2", failing, required=False),
        _step("s3", downstream, optional_depends_on=["s2"]),
    ])
    _run(db, scope, task)

    s3 = _step_row(db, task, "s3")
    assert s3.status == sm.STEP_COMPLETED
    assert "optional_dependency_missing" in (s3.gap_codes_json or [])
    evaluation = (s3.output_summary_json or {}).get("dependency_evaluation") or {}
    assert evaluation["disposition"] == "execute"
    assert evaluation["optional_missing"] == [{"step_key": "s2", "status": sm.STEP_SKIPPED}]


def test_open_human_gate_pauses_dependent_steps(scope):
    db = scope["db"]
    gate = _register("dep_gate", _ok, requires_human_confirmation=True, risk_level="high")
    downstream = _register("dep_downstream4", _ok)
    task = _task(db, scope)
    _plan(db, task, [_step("s1", gate), _step("s2", downstream, depends_on=["s1"])])
    _run(db, scope, task)

    assert _step_row(db, task, "s1").status == sm.STEP_WAITING_HUMAN
    s2 = _step_row(db, task, "s2")
    assert s2.status == sm.STEP_PENDING, "an open gate must pause the chain, not skip the dependent step"
    assert s2.error_code is None
    assert db.query(AgentToolCall).filter_by(step_id=s2.id).count() == 0
    assert task.status == sm.TASK_WAITING_HUMAN


def test_dependencies_resolve_across_plan_versions(scope):
    db = scope["db"]
    good = _register("dep_good5", _ok)
    later = _register("dep_later5", _ok)
    task = _task(db, scope)
    _plan(db, task, [_step("s1", good)])
    _run(db, scope, task)
    assert _step_row(db, task, "s1").status == sm.STEP_COMPLETED

    # A new plan version reuses the completed step key: the dependency must still resolve.
    task.status = sm.TASK_BLOCKED  # a completed task is terminal; resume a blocked one instead
    db.commit()
    plan = _plan(db, task, [_step("s1", good), _step("s2", later, depends_on=["s1"])])
    assert plan.version_no == 2
    _run(db, scope, task)

    s2 = _step_row(db, task, "s2")
    assert s2.status == sm.STEP_COMPLETED
    assert db.query(AgentToolCall).filter_by(step_id=s2.id).count() == 1
    assert task.status == sm.TASK_COMPLETED


def test_replan_rebinds_rebuilt_dependencies(scope):
    db = scope["db"]
    good = _register("dep_good6", _ok)
    failing = _register("dep_failing6", _fails)
    downstream = _register("dep_downstream6", _ok)
    task = _task(db, scope)
    plan = _plan(db, task, [
        _step("s1", good), _step("s2", failing), _step("s3", downstream, depends_on=["s1", "s2"]),
    ])

    failed_step = _step_row(db, task, "s2")
    failed_step.status = sm.STEP_FAILED
    failed_step.error_code = "probe_failure"
    db.commit()

    replanned = runtime.replan(db, task, reason_code="dependency_probe", failed_step=failed_step)
    db.commit()
    assert replanned.version_no == 2
    assert task.plan_version == 2

    rebuilt = {step["step_key"]: step for step in (replanned.steps_json or [])}
    # Every rebuilt dependency must still point at an earlier surviving step.
    order = [step["step_key"] for step in (replanned.steps_json or [])]
    for index, step in enumerate(replanned.steps_json or []):
        for key in [*step.get("depends_on", []), *step.get("optional_depends_on", [])]:
            assert key in order[:index], f"{step['step_key']} points at a missing/later dependency {key}"
    assert (rebuilt["s2"]["tool_key"] != failing) or (rebuilt["s2"]["required"] is False), \
        "the failed tool must be replaced or demoted to optional"
