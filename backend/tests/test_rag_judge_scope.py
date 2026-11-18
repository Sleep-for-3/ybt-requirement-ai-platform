"""Synthetic regressions for answer coverage and evidence sent to the judge."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app.core.settings import get_settings
from app.services.rag import citation_validator as validator
from app.services.rag import grounded_answer_service as grounded
from app.services.rag.citation_support import split_claims_all


def install_answer(monkeypatch, output=None, error=None):
    item = dict(knowledge_unit_id=1, content='余额以合同为准。',
                confidentiality_level='internal', rerank_score=1)
    monkeypatch.setattr(grounded.HybridRetriever, 'search',
                        lambda *a, **k: (SimpleNamespace(id=1), [item]))
    monkeypatch.setattr(grounded, 'document_citation', lambda *a: {
        'citation_id': 'knowledge-unit-1', 'knowledge_unit_id': 1,
        'quoted_content': item['content'], 'locator': {'block_id': 'unit-1'}})
    monkeypatch.setattr(grounded, 'validate_citations', lambda *a, **k: None)
    monkeypatch.setattr(grounded, '_index_freshness', lambda *a: {})
    monkeypatch.setattr(grounded, 'get_prompt_runtime', lambda *a, **k: None)
    monkeypatch.setattr(grounded, 'evidence_runtime', lambda x: x)
    monkeypatch.setattr(grounded, 'prepare_model_input', lambda *a, **k: 'synthetic')
    monkeypatch.setattr(grounded, 'build_execution_metadata', lambda *a, **k: {
        'execution_kind': 'degraded', 'degraded_reason': k.get('degraded_reason')})

    async def generate(*a, **k):
        if error:
            raise error
        return output, {}

    monkeypatch.setattr(grounded, 'execute_runtime_chat_with_metadata', generate)


def test_declared_claims_cannot_hide_unlisted_answer_claim(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), 'citation_support_check', 'judge')
    install_answer(monkeypatch, output={
        'answer': '余额以合同为准 [1]。利率以口头约定为准 [1]。',
        'supported_claims': ['余额以合同为准 [1]。'], 'confidence_level': 'high'})
    captured = []

    async def judge(*a, **k):
        captured.extend(k['claims'])
        return {}

    monkeypatch.setattr(grounded, 'check_citation_support', judge)
    asyncio.run(grounded.grounded_answer(db_session, 1, '余额和利率如何确定？'))
    assert any('利率以口头约定' in claim for claim in captured)


def test_generic_failure_keeps_degradation_contract(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), 'citation_support_check', 'off')
    install_answer(monkeypatch, error=RuntimeError('synthetic failure'))
    result = asyncio.run(grounded.grounded_answer(db_session, 1, '余额如何确定？'))
    assert result['answer_status'] == 'degraded'
    assert result['confidence_level'] == 'low'
    assert result['verification_status'] == 'not_run'
    assert result['degraded_reason'] == 'RuntimeError'
    assert result['trustworthiness']['grade'] == 'D'


@pytest.mark.parametrize('conflict_ids,expected', [(None, [1]), ([2], [1, 2]), ([], [1])])
def test_uncited_candidates_never_reach_judge(db_session, monkeypatch, conflict_ids, expected):
    monkeypatch.setattr(get_settings(), 'citation_support_check', 'judge')
    captured = []

    async def judge(_db, _key, _system, prompt, **kwargs):
        payload = json.loads(prompt)
        captured.append(payload)
        verdicts = [dict(citation_id=c['citation_id'], verdict='supported', dimension='citation')
                    for c in payload['citations']]
        verdicts += [dict(claim_id=c['claim_id'], verdict='supported', dimension='claim')
                     for c in payload['claims']]
        return verdicts, [], {}, None

    monkeypatch.setattr(validator, 'run_judge_with_conflicts', judge)
    citations = [dict(citation_id=f'knowledge-unit-{i}', knowledge_unit_id=i,
                      quoted_content='余额以合同为准。') for i in [1, 2, 3]]
    result = asyncio.run(validator.check_citation_support(
        db_session, citations, answer='余额以合同为准 [1]。',
        referenced_unit_ids=[1], conflict_unit_ids=conflict_ids))
    assert [c['knowledge_unit_id'] for c in captured[0]['citations']] == expected
    assert result['citation_count'] == len(expected)
    assert sorted(result['unreferenced_evidence_ids']) == sorted(set([1, 2, 3]) - set(expected))


def test_explicit_no_references_does_not_judge_all_candidates(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), 'citation_support_check', 'judge')

    async def forbidden(*a, **k):
        pytest.fail('Unreferenced evidence was sent to the judge')

    monkeypatch.setattr(validator, 'run_judge_with_conflicts', forbidden)
    result = asyncio.run(validator.check_citation_support(
        db_session, [dict(knowledge_unit_id=1, quoted_content='余额以合同为准。')],
        answer='无法确认。', referenced_unit_ids=[]))
    assert result['skip_reason'] == 'no_citations'
    assert result['citation_count'] == 0


def test_atomic_claims_keep_numeric_semicolon_codes():
    claims = split_claims_all('机构建议码值01;03 [1]；正式反馈另列。')
    assert claims == ['机构建议码值01;03 [1]；', '正式反馈另列。']


def test_body_coverage_deduplicates_declared_claims_and_orphan_citation():
    first = '余额以合同为准。'
    second = '利率以合同约定为准。'
    assert grounded._judge_claims(first + second + ' [1]', [first, second]) == [first, second]


def test_body_precedes_extra_declared_claims_for_bounded_judge():
    assert grounded._judge_claims('正文结论 [1]。', ['摘要补充。']) == ['正文结论 [1]。', '摘要补充。']
