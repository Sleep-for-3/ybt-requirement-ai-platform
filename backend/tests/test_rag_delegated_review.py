from copy import deepcopy

import pytest

from rag_freeze_delegated import apply_review


def inputs():
    dataset = {'previous_dataset_version': 'old', 'summary': {}, 'cases': [{'case_id': 'a', 'gold': {
        'expected_summary': 'old', 'relevant_ids': [1, 2],
        'roles': {'needed': [1], 'extra': [2]}, 'evidence': [{'unit_id': 1}, {'unit_id': 2}]}}]}
    manifest = {'corpus_hash': 'corpus', 'corpus': [
        {'unit_id': 1, 'content_hash': 'one'}, {'unit_id': 2, 'content_hash': 'two'}]}
    review = {'review_kind': 'user_delegated_agent_review', 'human_business_approved': False,
        'corpus_hash': 'corpus', 'original_dataset_version': 'old',
        'source_content_hashes': {'1': 'one', '2': 'two'},
        'cases': [{'case_id': 'a', 'required_unit_ids': [1], 'expected_summary': 'reviewed'}]}
    return dataset, manifest, review


def test_delegated_review_preserves_old_gold_and_keeps_only_question_required_roles():
    dataset, manifest, review = inputs()
    original = deepcopy(dataset)
    result = apply_review(dataset, manifest, review)
    assert dataset == original
    case = result['cases'][0]
    assert case['previous_gold'] == original['cases'][0]['gold']
    assert case['gold']['roles'] == {'needed': [1]}
    assert case['gold']['delegated_business_approved'] is True
    assert case['gold']['human_business_approved'] is False
    assert case['gold']['generated_answer_release_approved'] is False


@pytest.mark.parametrize('mutation', ['new_evidence', 'source_changed', 'missing_case', 'human_impersonation'])
def test_delegated_review_fails_closed_on_unbound_approval(mutation):
    dataset, manifest, review = inputs()
    if mutation == 'new_evidence':
        review['cases'][0]['required_unit_ids'] = [99]
    elif mutation == 'source_changed':
        manifest['corpus'][0]['content_hash'] = 'changed'
    elif mutation == 'missing_case':
        review['cases'] = []
    else:
        review['human_business_approved'] = True
    with pytest.raises(ValueError):
        apply_review(dataset, manifest, review)
