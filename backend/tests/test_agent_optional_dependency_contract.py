"""A required answer must not silently inherit an optional historical branch."""
import asyncio
from types import SimpleNamespace

import pytest

from app.services.agent import planner
from app.services.agent.planner import PlanDraft, PlannedStep, validate_plan_draft_detailed
from app.services.llm.mock import MockLLMService


def draft(required=False, optional_edge=False, answer_required=True):
    return PlanDraft(objective='Explain the archived cooperation code',
        scenario_key='knowledge_question', steps=[
            PlannedStep(step_key='history', tool_key='search_decision_cases',
                        reason='Supplemental historical context', required=required),
            PlannedStep(step_key='answer', tool_key='answer_knowledge_question',
                        reason='Answer from governed sources', required=answer_required,
                        depends_on=[] if optional_edge else ['history'],
                        optional_depends_on=['history'] if optional_edge else []),
        ])


def test_required_answer_rejects_hard_dependency_on_optional_history():
    issues = validate_plan_draft_detailed(draft())
    matches = [i for i in issues if i.code == 'required_depends_on_optional_step']
    assert len(matches) == 1
    assert matches[0].step_key == 'answer'
    assert matches[0].repairable is True


def test_knowledge_question_requires_a_required_answer_step():
    plan = draft()
    no_answer = plan.model_copy(update={'steps': [plan.steps[0]]})
    optional_answer = plan.model_copy(update={
        'steps': [plan.steps[0], plan.steps[1].model_copy(update={'required': False})],
    })

    for invalid in (no_answer, optional_answer):
        issues = validate_plan_draft_detailed(invalid)
        assert any(issue.code == 'missing_required_knowledge_answer' for issue in issues)


@pytest.mark.parametrize('options', [
    {'required': True}, {'optional_edge': True}, {'answer_required': False},
])
def test_explicit_required_and_optional_contracts_remain_valid(options):
    issues = validate_plan_draft_detailed(draft(**options))
    if options.get('answer_required') is False:
        assert any(issue.code == 'missing_required_knowledge_answer' for issue in issues)
    else:
        assert issues == []


def test_other_workflows_keep_explicit_hard_dependency_semantics():
    plan = draft().model_copy(update={'scenario_key': 'regulatory_field_analysis'})
    assert validate_plan_draft_detailed(plan) == []


@pytest.mark.parametrize('optional_edge', [False, True])
def test_transitive_history_dependency_obeys_optional_edge_boundary(optional_edge):
    plan = draft()
    middle = PlannedStep(step_key='middle', tool_key='summarize_evidence', reason='Collect context',
        depends_on=[] if optional_edge else ['history'],
        optional_depends_on=['history'] if optional_edge else [])
    plan = PlanDraft(objective=plan.objective, scenario_key=plan.scenario_key,
        steps=[plan.steps[0], middle, plan.steps[1].model_copy(update={'depends_on': ['middle']})])
    codes = [i.code for i in validate_plan_draft_detailed(plan)]
    assert ('required_depends_on_optional_step' in codes) is not optional_edge


def test_planning_prompt_exposes_optional_dependency_contract():
    prompt = planner.plan_input_text('Explain the code', 'knowledge_question', {}, {})
    assert '"optional_depends_on"' in prompt
    assert 'search_decision_cases' in prompt


def test_mock_filler_plan_is_rejected_and_bounded_repair_falls_back(monkeypatch):
    calls = []
    mock = MockLLMService()
    monkeypatch.setattr(planner, 'get_prompt_runtime',
        lambda *_: SimpleNamespace(system_prompt='', user_template=''))

    async def fake_chat(*args, **kwargs):
        calls.append(args[3])
        return await mock.chat_json('[AGENT_PLANNER_V1]', args[3]), {}

    monkeypatch.setattr(planner, 'execute_runtime_chat_with_metadata', fake_chat)
    result, metadata, reason = asyncio.run(planner.plan_with_llm(
        None, SimpleNamespace(id=1), objective='Explain the archived cooperation code',
        scenario_key='knowledge_question', subject={},
    ))

    assert result is None
    assert reason == 'planner_plan_invalid'
    assert metadata['planner_attempts'] == len(calls) == 2
    assert 'missing_required_knowledge_answer' in metadata['plan_validation_codes']


@pytest.mark.parametrize('repair_succeeds', [False, True])
def test_optional_history_contract_reuses_bounded_planner_repair(monkeypatch, repair_succeeds):
    calls = []
    monkeypatch.setattr(planner, 'get_prompt_runtime',
        lambda *_: SimpleNamespace(system_prompt='', user_template=''))

    async def fake_chat(*args, **kwargs):
        calls.append(args[3])
        fixed = repair_succeeds and len(calls) == 2
        return draft(optional_edge=fixed).model_dump(), {}

    monkeypatch.setattr(planner, 'execute_runtime_chat_with_metadata', fake_chat)
    result, metadata, reason = asyncio.run(planner.plan_with_llm(None, SimpleNamespace(id=1),
        objective='Explain the archived cooperation code', scenario_key='knowledge_question', subject={}))
    assert len(calls) == metadata['planner_attempts'] == 2
    if repair_succeeds:
        assert result is not None and reason is None
        assert result.steps[1].optional_depends_on == ['history']
    else:
        assert result is None and reason == 'planner_plan_invalid'
        assert 'required_depends_on_optional_step' in metadata['plan_validation_codes']
