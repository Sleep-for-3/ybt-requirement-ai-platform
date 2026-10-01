"""Historical decision cases are supporting experience, never a regulatory basis."""
from __future__ import annotations

import pytest

from app.models import (
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
from app.services.agent import planner
from app.services.agent.tools import registry
from app.services.agent.tools.decision_cases import TOOL_KEY
from app.services.agent.tools.registry import ToolContext, require_tool
from app.services.auth.dependencies import Principal

TOOL = "search_decision_cases"


@pytest.fixture()
def scope(db_session):
    institution = Institution(institution_code="case-tool-bank", institution_name="案例工具银行",
                              institution_type="bank", status="active")
    user = User(username="case_tool_user", display_name="案例工具用户", status="active")
    db_session.add_all([institution, user])
    db_session.flush()
    project = Project(name="案例工具项目", institution_id=institution.id, project_status="active")
    db_session.add(project)
    db_session.flush()
    db_session.add(ProjectMembership(project_id=project.id, user_id=user.id,
                                     project_role="project_manager", status="active"))
    table = TargetTable(project_id=project.id, table_code="YBT_CT", table_name="案例表")
    db_session.add(table)
    db_session.flush()
    field = TargetField(project_id=project.id, target_table_id=table.id,
                        field_code="CT_BAL", field_name="案例余额")
    db_session.add(field)
    db_session.flush()
    task = AgentTask(institution_id=institution.id, project_id=project.id,
                     objective="案例工具验收：分析案例余额字段", scenario_key="mapping_resolution",
                     status="running", plan_version=1, created_by=user.id,
                     result_summary_json={"subject": {"target_field_id": field.id}})
    db_session.add(task)
    db_session.flush()
    step = AgentStep(task_id=task.id, plan_id=1, step_key="search_cases", order_index=1,
                     tool_key=TOOL, status="running", required=False,
                     input_json={"subject": {"target_field_id": field.id}}, optional_depends_on_json=[])
    db_session.add(step)
    db_session.flush()
    context = ToolContext(db=db_session, principal=Principal(user.id, user.username, user.display_name),
                          project=project, task=task, step=step, tool_input={"top_k": 5})
    return {"db": db_session, "project": project, "task": task, "step": step, "field": field,
            "context": context}


def _case(db, project, field) -> DecisionCase:
    case = DecisionCase(
        institution_id=project.institution_id, project_id=project.id, scenario_key="mapping_resolution",
        subject_type="target_field", subject_id=str(field.id), decision_type="field_mapping_decision",
        decision="映射到 CT_SRC", rationale="人工确认", evidence_refs_json=[], regulatory_refs_json=[],
        created_by=1, approved_by=1, confidence_source="human_decision", status="active",
    )
    db.add(case)
    db.commit()
    return case


def test_the_tool_is_registered_as_readonly_historical_evidence():
    spec = require_tool(TOOL_KEY)
    assert spec.risk_level == "low"
    assert spec.read_only is True
    assert spec.requires_human_confirmation is False
    assert spec.evidence_contract["fact_kinds"] == ["historical_decision"]
    assert spec.evidence_contract["policy_kinds"] == []
    assert spec.required_permissions == frozenset({"project.view"})


def test_hits_are_labelled_historical_and_never_policy(scope):
    db, context = scope["db"], scope["context"]
    _case(db, scope["project"], scope["field"])
    result = require_tool(TOOL_KEY).handler(context)

    assert result.status == "completed"
    assert result.policy_evidence == [], "a historical decision can never be policy evidence"
    assert result.facts and result.facts[0]["kind"] == "historical_decision"
    assert result.output["source_type"] == "historical_decision"
    assert "不能作为监管依据" in result.output["advisory_note"]
    for case in result.output["cases"]:
        assert case["source_type"] == "historical_decision"
        assert case["source_type"] != "policy_requirement"
    assert result.gaps == []


def test_no_case_produces_a_gap_not_a_claim(scope):
    result = require_tool(TOOL_KEY).handler(scope["context"])
    assert result.status == "skipped"
    assert result.facts == [] and result.claims == []
    assert [item["code"] for item in result.gaps] == ["no_historical_case"]
    assert "监管依据" in result.gaps[0]["message"]


def test_the_mapping_scenario_uses_cases_as_optional_context():
    draft = planner.deterministic_plan("这个监管字段应该映射源系统哪个字段？",
                                       scenario_key="mapping_resolution",
                                       subject={"target_field_id": 1})
    by_key = {step.step_key: step for step in draft.steps}
    assert "search_cases" in by_key
    assert by_key["search_cases"].required is False, "experience must never gate the plan"
    assert by_key["search_cases"].tool_key == TOOL_KEY
    assert by_key["prepare_mapping"].optional_depends_on == ["search_cases"]
    assert planner.validate_plan_draft(draft) == []
    assert registry.require_tool(by_key["search_cases"].tool_key).evidence_contract["policy_kinds"] == []
