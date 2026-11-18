"""Delegated source approval is explicit and distinct from human signature."""
from copy import deepcopy

from test_rag_component_tooling import load_script


def dataset(approved=True):
    return {'blockers': ['human_business_signoff_not_supplied', 'independent_holdout_has_two_documents_only'],
            'cases': [{'split': 'tuning', 'review_kind': 'user_delegated_agent_review', 'gold': {
                'review_kind': 'user_delegated_agent_review',
                'delegated_business_approved': approved, 'human_business_approved': False}}]}


def test_delegation_satisfies_source_approval_without_claiming_human_signature():
    tool = load_script('rag_review_replay')
    source = dataset()
    before = deepcopy(source)
    meta = tool.review_metadata(source)
    assert meta['gold_kind'] == 'user_delegated_agent_review'
    assert meta['delegated_business_approved'] is True
    assert meta['human_business_approved'] is False
    assert meta['delegated_approved_cases'] == 1
    assert 'human_business_signoff_not_supplied' not in meta['blockers']
    assert 'independent_holdout_has_two_documents_only' not in meta['blockers']
    assert 'no_independent_holdout_in_this_regression' in meta['blockers']
    assert source == before


def test_partial_or_unbound_approval_does_not_remove_signoff_blocker():
    tool = load_script('rag_review_replay')
    for source in (dataset(False), dataset()):
        if source['cases'][0]['gold']['delegated_business_approved']:
            source['cases'][0]['gold']['review_kind'] = 'agent_source_review'
        meta = tool.review_metadata(source)
        assert meta['delegated_business_approved'] is False
        assert 'human_business_signoff_not_supplied' in meta['blockers']


def test_actual_small_holdout_keeps_its_source_diversity_blocker():
    tool = load_script('rag_review_replay')
    source = dataset()
    source['cases'][0]['split'] = 'holdout'
    meta = tool.review_metadata(source)
    assert 'independent_holdout_has_two_documents_only' in meta['blockers']
    assert 'no_independent_holdout_in_this_regression' not in meta['blockers']
