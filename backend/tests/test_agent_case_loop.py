"""Closed loop: an approving human decision becomes case memory, a rejection does not."""
from __future__ import annotations

import pytest

from app.models import (
    AgentHumanDecision,
    AgentStep,
    AgentTask,
    DecisionCase,
    Institution,
    Project,
    ProjectMembership,
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
        display_name=tool_key, description=f"案例闭环测试工具 {tool_key}",
        input_schema={"type": "object", "properties": {}}, output_schema={"type": "object", "properties": {}},
        required_permissions=frozenset({"project.view"}), risk_level="high", timeout_seconds=5,
        retry_policy={"max_attempts": 1}, read_only=True, requires_human_confirmation=True,
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
    institution = Institution(institution_code="loop-bank", institution_name="案例闭环银行",
                              institution_type="bank", status="active")
    user = User(username="loop_manager", display_name="案例闭环管理员", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="案例闭环项目", institution_id=institution.id, project_status="active")
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectMembership(project_id=project.id, user_id=user.id,
                                     project_role="project_manager", status="active"))
    table = TargetTable(project_id=project.id, table_code="YBT_LOOP", table_name="闭环表")
    db_session.add(table)
    db_session.flush()
    field = TargetField(project_id=project.id, target_table_id=table.id,
                        field_code="LOOP_BAL", field_name="闭环余额")
    db_session.add(field)
    db_session.flush()
    return {"db": db_session, "project": project, "user": user, "field": field,
            "principal": Principal(user.id, user.username, user.display_name)}


def _gate_task(db, scope, tool_key: str) -> AgentTask:
    task = AgentTask(institution_id=scope["project"].institution_id, project_id=scope["project"].id,
                     objective="案例闭环验收：分析闭环余额字段", scenario_key="mapping_resolution",
                     status=sm.TASK_CREATED, plan_version=1, created_by=scope["user"].id,
                     result_summary_json={"subject": {"target_field_id": scope["field"].id,
                                                      "target_field_code": "LOOP_BAL"}})
    db.add(task)
    db.flush()
    draft = planner.PlanDraft(objective=task.objective, scenario_key=task.scenario_key,
                              subject={"target_field_id": scope["field"].id},
                              steps=[planner.PlannedStep(step_key="gate", tool_key=tool_key,
                                                         reason="人工确认映射建议", input={})])
    runtime.materialize_plan(db, task, draft, planner_source="deterministic")
    db.commit()
    return task


def test_approving_a_mapping_gate_creates_case_memory(scope):
    db = scope["db"]
    tool_key = _register("loop_mapping", _ok)
    # the runtime's policy table maps real tool keys; register the stub here
    monkeypatch_map = runtime.CASE_DECISION_TYPES
    monkeypatch_map[tool_key] = "field_mapping_decision"
    task = _gate_task(db, scope, tool_key)
    job = runtime.submit_task(db, scope["project"], scope["principal"], task)
    runtime.run_agent_task(db, job)
    db.refresh(task)
    step = db.query(AgentStep).filter_by(task_id=task.id, step_key="gate").one()
    assert step.status == sm.STEP_WAITING_HUMAN

    runtime.decide(db, scope["principal"], task, step, sm.DECISION_EDIT_AND_APPROVE,
                   comment="按业务确认采用该映射", edited_payload={"decision_text": "映射到 LOOP_SRC"})

    cases = db.query(DecisionCase).filter_by(project_id=scope["project"].id).all()
    assert len(cases) == 1, "an approving human decision must leave exactly one case"
    case = cases[0]
    assert case.confidence_source == "human_decision"
    assert case.decision_type == "field_mapping_decision"
    assert case.decision == "映射到 LOOP_SRC"
    assert case.subject_type == "target_field"
    assert case.subject_id == str(scope["field"].id)
    assert case.approved_by == scope["user"].id
    assert case.scenario_key == "mapping_resolution"


def test_rejecting_a_gate_writes_no_case_memory(scope):
    db = scope["db"]
    tool_key = _register("loop_mapping2", _ok)
    runtime.CASE_DECISION_TYPES[tool_key] = "field_mapping_decision"
    task = _gate_task(db, scope, tool_key)
    job = runtime.submit_task(db, scope["project"], scope["principal"], task)
    runtime.run_agent_task(db, job)
    db.refresh(task)
    step = db.query(AgentStep).filter_by(task_id=task.id, step_key="gate").one()

    runtime.decide(db, scope["principal"], task, step, sm.DECISION_REJECT, comment="依据不足")
    assert db.query(DecisionCase).filter_by(project_id=scope["project"].id).count() == 0


def test_a_memory_failure_never_breaks_the_decision(scope, monkeypatch):
    db = scope["db"]
    from app.services.agent import case_memory

    def boom(*args, **kwargs):
        raise case_memory.CaseMemoryError("unsupported_confidence_source", "refused")

    monkeypatch.setattr(case_memory, "record_decision_case", boom)
    tool_key = _register("loop_mapping3", _ok)
    runtime.CASE_DECISION_TYPES[tool_key] = "field_mapping_decision"
    task = _gate_task(db, scope, tool_key)
    job = runtime.submit_task(db, scope["project"], scope["principal"], task)
    runtime.run_agent_task(db, job)
    db.refresh(task)
    step = db.query(AgentStep).filter_by(task_id=task.id, step_key="gate").one()

    runtime.decide(db, scope["principal"], task, step, sm.DECISION_APPROVE, comment="同意")
    db.refresh(step)
    assert step.status == sm.STEP_COMPLETED, "the governed decision must still be applied"
    assert db.query(DecisionCase).filter_by(project_id=scope["project"].id).count() == 0
