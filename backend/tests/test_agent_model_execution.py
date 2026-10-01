"""Phase 8: a degraded step must never be reported as a model success."""
from __future__ import annotations

import pytest

from app.models import (
    AgentStep,
    AgentTask,
    AgentToolCall,
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
        display_name=tool_key, description=f"模型执行标记测试工具 {tool_key}",
        input_schema={"type": "object", "properties": {}}, output_schema={"type": "object", "properties": {}},
        required_permissions=frozenset({"project.view"}), risk_level="low", timeout_seconds=5,
        retry_policy={"max_attempts": 1}, read_only=True, requires_human_confirmation=False,
        evidence_contract={"fact_kinds": [], "artifact_types": []}, audit_fields=(), handler=handler,
    )
    values.update(overrides)
    key = f"{tool_key}_{_SEQ['n']}"
    register_tool(AgentToolSpec(tool_key=key, **values))
    return key


def _modelled(ctx) -> ToolResult:
    return ToolResult(output={"draft": True}, step_output={"ran": True},
                      model_metadata={"model_name": "bank-llm-v1", "provider": "internal",
                                      "prompt_version": "p3"})


def _degraded(ctx) -> ToolResult:
    return ToolResult(
        output={"draft": True}, step_output={"ran": True}, degraded_path="deterministic_draft",
        gaps=[{"code": "skill_binding_missing", "message": "未绑定已发布技能"}],
    )


def _silent_degrade(ctx) -> ToolResult:
    return ToolResult(output={"ok": True}, step_output={"ran": True},
                      gaps=[{"code": "skill_binding_missing", "message": "未绑定已发布技能"}])


@pytest.fixture()
def scope(db_session):
    institution = Institution(institution_code="modelexec-bank", institution_name="模型执行银行",
                              institution_type="bank", status="active")
    user = User(username="modelexec_user", display_name="模型执行用户", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="模型执行项目", institution_id=institution.id, project_status="active")
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectMembership(project_id=project.id, user_id=user.id,
                                     project_role="project_manager", status="active"))
    table = TargetTable(project_id=project.id, table_code="YBT_ME", table_name="模型表")
    db_session.add(table)
    db_session.flush()
    field = TargetField(project_id=project.id, target_table_id=table.id,
                        field_code="ME_BAL", field_name="模型余额")
    db_session.flush()
    return {"db": db_session, "project": project, "user": user, "field": field,
            "principal": Principal(user.id, user.username, user.display_name)}


def _run_one(db, scope, tool_key: str) -> AgentTask:
    task = AgentTask(institution_id=scope["project"].institution_id, project_id=scope["project"].id,
                     objective="模型执行验收：分析模型余额字段", scenario_key="regulatory_field_analysis",
                     status=sm.TASK_CREATED, plan_version=1, created_by=scope["user"].id,
                     result_summary_json={"subject": {"target_field_id": scope["field"].id}})
    db.add(task)
    db.flush()
    draft = planner.PlanDraft(objective=task.objective, scenario_key=task.scenario_key, subject={},
                              steps=[planner.PlannedStep(step_key="draft", tool_key=tool_key,
                                                         reason="生成候选", input={})])
    runtime.materialize_plan(db, task, draft, planner_source="deterministic")
    db.commit()
    job = runtime.submit_task(db, scope["project"], scope["principal"], task)
    runtime.run_agent_task(db, job)
    db.refresh(task)
    return task


def _step_of(db, task) -> AgentStep:
    return db.query(AgentStep).filter_by(task_id=task.id, step_key="draft").one()


def test_a_model_backed_step_reports_execution(scope):
    db = scope["db"]
    tool_key = _register("me_model", _modelled)
    task = _run_one(db, scope, tool_key)
    summary = _step_of(db, task).output_summary_json or {}
    execution = summary["model_execution"]
    assert execution["executed"] is True
    assert execution["model_name"] == "bank-llm-v1"
    assert execution["provider"] == "internal"
    assert execution["prompt_version"] == "p3"
    assert execution["degraded_path"] is None and execution["reason"] is None


def test_an_explicitly_degraded_step_is_not_a_model_success(scope):
    db = scope["db"]
    tool_key = _register("me_degraded", _degraded)
    task = _run_one(db, scope, tool_key)
    execution = (_step_of(db, task).output_summary_json or {})["model_execution"]
    assert execution["executed"] is False
    assert execution["degraded_path"] == "deterministic_draft"
    assert execution["reason"] == "deterministic_draft"
    assert execution["model_name"] is None


def test_a_missing_skill_binding_is_reported_as_not_executed(scope):
    db = scope["db"]
    tool_key = _register("me_silent", _silent_degrade)
    task = _run_one(db, scope, tool_key)
    execution = (_step_of(db, task).output_summary_json or {})["model_execution"]
    assert execution["executed"] is False, "a missing skill binding means no model ran"
    assert execution["reason"] == "skill_binding_missing"


def test_the_snapshot_exposes_the_execution_flag(scope):
    db = scope["db"]
    tool_key = _register("me_degraded2", _degraded)
    task = _run_one(db, scope, tool_key)
    step_payload = next(item for item in runtime.task_snapshot(db, task)["steps"]
                        if item["step_key"] == "draft")
    assert step_payload["model_execution"]["executed"] is False
    assert step_payload["model_execution"]["reason"] == "deterministic_draft"


def test_the_tool_call_keeps_the_degraded_path_for_audit(scope):
    db = scope["db"]
    tool_key = _register("me_degraded3", _degraded)
    task = _run_one(db, scope, tool_key)
    step = _step_of(db, task)
    call = db.query(AgentToolCall).filter_by(step_id=step.id).one()
    assert call.degraded_path == "deterministic_draft"
    assert call.model_name is None, "no model may be credited for a degraded step"
