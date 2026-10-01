"""Observe state: bounded, structured, and free of raw document text."""
from __future__ import annotations

import json

import pytest

from app.models import (
    AgentArtifact,
    AgentHumanDecision,
    AgentStep,
    AgentTask,
    Institution,
    Project,
    ProjectMembership,
    TargetField,
    TargetTable,
    User,
)
from app.services.agent import observation, state_machine as sm
from app.services.auth.dependencies import Principal


@pytest.fixture()
def scope(db_session):
    institution = Institution(institution_code="obs-bank", institution_name="观察状态银行",
                              institution_type="bank", status="active")
    user = User(username="obs_manager", display_name="观察状态管理员", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="观察状态项目", institution_id=institution.id, project_status="active")
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectMembership(project_id=project.id, user_id=user.id,
                                     project_role="project_manager", status="active"))
    table = TargetTable(project_id=project.id, table_code="YBT_OBS", table_name="观察状态表")
    db_session.add(table)
    db_session.flush()
    field = TargetField(project_id=project.id, target_table_id=table.id,
                        field_code="OBS_BAL", field_name="观察状态余额")
    db_session.add(field)
    db_session.flush()
    task = AgentTask(institution_id=institution.id, project_id=project.id,
                     objective="观察状态验收：分析观察状态余额字段", scenario_key="regulatory_field_analysis",
                     status=sm.TASK_BLOCKED, plan_version=1, created_by=user.id, replanning_count=1,
                     result_summary_json={
                         "subject": {"target_field_id": field.id, "target_field_code": "OBS_BAL"},
                         "subject_resolution": {"status": "resolved", "rationale": "唯一候选"},
                         "incomplete": True,
                     })
    db_session.add(task)
    db_session.flush()
    db_session.add(AgentStep(
        task_id=task.id, plan_id=1, step_key="search_policy", order_index=1,
        tool_key="search_regulatory_knowledge", status=sm.STEP_COMPLETED, required=True,
        evidence_count=2, gap_codes_json=[],
        output_summary_json={"summary": {"summary": "命中 2 条监管条款", "note": "x" * 400},
                             "facts": [{"kind": "knowledge_clause"}, {"kind": "metadata"}]},
        input_json={"query": "观察状态"}, optional_depends_on_json=[],
    ))
    db_session.add(AgentStep(
        task_id=task.id, plan_id=1, step_key="generate_requirement_document", order_index=2,
        tool_key="generate_requirement_document", status=sm.STEP_SKIPPED, required=True,
        evidence_count=0, gap_codes_json=["dependency_gap", "skill_binding_missing"],
        output_summary_json={"summary": "跳过"}, input_json={}, optional_depends_on_json=[],
    ))
    db_session.add(AgentArtifact(task_id=task.id, artifact_type="gap_report", title="缺口报告",
                                 status="draft", summary_json={}, evidence_refs_json=[]))
    db_session.commit()
    return {"db": db_session, "project": project, "task": task, "field": field,
            "principal": Principal(user.id, user.username, user.display_name)}


def test_state_is_structured_and_bounded(scope):
    state = observation.observation_state(scope["db"], scope["task"])
    assert state["objective"].startswith("观察状态验收")
    assert state["scenario"]["scenario_key"] == "regulatory_field_analysis"
    assert state["subject"]["target_field_code"] == "OBS_BAL"
    assert [step["step_key"] for step in state["completed_steps"]] == [
        "search_policy", "generate_requirement_document"]
    assert state["evidence_summary"]["evidence_items"] == 2
    assert state["evidence_summary"]["kinds"] == {"knowledge_clause": 1, "metadata": 1}
    assert state["evidence_summary"]["coverage"] == 0.5
    assert state["remaining_budget"]["steps_pending"] == 0
    assert state["remaining_budget"]["replans_used"] == 1
    assert {gap["code"] for gap in state["gaps"]} >= {"dependency_gap", "skill_binding_missing"}
    # A completed step's summary is clipped, never the whole body.
    assert all(len(step["summary"]) <= observation.SUMMARY_CHARS for step in state["completed_steps"])


def test_unresolved_questions_explain_the_gaps(scope):
    state = observation.observation_state(scope["db"], scope["task"])
    questions = " ".join(state["unresolved_questions"])
    assert "技能未发布" in questions
    assert "上游步骤被跳过" in questions
    assert "不完整" in questions


def test_available_tools_respect_actor_permissions(scope):
    all_tools = observation.observation_state(scope["db"], scope["task"])["available_tools"]
    assert "search_regulatory_knowledge" in all_tools
    restricted = observation.observation_state(scope["db"], scope["task"],
                                               permitted=frozenset({"project.view"}))["available_tools"]
    assert "search_regulatory_knowledge" not in restricted
    assert set(restricted) <= set(all_tools)


def test_digest_is_compact_json_safe_text(scope):
    state = observation.observation_state(scope["db"], scope["task"])
    digest = observation.observation_digest(state)
    assert "业务目标" in digest and "缺口" in digest and "预算" in digest
    assert len(digest) <= observation.MAX_DIGEST_CHARS
    assert "x" * 200 not in digest, "raw long bodies must not leak into the planner prompt"
    json.dumps(state, ensure_ascii=False)  # the state must stay serialisable for the API


def test_digest_never_exceeds_the_cap_even_with_many_steps(scope):
    db, task = scope["db"], scope["task"]
    for index in range(40):
        db.add(AgentStep(
            task_id=task.id, plan_id=1, step_key=f"bulk_{index}", order_index=100 + index,
            tool_key="summarize_evidence", status=sm.STEP_COMPLETED, required=False,
            evidence_count=1, gap_codes_json=[f"gap_{index}"],
            output_summary_json={"summary": "步骤摘要" * 40}, input_json={},
            optional_depends_on_json=[],
        ))
    db.commit()
    state = observation.observation_state(db, task)
    assert len(state["completed_steps"]) <= observation.MAX_STEPS_IN_STATE
    assert len(state["gaps"]) <= observation.MAX_GAPS_IN_STATE
    assert len(observation.observation_digest(state)) <= observation.MAX_DIGEST_CHARS


def test_human_decisions_are_included_with_their_step(scope):
    db, task = scope["db"], scope["task"]
    step = db.query(AgentStep).filter_by(task_id=task.id, step_key="search_policy").one()
    db.add(AgentHumanDecision(task_id=task.id, step_id=step.id, decision="approve",
                              comment="证据充分", edited_payload_json={}, context_hash="h",
                              decided_by=task.created_by))
    db.commit()
    state = observation.observation_state(db, task)
    assert state["human_decisions"][0]["step_key"] == "search_policy"
    assert state["human_decisions"][0]["decision"] == "approve"
