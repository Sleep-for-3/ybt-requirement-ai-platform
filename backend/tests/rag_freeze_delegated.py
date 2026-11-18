"""Freeze an explicit user-delegated source review before any generation."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from rag_regression import digest, freeze_environment, read_json
from rag_review_replay import setup, check_snapshot
from rag_source_review import write_json


def apply_review(dataset, manifest, review):
    if review['review_kind'] != 'user_delegated_agent_review' or review['human_business_approved'] is not False:
        raise ValueError('Explicit delegated review identity required')
    if review['corpus_hash'] != manifest['corpus_hash'] or review['original_dataset_version'] != dataset['previous_dataset_version']:
        raise ValueError('Review source identity differs')
    by_id = {u['unit_id']: u for u in manifest['corpus']}
    for identity, expected in review['source_content_hashes'].items():
        if by_id[int(identity)]['content_hash'] != expected:
            raise ValueError('Reviewed evidence changed')
    cases = {c['case_id']: c for c in review['cases']}
    if len(cases) != len(review['cases']) or set(cases) != {c['case_id'] for c in dataset['cases']}:
        raise ValueError('Review must cover exactly this regression')
    revised = deepcopy(dataset)
    for case in revised['cases']:
        decision = cases[case['case_id']]
        required = set(decision['required_unit_ids'])
        old = case['gold']
        if not required or not required <= set(old['relevant_ids']):
            raise ValueError('Cannot inject new gold evidence')
        if any(str(i) not in review['source_content_hashes'] for i in old['relevant_ids']):
            raise ValueError('All original references require source binding')
        case['previous_gold'] = deepcopy(old)
        case['gold'] = {**old, 'expected_summary': decision['expected_summary'],
            'relevant_ids': sorted(required), 'roles': {role: [i for i in ids if i in required]
                for role, ids in old['roles'].items() if required.intersection(ids)},
            'evidence': [e for e in old['evidence'] if e['unit_id'] in required],
            'review_kind': review['review_kind'], 'delegated_business_approved': True,
            'human_business_approved': False, 'generated_answer_release_approved': False}
        case['review_kind'] = review['review_kind']
    revised['delegated_review_sha256'] = digest(review)
    revised['summary']['delegated_approved'] = len(cases)
    revised.pop('dataset_version', None)
    revised['dataset_version'] = digest(revised)
    return revised


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('workspace', 'snapshot', 'review', 'output'):
        parser.add_argument('--'+name, required=True, type=Path)
    args = parser.parse_args()
    target = args.output.resolve()
    if target.exists() and any(target.iterdir()):
        raise ValueError('Preserve existing snapshot')
    setup(args.workspace.resolve())
    old = read_json(args.snapshot/'reviewed-dataset.json')
    parent = read_json(args.snapshot/'reviewed-environment.json')
    proof = read_json(args.snapshot/'runtime-verification.json')
    review = read_json(args.review)
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        check_snapshot(old, parent, db)
        dataset = apply_review(old, parent, review)
        manifest = freeze_environment(None, parent['project_id'], dataset, session=db)
    if any(manifest[key] != parent[key] for key in ('corpus_hash', 'code_hash', 'index', 'prompts', 'config_fingerprint')):
        raise ValueError('Only the reviewed annotations may change')
    target.mkdir(parents=True, exist_ok=True)
    write_json(target/'reviewed-dataset.json', dataset)
    write_json(target/'reviewed-environment.json', manifest)
    write_json(target/'runtime-verification.json', {**proof, 'dataset_version': dataset['dataset_version'],
        'parent_dataset_version': old['dataset_version'], 'delegated_approved': len(dataset['cases']),
        'delegated_review_file_sha256': hashlib.sha256(args.review.read_bytes()).hexdigest()})
    print({'cases': len(dataset['cases']), 'delegated_approved': len(dataset['cases']),
           'dataset_version': dataset['dataset_version'], 'external_model_requests': 0})


if __name__ == '__main__':
    main()
