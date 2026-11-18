"""Apply explicit SQL review to frozen sources, preserving every previous gold."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from rag_regression import digest, freeze_environment, read_json
from rag_review_replay import setup
from rag_source_review import write_json


def apply_sql_review(dataset, manifest, review):
    if (review['review_kind'] != 'user_delegated_agent_review'
            or review['human_business_approved'] is not False
            or review['generated_answer_release_approved'] is not False
            or review['regulatory_authority_conferred'] is not False):
        raise ValueError('Explicit delegated evaluation scope is required')
    if (review['original_dataset_version'] != dataset['dataset_version']
            or review['corpus_hash'] != manifest['corpus_hash']):
        raise ValueError('Review belongs to another frozen source')
    corpus = {u['unit_id']: u for u in manifest['corpus']}
    for identity, expected in review['source_content_hashes'].items():
        if corpus[int(identity)]['content_hash'] != expected:
            raise ValueError('Reviewed source content changed')
    cases = {c['case_id']: c for c in dataset['cases']}
    decisions = review['cases']
    if len({c['case_id'] for c in decisions}) != len(decisions):
        raise ValueError('Duplicate review case')
    revised = []
    for decision in decisions:
        case = deepcopy(cases[decision['case_id']])
        old = case['gold']
        if sorted(old['relevant_ids']) != sorted(decision['old_unit_ids']):
            raise ValueError('Original binding differs from reviewed defect')
        required = decision['required_unit_ids']
        if len(required) != 1 or decision['decision'] != old['decision']:
            raise ValueError('This correction only binds a single reviewed SQL statement')
        unit = corpus[required[0]]
        if (str(unit['unit_id']) not in review['source_content_hashes']
                or unit['file_hash'] != review['source_file_hashes'][str(unit['unit_id'])]
                or unit['file_hash'] not in {corpus[i]['file_hash'] for i in old['relevant_ids']}
                or unit['version_id'] not in {corpus[i]['version_id'] for i in old['relevant_ids']}):
            raise ValueError('Replacement must be explicitly bound in the same frozen version')
        if not unit['content'].lstrip().upper().startswith(('INSERT ', 'SELECT ', 'WITH ')):
            raise ValueError('Replacement is not executable SQL text')
        if not all(anchor in unit['content'] for anchor in decision['anchors']):
            raise ValueError('Reviewed SQL logic missing from evidence')
        case['previous_gold'] = deepcopy(old)
        case['original_split'] = case['split']
        case['split'] = 'tuning'
        case['observed_before_run'] = True
        case['review_status'] = 'approved'
        case['review_kind'] = review['review_kind']
        case['annotation_change_reason'] = review['binding_correction_reason']
        case['gold'] = {**old, 'relevant_ids': required,
            'roles': {'archived_sql_implementation': required},
            'evidence': [{k: unit[k] for k in ('unit_id', 'document_id', 'file_hash', 'content_hash')}],
            'review_kind': review['review_kind'], 'delegated_business_approved': True,
            'human_business_approved': False, 'generated_answer_release_approved': False,
            'reviewer': review['reviewer'], 'review_reason': decision['reason']}
        revised.append(case)
    result = {'schema': 'rag-delegated-sql-regression-v1', 'cases': revised,
        'previous_dataset_version': dataset['dataset_version'], 'delegated_review_sha256': digest(review),
        'split_policy': 'all_previously_observed_cases_are_regression_only', 'blockers': [],
        'summary': {'cases': len(revised), 'delegated_approved': len(revised), 'human_approved': 0,
                    'new_holdout_cases': 0, 'corrected_evidence_bindings': len(revised)}}
    result['dataset_version'] = digest(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('runtime', 'snapshot', 'review', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Do not overwrite a reviewed snapshot')
    setup(args.runtime.resolve())
    original = read_json(args.snapshot / 'reviewed-dataset.json')
    source = read_json(args.snapshot / 'reviewed-environment.json')
    review = read_json(args.review)
    dataset = apply_sql_review(original, source, review)
    from app.core.database import SessionLocal
    from app.models import KnowledgeUnit
    with SessionLocal() as db:
        for identity, expected in review['source_content_hashes'].items():
            unit = db.get(KnowledgeUnit, int(identity))
            assert digest(unit.content) == expected
            if identity in review['source_file_hashes']:
                assert unit.unit_type == 'sql_text'
        manifest = freeze_environment(None, source['project_id'], dataset, session=db)
    assert manifest['corpus_hash'] == source['corpus_hash']
    write_json(args.output / 'reviewed-dataset.json', dataset)
    write_json(args.output / 'reviewed-environment.json', manifest)
    print(json.dumps({'cases': len(dataset['cases']), 'source_hash': manifest['code_hash'],
        'dataset_version': dataset['dataset_version'], 'corrected_gold_only': True,
        'external_model_calls': 0, 'retrieval_or_quality_accepted': False}))


if __name__ == '__main__':
    main()
