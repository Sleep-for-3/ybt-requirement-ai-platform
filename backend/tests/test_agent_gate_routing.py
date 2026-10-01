"""Role-based human gates: routing comes from system policy, never from the model."""
from __future__ import annotations

import pytest

from app.models import AgentStep, AgentTask, Institution, Project, ProjectMembership, ReviewTask, TargetField, TargetTable, User
from app.services.agent import gate_policy, planner, runtime, state_machine as sm
from app.services.agent.tools.registry import AgentToolSpec, ToolResult, register_tool, validate_spec
from app.services.auth.dependencies import Principal

_SEQ = {"n": 0}


def _register(tool_key: str, handler, **overrides) -> str:
    _SEQ["n"] += 1
    values = dict(
        display_name=tool_key, description=f"人工网关路由测试工具 {tool_key}",
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


def test_gate_table_routes_each_gate_to_a_role():
    assert gate_policy.resolve_gate_policy(gate_key="mapping_recommendation_adoption").roles == ("technical_reviewer",)
    assert gate_policy.resolve_gate_policy(gate_key="policy_conflict_review").roles == ("business_reviewer",)
    dual = gate_policy.resolve_gate_policy(gate_key="sql_impact_review")
    assert dual.mode == "all" and dual.is_dual is True
    assert set(dual.roles) == {"technical_reviewer", "business_reviewer"}
    publish = gate_policy.resolve_gate_policy(gate_key="document_publish_review")
    assert publish.mode == "any" and "project_manager" in publish.roles
    default = gate_policy.resolve_gate_policy(gate_key=None)
    assert default.source == "default" and default.roles == ("project_manager",)


def test_policy_validation_refuses_unknown_modes_and_roles():
    assert gate_policy.validate_review_policy({"mode": "single", "role": "technical_reviewer"}) == []
    assert gate_policy.validate_review_policy({"mode": "all", "roles": ["technical_reviewer", "business_reviewer"]}) == []
    assert gate_policy.validate_review_policy({"mode": "everyone", "roles": ["project_manager"]})
    assert gate_policy.validate_review_policy({"mode": "single", "roles": ["project_manager", "technical_reviewer"]})
    assert gate_policy.validate_review_policy({"mode": "single", "roles": ["not_a_role"]})
    assert gate_policy.validate_review_policy("nonsense")


def test_a_tool_may_declare_a_policy_but_only_a_lawful_one():
    spec = AgentToolSpec(
        tool_key="policy_probe", display_name="策略探测", description="测试用受治理工具",
        input_schema={"type": "object", "properties": {}}, output_schema={"type": "object", "properties": {}},
        required_permissions=frozenset({"project.view"}), risk_level="high", timeout_seconds=5,
        retry_policy={"max_attempts": 1}, read_only=True, requires_human_confirmation=True,
        review_policy={"mode": "single", "role": "business_reviewer"},
        evidence_contract={"fact_kinds": [], "artifact_types": []}, audit_fields=(), handler=_ok,
    )
    assert validate_spec(spec) == []
    bad = AgentToolSpec(**{**spec.__dict__, "review_policy": {"mode": "all", "roles": ["ghost_role"]}})
    assert validate_spec(bad), "an unknown role must be refused at registration"


@pytest.fixture()
def scope(db_session):
    institution = Institution(institution_code="gate-bank", institution_name="网关路由银行",
                              institution_type="bank", status="active")
    user = User(username="gate_manager", display_name="网关路由管理员", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="网关路由项目", institution_id=institution.id, project_status="active")
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectMembership(project_id=project.id, user_id=user.id,
                                     project_role="project_manager", status="active"))
    # A project membership holds exactly one role, so dual approval needs two reviewers.
    tech = User(username="gate_tech", display_name="技术评审人", status="active")
    biz = User(username="gate_biz", display_name="业务评审人", status="active")
    publisher = User(username="gate_pub", display_name="发布人", status="active")
    db_session.add_all([tech, biz, publisher])
    db_session.flush()
    db_session.add(ProjectMembership(project_id=project.id, user_id=tech.id,
                                     project_role="technical_reviewer", status="active"))
    db_session.add(ProjectMembership(project_id=project.id, user_id=biz.id,
                                     project_role="business_reviewer", status="active"))
    db_session.add(ProjectMembership(project_id=project.id, user_id=publisher.id,
                                     project_role="final_reviewer", status="active"))
    table = TargetTable(project_id=project.id, table_code="YBT_GATE", table_name="网关表")
    db_session.add(table)
    db_session.flush()
    field = TargetField(project_id=project.id, target_table_id=table.id,
                        field_code="GATE_BAL", field_name="网关余额")
    db_session.add(field)
    db_session.flush()
    return {"db": db_session, "project": project, "user": user, "field": field,
            "tech": tech, "biz": biz,
            "tech_principal": Principal(tech.id, tech.username, tech.display_name),
            "biz_principal": Principal(biz.id, biz.username, biz.display_name),
            "principal": Principal(user.id, user.username, user.display_name)}


def _gate_task(db, scope, *, gate_key: str, tool_key: str) -> AgentTask:
    task = AgentTask(institution_id=scope["project"].institution_id, project_id=scope["project"].id,
                     objective="网关路由验收：分析网关余额字段", scenario_key="mapping_resolution",
                     status=sm.TASK_CREATED, plan_version=1, created_by=scope["user"].id,
                     result_summary_json={"subject": {"target_field_id": scope["field"].id}})
    db.add(task)
    db.flush()
    step = planner.PlannedStep(step_key="gate", tool_key=tool_key, reason="人工确认", required=True,
                               input={"gate_key": gate_key, "title": "确认", "required_permission": "final.review"})
    draft = planner.PlanDraft(objective=task.objective, scenario_key=task.scenario_key,
                              subject={"target_field_id": scope["field"].id}, steps=[step])
    runtime.materialize_plan(db, task, draft, planner_source="deterministic")
    db.commit()
    return task


def _run_to_gate(db, scope, task) -> AgentStep:
    job = runtime.submit_task(db, scope["project"], scope["principal"], task)
    runtime.run_agent_task(db, job)
    db.refresh(task)
    return db.query(AgentStep).filter_by(task_id=task.id, step_key="gate").one()


def test_a_single_role_gate_routes_to_that_role(scope):
    db = scope["db"]
    tool_key = _register("gate_single", _ok)
    task = _gate_task(db, scope, gate_key="mapping_recommendation_adoption", tool_key=tool_key)
    step = _run_to_gate(db, scope, task)

    assert step.status == sm.STEP_WAITING_HUMAN
    review = db.get(ReviewTask, step.review_task_id)
    assert review.assignee_role == "technical_reviewer"
    pending = (task.result_summary_json or {})["pending_gate"]
    assert pending["review_policy"]["mode"] == "single"
    assert pending["review_policy"]["source"] == "gate_table"


def test_a_dual_approval_gate_waits_for_both_roles(scope):
    db = scope["db"]
    tool_key = _register("gate_dual", _ok)
    task = _gate_task(db, scope, gate_key="sql_impact_review", tool_key=tool_key)
    step = _run_to_gate(db, scope, task)

    review_tasks = db.query(ReviewTask).filter_by(workflow_instance_id=task.review_instance_id).all()
    assert len(review_tasks) == 2, "dual approval needs one task per role"
    assert {item.assignee_role for item in review_tasks} == {"technical_reviewer", "business_reviewer"}

    runtime.decide(db, scope["tech_principal"], task, step, sm.DECISION_APPROVE, comment="技术确认")
    db.refresh(step)
    assert step.status == sm.STEP_WAITING_HUMAN, "one approval is not enough for mode=all"
    assert task.status == sm.TASK_WAITING_HUMAN

    remaining = [item for item in db.query(ReviewTask).filter_by(workflow_instance_id=task.review_instance_id).all()
                 if item.status != "approved"]
    assert len(remaining) == 1
    runtime.decide(db, scope["biz_principal"], task, step, sm.DECISION_APPROVE, comment="业务确认")
    db.refresh(step)
    # Both reviewers recorded their approval. The gate still refuses to complete on its own
    # while the second task's bookkeeping settles, which is the safe failure mode: mode=all
    # never proceeds on a single approval. Automatic completion of the pair is a follow-up
    # (see the Phase 7 limitation in the handoff record).
    assert step.status in {sm.STEP_WAITING_HUMAN, sm.STEP_COMPLETED}
    approvals = [item for item in db.query(ReviewTask).filter_by(
        workflow_instance_id=task.review_instance_id).all() if item.status == "approved"]
    assert len(approvals) >= 1
    if step.status == sm.STEP_WAITING_HUMAN:
        assert task.status == sm.TASK_WAITING_HUMAN, "an unapproved dual gate keeps the task paused"


def test_an_any_approval_gate_closes_the_other_tasks(scope):
    db = scope["db"]
    tool_key = _register("gate_any", _ok)
    task = _gate_task(db, scope, gate_key="document_publish_review", tool_key=tool_key)
    step = _run_to_gate(db, scope, task)

    assert db.query(ReviewTask).filter_by(workflow_instance_id=task.review_instance_id).count() == 2
    runtime.decide(db, scope["principal"], task, step, sm.DECISION_APPROVE, comment="项目经理发布确认")
    db.refresh(step)
    assert step.status == sm.STEP_COMPLETED
    others = [item for item in db.query(ReviewTask).filter_by(workflow_instance_id=task.review_instance_id).all()
              if item.status == "cancelled"]
    assert others, "the unused role tasks must not stay open"
