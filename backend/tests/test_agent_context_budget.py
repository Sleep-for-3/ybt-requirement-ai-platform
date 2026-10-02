"""Context budget: one step can never persist unbounded payloads."""
from __future__ import annotations

import json

import pytest

from app.models import AgentStep, AgentTask, Institution, Project, ProjectMembership, TargetField, TargetTable, User
from app.services.agent import planner, runtime, state_machine as sm
from app.services.agent.tools.registry import AgentToolSpec, ToolResult, register_tool
from app.services.auth.dependencies import Principal

_SEQ = {"n": 0}


def _register(tool_key: str, handler, **overrides) -> str:
    _SEQ["n"] += 1
    values = dict(
        display_name=tool_key, description=f"上下文预算测试工具 {tool_key}",
        input_schema={"type": "object", "properties": {}}, output_schema={"type": "object", "properties": {}},
        required_permissions=frozenset({"project.view"}), risk_level="low", timeout_seconds=5,
        retry_policy={"max_attempts": 1}, read_only=True, requires_human_confirmation=False,
        evidence_contract={"fact_kinds": [], "artifact_types": []}, audit_fields=(), handler=handler,
    )
    values.update(overrides)
    key = f"{tool_key}_{_SEQ['n']}"
    register_tool(AgentToolSpec(tool_key=key, **values))
    return key


def _huge(ctx) -> ToolResult:
    return ToolResult(
        output={"note": "x" * 60000},
        facts=[{"id": f"fact-{index}", "kind": "metadata"} for index in range(400)],
        claims=[{"claim_type": "observed_fact", "text": "claim", "fact_ids": ["fact-0"]} for _ in range(200)],
        evidence_refs=[f"ref-{index}" for index in range(900)],
        gaps=[{"code": f"gap_{index}", "message": "g"} for index in range(300)],
        step_output={"big": "y" * 80000},
    )


@pytest.fixture()
def scope(db_session):
    institution = Institution(institution_code="budget-bank", institution_name="预算银行",
                              institution_type="bank", status="active")
    user = User(username="budget_user", display_name="预算用户", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="预算项目", institution_id=institution.id, project_status="active")
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectMembership(project_id=project.id, user_id=user.id,
                                     project_role="project_manager", status="active"))
    table = TargetTable(project_id=project.id, table_code="YBT_BG", table_name="预算表")
    db_session.add(table)
    db_session.flush()
    field = TargetField(project_id=project.id, target_table_id=table.id,
                        field_code="BG_BAL", field_name="预算余额")
    db_session.flush()
    return {"db": db_session, "project": project, "user": user, "field": field,
            "principal": Principal(user.id, user.username, user.display_name)}


def _run(db, scope, tool_key: str) -> AgentTask:
    task = AgentTask(institution_id=scope["project"].institution_id, project_id=scope["project"].id,
                     objective="上下文预算验收：分析预算余额字段", scenario_key="regulatory_field_analysis",
                     status=sm.TASK_CREATED, plan_version=1, created_by=scope["user"].id,
                     result_summary_json={"subject": {"target_field_id": scope["field"].id}})
    db.add(task)
    db.flush()
    draft = planner.PlanDraft(objective=task.objective, scenario_key=task.scenario_key, subject={},
                              steps=[planner.PlannedStep(step_key="big", tool_key=tool_key,
                                                         reason="超大输出步骤", input={})])
    runtime.materialize_plan(db, task, draft, planner_source="deterministic")
    db.commit()
    job = runtime.submit_task(db, scope["project"], scope["principal"], task)
    runtime.run_agent_task(db, job)
    db.refresh(task)
    return task


def test_step_payloads_are_capped_by_the_context_budget(scope):
    db = scope["db"]
    tool_key = _register("budget_huge", _huge)
    task = _run(db, scope, tool_key)
    step = db.query(AgentStep).filter_by(task_id=task.id, step_key="big").one()
    assert step.status == sm.STEP_COMPLETED
    summary = step.output_summary_json or {}

    assert len(summary["facts"]) == runtime.MAX_FACTS_PER_STEP
    assert len(summary["claims"]) == runtime.MAX_CLAIMS_PER_STEP
    assert len(summary["gaps"]) == runtime.MAX_GAPS_PER_STEP
    assert len(step.evidence_refs_json) == runtime.MAX_EVIDENCE_REFS_PER_STEP

    # Whichever stage truncates first, what is persisted must stay inside the budget.
    carry = summary["carry"]
    encoded = json.dumps(carry, ensure_ascii=False, default=str)
    assert len(encoded) <= runtime.MAX_CARRY_CHARS, "carry must stay inside the context budget"


def test_bounded_payload_truncates_oversized_values():
    big = {"data": "z" * (runtime.MAX_CARRY_CHARS + 5000)}
    bounded = runtime._bounded_payload(big)
    assert bounded["truncated"] is True
    assert bounded["reason"] == "context_budget"
    assert bounded["original_chars"] > runtime.MAX_CARRY_CHARS
    assert runtime._bounded_payload({"small": 1}) == {"small": 1}


def test_a_small_payload_is_carried_untouched(scope):
    db = scope["db"]

    def small(ctx) -> ToolResult:
        return ToolResult(output={"ok": True}, step_output={"ran": True},
                          facts=[{"id": "f1", "kind": "metadata"}])

    tool_key = _register("budget_small", small)
    task = _run(db, scope, tool_key)
    summary = db.query(AgentStep).filter_by(task_id=task.id, step_key="big").one().output_summary_json
    assert summary["carry"] == {"ran": True}
    assert len(summary["facts"]) == 1


def test_the_prompt_digest_stays_within_its_own_cap(scope):
    db = scope["db"]
    from app.services.agent import observation

    tool_key = _register("budget_huge2", _huge)
    task = _run(db, scope, tool_key)
    digest = observation.observation_digest(observation.observation_state(db, task))
    assert len(digest) <= observation.MAX_DIGEST_CHARS
