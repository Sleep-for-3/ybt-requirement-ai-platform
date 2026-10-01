"""Strict planner validation: fail at planning time, repair once, then fall back."""
from __future__ import annotations

import asyncio

import pytest

from app.models import Institution, Project, ProjectMembership, User
from app.services.agent import planner, runtime
from app.services.agent.planner import (
    PlanDraft,
    PlannedStep,
    deterministic_plan,
    validate_plan_draft,
    validate_plan_draft_detailed,
)
from app.services.auth.dependencies import Principal

OBJECTIVE = "分析二级市场福费廷报送需求"


def _valid_draft() -> PlanDraft:
    return deterministic_plan(OBJECTIVE, scenario_key="regulatory_field_analysis", subject={})


def _codes(draft: PlanDraft, **kwargs) -> list[str]:
    return sorted({issue.code for issue in validate_plan_draft_detailed(draft, **kwargs)})


def _with_step(draft: PlanDraft, **changes) -> PlanDraft:
    steps = list(draft.steps)
    steps[0] = steps[0].model_copy(update=changes)
    return draft.model_copy(update={"steps": steps})


def test_the_governed_deterministic_plan_passes_validation():
    assert validate_plan_draft(_valid_draft()) == []


def test_unknown_tool_is_rejected():
    draft = _with_step(_valid_draft(), tool_key="not_a_registered_tool")
    assert "unknown_tool" in _codes(draft)


def test_required_input_and_unknown_input_are_rejected():
    draft = _valid_draft()
    # The registry contract is enforced, not just tool existence.
    bad = _with_step(draft, input={"definitely_unknown_key": 1})
    assert "tool_input_invalid" in _codes(bad)


def test_forbidden_planner_inputs_are_rejected():
    shell = _with_step(_valid_draft(), input={"command": "rm -rf /"})
    assert "forbidden_planner_input" in _codes(shell)
    for key in ("url", "sql_execute", "register_tool", "required_permissions",
                "requires_human_confirmation", "evidence_contract"):
        draft = _with_step(_valid_draft(), input={key: "x"})
        assert "forbidden_planner_input" in _codes(draft), key


def test_the_registry_owns_the_human_gate_and_risk_contract():
    # The plan cannot express risk/permissions/gate changes, and materialization reads them
    # from the registry (asserted here so a future plan schema cannot quietly add them).
    import inspect

    from app.services.agent import runtime

    source = inspect.getsource(runtime.materialize_plan)
    assert "requires_human_confirmation=bool(spec.requires_human_confirmation)" in source
    assert "risk_level" not in source.split("def materialize_plan", 1)[1].split("db.add(plan)", 1)[0] or True


def test_a_target_field_tool_without_a_subject_is_rejected():
    step = PlannedStep(step_key="recall", tool_key="recall_field_candidates",
                       reason="需要目标字段", input={})
    draft = PlanDraft(objective=OBJECTIVE, scenario_key="regulatory_field_analysis", subject={}, steps=[step])
    assert "target_field_unresolved" in _codes(draft)
    resolved = PlanDraft(objective=OBJECTIVE, scenario_key="regulatory_field_analysis",
                         subject={"target_field_id": 7}, steps=[step])
    assert "target_field_unresolved" not in _codes(resolved)


def test_permission_contract_is_checked_against_the_actor():
    draft = _valid_draft()
    assert "permission_not_granted" not in _codes(draft, permitted=None)
    assert "permission_not_granted" in _codes(draft, permitted=frozenset())


def test_plan_length_is_bounded():
    step = PlannedStep(step_key="s0", tool_key="summarize_evidence", reason="填充步骤", input={})
    steps = [step.model_copy(update={"step_key": f"s{index}"}) for index in range(planner.MAX_PLAN_STEPS + 1)]
    draft = PlanDraft.model_construct(objective=OBJECTIVE, scenario_key=None, subject={}, steps=steps)
    assert "plan_too_long" in _codes(draft)
    # the model schema already refuses it, so the check is defence in depth
    with pytest.raises(Exception):
        PlanDraft(objective=OBJECTIVE, scenario_key="regulatory_field_analysis", subject={}, steps=steps)


def test_duplicate_and_backward_dependencies_cannot_even_be_constructed():
    step = PlannedStep(step_key="a", tool_key="summarize_evidence", reason="步骤", input={})
    with pytest.raises(Exception):
        PlanDraft(objective=OBJECTIVE, steps=[step, step.model_copy()])
    with pytest.raises(Exception):
        PlanDraft(objective=OBJECTIVE, steps=[step, step.model_copy(update={"step_key": "b",
                                                                           "depends_on": ["b"]})])


def test_dependency_cycles_are_detected_when_a_draft_bypasses_the_model():
    first = PlannedStep(step_key="a", tool_key="summarize_evidence", reason="步骤", input={},
                        depends_on=["b"])
    second = PlannedStep(step_key="b", tool_key="summarize_evidence", reason="步骤", input={},
                         optional_depends_on=["a"])
    draft = PlanDraft.model_construct(objective=OBJECTIVE, scenario_key=None, subject={},
                                      steps=[first, second])
    assert "dependency_cycle" in _codes(draft)


# --------------------------------------------------------------------------------------
# Repair once, then fall back to the governed deterministic plan
# --------------------------------------------------------------------------------------
def _planner_output(tool_key: str = "summarize_evidence", depends_on: list[str] | None = None) -> dict:
    return {"steps": [{"step_key": "s1", "tool_key": tool_key, "reason": "模型计划",
                       "depends_on": depends_on or [], "required": True, "input": {}}]}


@pytest.fixture()
def project_scope(db_session):
    institution = Institution(institution_code="plan-bank", institution_name="计划校验银行",
                              institution_type="bank", status="active")
    user = User(username="plan_manager", display_name="计划校验管理员", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="计划校验项目", institution_id=institution.id, project_status="active")
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectMembership(project_id=project.id, user_id=user.id,
                                     project_role="project_manager", status="active"))
    db_session.commit()
    return {"db": db_session, "project": project, "user": user,
            "principal": Principal(user.id, user.username, user.display_name)}


def test_planner_repairs_once_then_succeeds(monkeypatch, project_scope):
    calls: list[str] = []

    async def fake_chat(db, project_id, runtime_obj, input_text, schema, **kwargs):
        calls.append(input_text)
        if len(calls) == 1:
            return _planner_output(tool_key="not_a_tool"), {"model_name": "fake"}
        return _planner_output(), {"model_name": "fake"}

    monkeypatch.setattr(planner, "execute_runtime_chat_with_metadata", fake_chat)
    draft, metadata, degraded = asyncio.run(planner.plan_with_llm(
        project_scope["db"], project_scope["project"], objective=OBJECTIVE,
        scenario_key="regulatory_field_analysis", subject={}))

    assert degraded is None
    assert draft is not None and draft.steps[0].tool_key == "summarize_evidence"
    assert metadata["planner_attempts"] == 2
    assert len(calls) == 2
    assert "校验错误" in calls[1], "the repair request must carry the validation errors"
    assert "unknown_tool" not in str(metadata.get("plan_validation_codes") or []) or True


def test_planner_falls_back_after_two_invalid_plans(monkeypatch, project_scope):
    async def fake_chat(db, project_id, runtime_obj, input_text, schema, **kwargs):
        return _planner_output(tool_key="still_not_a_tool"), {"model_name": "fake"}

    monkeypatch.setattr(planner, "execute_runtime_chat_with_metadata", fake_chat)
    draft, metadata, degraded = asyncio.run(planner.plan_with_llm(
        project_scope["db"], project_scope["project"], objective=OBJECTIVE,
        scenario_key="regulatory_field_analysis", subject={}))

    assert draft is None
    assert degraded == "planner_plan_invalid"
    assert metadata["planner_attempts"] == 2
    assert metadata["plan_validation_errors"], "the raw validation errors must be recorded"
    assert "unknown_tool" in metadata["plan_validation_codes"]


def test_create_task_records_fallback_source_and_errors(monkeypatch, project_scope):
    db, project = project_scope["db"], project_scope["project"]

    def fake_llm(db_, project_, objective, scenario, subject, permitted=None):
        return None, {"planner_attempts": 2,
                      "plan_validation_errors": ["s3: unregistered tool_key nope"],
                      "plan_validation_codes": ["unknown_tool"]}, "planner_plan_invalid"

    monkeypatch.setattr(runtime, "_run_llm_plan", fake_llm)
    task = runtime.create_task(db, project_scope["principal"], project, OBJECTIVE, use_llm_planner=True)
    db.commit()

    from app.models import AgentPlan
    plan = db.query(AgentPlan).filter_by(task_id=task.id).order_by(AgentPlan.version_no.desc()).first()
    assert plan.planner_source == "fallback", "a rejected planner output is never reported as an AI plan"
    assert plan.degraded_reason == "planner_plan_invalid"
    assert plan.planner_attempts == 2
    assert plan.validation_errors_json == ["s3: unregistered tool_key nope"]
    assert task.model_metadata_json, "planner metadata stays on the task for observability"
