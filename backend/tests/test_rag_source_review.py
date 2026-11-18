from copy import deepcopy
import json
from pathlib import Path

import pytest

from test_rag_component_tooling import load_script


def inputs():
    dataset={"dataset_version":"old", "cases":[{"case_id":"c","query":"原始问题", "split":"holdout"}]}
    decisions={"source_sha256":"qa", "anchor_prefixes":{"Y":"制度问答"},
               "decisions":[["c","Y3","pending","仅为建议"]]}
    holdout={"sources":{"I":"original.sql"},"cases":[["new","I",10,12,"归档脚本如何转换？","01映射甲"]]}
    corpus=[{"unit_id":1,"source":"archive.xlsx","file_hash":"qa","source_sheet_name":"制度问答","source_cell_range":"A3:D3",
             "enabled":True,"lifecycle":"active","document_id":1,"content_hash":"a","content":"建议甲"},
            {"unit_id":2,"unit_type":"sql_text","file_hash":"sql","source":"original.sql","source_sheet_name":None,"source_cell_range":None,"locator":{"line_start":5,"line_end":20},
             "enabled":True,"lifecycle":"active","document_id":2,"content_hash":"b","content":"CASE甲"}]
    corpus[1]['locator']['paragraph_index'] = 1
    return dataset,decisions,holdout,corpus


def test_observed_holdout_is_retired_and_new_document_is_independent():
    module=load_script("rag_review_dataset")
    result=module.build(*inputs(),"qa")
    assert [c['split'] for c in result['cases']]==['tuning','holdout']
    assert result['split_documents']=={'tuning':[1],'holdout':[2]}
    assert result['summary']['human_approved']==0
    assert all(c['review_status']=='agent_reviewed' for c in result['cases'])


def test_empty_independent_holdout_fails_closed():
    module = load_script("rag_review_dataset")
    dataset, decisions, holdout, corpus = inputs()
    holdout["cases"] = []
    with pytest.raises(ValueError, match="at least one case"):
        module.build(dataset, decisions, holdout, corpus, "qa")


def test_same_bytes_in_different_document_ids_do_not_create_independent_holdout():
    module=load_script("rag_review_dataset")
    values=inputs()
    values[3][1]['file_hash']='qa'
    with pytest.raises(ValueError,match='leakage'):
        module.build(*values,'qa')


@pytest.mark.parametrize('change',['source_hash','duplicate_review','missing_anchor','uncovered_sql'])
def test_binding_fails_closed_on_incomplete_or_changed_source(change):
    module=load_script("rag_review_dataset")
    dataset,decisions,holdout,corpus=inputs()
    if change=='source_hash':decisions['source_sha256']='other'
    if change=='duplicate_review':decisions['decisions']*=2
    if change=='missing_anchor':corpus[0]['source_cell_range']='A4:D4'
    if change=='uncovered_sql':corpus[1]['locator']['line_end']=11
    with pytest.raises(ValueError):
        module.build(dataset,decisions,holdout,corpus,'qa')


def test_metrics_do_not_mistake_context_candidates_for_used_citations():
    module=load_script("rag_review_replay")
    case={'gold':{'relevant_ids':[1,2],'roles':{'one':[1],'two':[2]}}}
    metrics=module.retrieval_metrics(case,[1,1,2],[1,2],[1])
    assert metrics['role_context']==2 and metrics['role_cited']==1
    assert metrics['all_roles_cited'] is False
    assert metrics['hit5']==1 and metrics['mrr']==1


def test_every_original_case_has_one_explicit_agent_review():
    directory=Path(__file__).resolve().parents[2]/'docs/evaluation/rag-upgrade-20261113'
    dataset=json.loads((directory/'dataset.json').read_text(encoding='utf-8'))
    reviewed=json.loads((directory/'source-adjudications-20261115.json').read_text(encoding='utf-8'))
    identities=[row[0] for row in reviewed['decisions']]
    assert len(identities)==len(set(identities))==104
    assert set(identities)=={c['case_id'] for c in dataset['cases']}
    assert reviewed['human_business_approval'] is False


def test_answer_audit_includes_actual_evidence_without_promoting_candidates():
    module = load_script('rag_review_answer_audit')
    case = {'query': 'q', 'gold': {'expected_summary': 'e', 'decision': 'pending', 'relevant_ids': [1]}}
    generated = {'cited_ids': [2], 'response': {'answer': 'a',
        'citations': [{'knowledge_unit_id': 2}, {'knowledge_unit_id': 3}]}}
    manifest = {'corpus': [{'unit_id': i, 'content': str(i)} for i in (1, 2, 3)]}
    request = module.request_for(case, generated, manifest)
    assert [u['unit_id'] for u in request['gold_sources']] == [1]
    assert [u['unit_id'] for u in request['actual_cited_sources']] == [2]


def test_answer_audit_refuses_unresolved_actual_citation():
    module = load_script('rag_review_answer_audit')
    case = {'query': 'q', 'gold': {'expected_summary': 'e', 'decision': 'pending', 'relevant_ids': []}}
    with pytest.raises(ValueError, match='Unresolved'):
        module.request_for(case, {'cited_ids': [99], 'response': {'citations': []}}, {'corpus': []})


def test_replay_assessment_separates_gold_actual_sources_and_context():
    module = load_script('rag_review_replay')
    case = {'query': 'q', 'gold': {'expected_summary': 'e', 'decision': 'pending',
                                  'relevant_ids': [1], 'source_lines': [10, 12]}}
    generated = {'cited_ids': [2, 2], 'context_ids': [2, 3], 'response': {
        'answer': 'a', 'cannot_answer_reason': 'missing reference role',
        'citations': [{'knowledge_unit_id': 2}, {'knowledge_unit_id': 3}]}}
    manifest = {'corpus': [{'unit_id': i, 'content': str(i), 'locator': {'line_start': i}}
                           for i in (1, 2, 3)]}
    request = module.assessment_request(case, generated, manifest)
    assert [u['unit_id'] for u in request['gold_sources']] == [1]
    assert [u['unit_id'] for u in request['actual_cited_sources']] == [2]
    assert request['context_source_ids'] == [2, 3]
    assert request['gold_source_ids_missing_from_context'] == [1]
    assert request['cannot_answer_reason'] == 'missing reference role'
    assert request['actual_cited_sources'][0]['locator'] == {'line_start': 2}
    assert 'content' not in str(request['context_source_ids'])


@pytest.mark.parametrize('mutation', ['not_returned', 'not_in_corpus', 'not_in_context'])
def test_replay_assessment_rejects_unresolved_or_outside_context_citations(mutation):
    module = load_script('rag_review_replay')
    case = {'query': 'q', 'gold': {'expected_summary': 'e', 'decision': 'pending', 'relevant_ids': []}}
    generated = {'cited_ids': [2], 'context_ids': [2],
                 'response': {'citations': [{'knowledge_unit_id': 2}]}}
    manifest = {'corpus': [{'unit_id': 2, 'content': 'evidence'}]}
    if mutation == 'not_returned':
        generated['response']['citations'] = []
    elif mutation == 'not_in_corpus':
        manifest['corpus'] = []
    else:
        generated['context_ids'] = [3]
    with pytest.raises(ValueError, match='Unresolved|context'):
        module.assessment_request(case, generated, manifest)


def test_supplemental_review_records_only_allowed_evaluator_changes(tmp_path):
    module = load_script('rag_review_answer_audit')
    evaluator = tmp_path/'backend/scripts/rag_review_replay.py'
    evaluator.parent.mkdir(parents=True)
    evaluator.write_text('new evaluator', encoding='utf-8')
    manifest = {'code_files': {'backend/scripts/rag_review_replay.py': 'old'}}
    changes = module.verify_generation_sources(manifest, tmp_path)
    assert changes == {'backend/scripts/rag_review_replay.py': {
        'generation_sha256': 'old', 'evaluation_sha256': module.sha(evaluator)}}


@pytest.mark.parametrize('name', ['backend/app/main.py', 'backend/scripts/rag_regression.py',
                                  'frontend/app/agent/page.tsx'])
def test_supplemental_review_refuses_changed_generation_code(tmp_path, name):
    module = load_script('rag_review_answer_audit')
    path = tmp_path/name
    path.parent.mkdir(parents=True)
    path.write_text('changed', encoding='utf-8')
    with pytest.raises(ValueError, match='Original generation code changed'):
        module.verify_generation_sources({'code_files': {name: 'old'}}, tmp_path)


def test_supplemental_summary_reports_empty_holdout_as_unmeasured():
    module = load_script('rag_review_answer_audit')
    report = {'metrics': {'tuning': {}, 'holdout': {}}, 'rows': [
        {'split': 'tuning', 'complete': True, 'unsupported_business_assertion': False},
        {'split': 'tuning', 'complete': False, 'unsupported_business_assertion': False}]}
    module.refresh_metrics(report)
    assert report['metrics']['tuning']['completeness_rate'] == 0.5
    assert report['metrics']['holdout']['end_to_end_completeness_rate'] is None
    assert report['metrics']['holdout']['completeness_samples'] == 0


def test_sql_summary_is_not_an_original_line_evidence_unit():
    module = load_script('rag_review_dataset')
    values = inputs()
    summary = {**values[3][1], 'unit_id': 3, 'content': 's',
        'locator': {'line_start': 1, 'line_end': 100}}
    values[3].append(summary)
    result = module.build(*values, 'qa')
    assert result['cases'][1]['gold']['relevant_ids'] == [2]


def test_summary_locator_cannot_replace_missing_original_sql_lines():
    module = load_script('rag_review_dataset')
    values = inputs()
    values[3].append({**values[3][1], 'unit_id': 3, 'content': 's',
        'locator': {'line_start': 1, 'line_end': 100}})
    values[3][1]['locator']['line_end'] = 11
    with pytest.raises(ValueError, match='not covered'):
        module.build(*values, 'qa')


@pytest.mark.parametrize('include_raw', [True, False])
def test_sql_summary_with_paragraph_locator_never_becomes_gold(include_raw):
    module = load_script('rag_review_dataset')
    values = inputs()
    raw = {**values[3][1], 'unit_type': 'sql_text'}
    summary = {**raw, 'unit_id': 3, 'unit_type': 'sql_summary', 'content': 'summary',
        'locator': {'paragraph_index': 1, 'line_start': 1, 'line_end': 100}}
    values[3][1:] = [raw, summary] if include_raw else [summary]
    if include_raw:
        assert module.build(*values, 'qa')['cases'][1]['gold']['relevant_ids'] == [2]
    else:
        with pytest.raises(ValueError, match='not covered'):
            module.build(*values, 'qa')
