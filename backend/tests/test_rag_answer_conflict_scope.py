"""Real-regression failure shapes with synthetic, non-sensitive source text."""
import asyncio
from types import SimpleNamespace

import pytest

from app.core.settings import get_settings
from app.services.code_extraction import extract_code_values, extract_field_codes
from app.services.rag import grounded_answer_service as grounded


def item(identity, field, content, **kwargs):
    return dict(knowledge_unit_id=identity, target_field_code=field, content=content,
                authority_rank=5, confidentiality_level='internal', rerank_score=1, **kwargs)


@pytest.mark.parametrize('rule', ['JYA03-47', 'JYJL-A03-3', 'RULE_12-99', 'JYA03-47-02'])
def test_rule_identifiers_are_not_business_values(rule):
    assert extract_code_values(f'参考校验规则【{rule}】；柜员类型填01', affirmative_only=True) == {'01'}


def test_real_codes_and_identifiers_remain_separate():
    assert extract_code_values('码值01-营销、02-贷款；不得填99', affirmative_only=True) == {'01', '02'}
    assert extract_field_codes('字段A030016与b050007、H110002、J020107') == {
        'A030016', 'B050007', 'H110002', 'J020107'}
    assert extract_field_codes('XA030016 A0300169 xx_B050007') == set()


def test_rule_number_cannot_manufacture_same_field_conflict():
    rows = [item(1, 'A030016', '柜员类型为01时按岗位编号校验'),
            item(2, 'A030016', '柜员类型为01时参考规则JYA03-47按岗位编号校验')]
    assert grounded._evidence_conflicts(rows) == []


@pytest.mark.parametrize('judge_path', ['off', 'pass', 'failure'])
def test_other_field_conflict_cannot_downgrade_answer(db_session, monkeypatch, judge_path):
    rows = [item(1, 'E010007', '归档反馈：产品类别E010007填0201。'),
            item(2, 'E010005', '科目类型E010005只能填01。'),
            item(3, 'E010005', '科目类型E010005只能填02。')]
    monkeypatch.setattr(get_settings(), 'citation_support_check', 'off' if judge_path == 'off' else 'judge')
    monkeypatch.setattr(grounded.HybridRetriever, 'search', lambda *a, **k: (SimpleNamespace(id=1), rows))
    monkeypatch.setattr(grounded, 'document_citation', lambda row, _project: {
        'knowledge_unit_id': row['knowledge_unit_id'], 'quoted_content': row['content'],
        'citation_id': f"knowledge-unit-{row['knowledge_unit_id']}", 'locator': {'block_id': 'synthetic'}})
    monkeypatch.setattr(grounded, 'validate_citations', lambda *a, **k: None)
    monkeypatch.setattr(grounded, '_index_freshness', lambda *a: {})
    monkeypatch.setattr(grounded, 'get_prompt_runtime', lambda *a: None)
    monkeypatch.setattr(grounded, 'evidence_runtime', lambda runtime: runtime)
    monkeypatch.setattr(grounded, 'prepare_model_input', lambda *a, **k: 'synthetic')

    async def generate(*a, **k):
        return {'answer': '归档记录的产品类别E010007填0201 [1]。'}, {}

    captured = []

    async def judge(*a, **k):
        captured.append(k.get('conflict_unit_ids'))
        return {'verification': 'degraded' if judge_path == 'failure' else 'verified'}

    monkeypatch.setattr(grounded, 'execute_runtime_chat_with_metadata', generate)
    monkeypatch.setattr(grounded, 'check_citation_support', judge)
    monkeypatch.setattr(grounded, 'claim_support_summary', lambda support: {
        'verification': support['verification'], 'supported_claims': [],
        'unsupported_claims': [], 'unknown_claims': []})
    result = asyncio.run(grounded.grounded_answer(db_session, 1, '归档产品类别E010007如何填报？'))
    assert result['conflicts'] == []
    assert result['conflict_diagnostics']['candidate_conflict_count'] == 1
    assert result['conflict_diagnostics']['out_of_scope_count'] == 1
    assert result['answer_status'] == ('needs_confirmation' if judge_path == 'failure' else 'grounded')
    if judge_path != 'off':
        assert captured == [None]
    if judge_path == 'failure':
        assert result['confidence_level'] == 'low'
        assert result['trustworthiness']['grade'] not in {'A', 'B'}


def test_uncited_conflicting_peer_of_used_field_is_retained():
    rows = [item(1, 'F250007', '合作方式只能填01'),
            item(2, 'F250007', '合作方式只能填02'),
            item(3, 'F250007', '合作方式按归档说明填报')]
    conflicts = grounded._evidence_conflicts(rows, relevant_items=[rows[2]], query='合作方式如何填报？')
    assert conflicts and len(conflicts[0]['citation_ids']) == 3


def test_explicit_conflict_and_query_field_cannot_be_hidden_by_citations():
    rows = [item(1, 'F250007', '合作方式只能填01'),
            item(2, 'F250007', '合作方式只能填02'),
            item(3, 'E010007', '产品类别填0201')]
    assert grounded._evidence_conflicts(rows, relevant_items=[rows[2]], query='F250007如何填报？')
    for row in rows[:2]:
        row['metadata_json'] = {'conflict_key': 'MANUALLY_FLAGGED'}
    assert grounded._evidence_conflicts(rows, relevant_items=[rows[2]], query='其他问题')


def test_unknown_answer_scope_stays_conservative():
    rows = [item(1, 'F250007', '合作方式只能填01'), item(2, 'F250007', '合作方式只能填02')]
    unknown = dict(knowledge_unit_id=3, content='泛化摘要', authority_rank=2)
    assert grounded._evidence_conflicts(rows, relevant_items=[unknown], query='如何填报？')


def test_query_field_name_retains_conflict_despite_other_cited_field():
    rows = [item(1, 'E010005', '数据项名称：科目类型；只能填01'),
            item(2, 'E010005', '数据项名称：科目类型；只能填02'),
            item(3, 'E010007', '数据项名称：产品类别；填0201')]
    assert grounded._evidence_conflicts(rows, relevant_items=[rows[2]], query='科目类型如何填报？')


def test_partly_unknown_answer_scope_stays_conservative():
    rows = [item(1, 'E010005', '只能填01'), item(2, 'E010005', '只能填02'),
            item(3, 'E010007', '产品类别填0201')]
    unknown = dict(knowledge_unit_id=4, content='未标注字段的补充证据', authority_rank=2)
    assert grounded._evidence_conflicts(rows, relevant_items=[rows[2], unknown], query='如何填报？')
