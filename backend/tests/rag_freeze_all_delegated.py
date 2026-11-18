"""Bind the explicitly reviewed 104 workbook and 20 SQL expectations to current sources."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from rag_apply_sql_review import apply_sql_review
from rag_regression import digest, freeze_environment, read_json
from rag_review_replay import setup
from rag_source_review import write_json


def apply_workbook_review(original, source, review, adjudications):
    if (review['review_kind'] != 'user_delegated_agent_review'
            or review['human_business_approved'] is not False
            or review['generated_answer_release_approved'] is not False
            or review['regulatory_authority_conferred'] is not False
            or review['original_dataset_version'] != original['dataset_version']
            or review['corpus_hash'] != source['corpus_hash']):
        raise ValueError('Delegated review scope or source differs')
    rows = {r[0]: r for r in adjudications['decisions']}
    approved = review['approved_case_ids']
    if (len(approved) != len(set(approved)) or set(approved) != set(rows)
            or review['workbook_sha256'] != adjudications['source_sha256']):
        raise ValueError('Every original workbook case requires explicit approval')
    corrections = {c['case_id']: c for c in review['corrections']}
    if len(corrections) != len(review['corrections']) or not set(corrections) <= set(rows):
        raise ValueError('Invalid correction identity')
    by_case = {c['case_id']: c for c in original['cases']}
    by_unit = {u['unit_id']: u for u in source['corpus']}
    result = []
    for identity in approved:
        case = deepcopy(by_case[identity])
        old = case['gold']
        row = rows[identity]
        if (old['decision'] != row[2] or old['expected_summary'] != row[3]):
            raise ValueError('Original expectation differs from reviewed adjudication')
        if not old['relevant_ids'] and identity not in review['negative_case_review']:
            raise ValueError('Empty evidence is not a source absence review')
        if any(by_unit[i]['file_hash'] != review['workbook_sha256'] for i in old['relevant_ids']):
            raise ValueError('Workbook case refers to another file')
        correction = corrections.get(identity, {})
        required = set(correction.get('required_unit_ids', old['relevant_ids']))
        if not required <= set(old['relevant_ids']):
            raise ValueError('Cannot insert unreviewed workbook evidence')
        decision = correction.get('decision', old['decision'])
        if decision != old['decision'] and not correction.get('reason'):
            raise ValueError('Decision changes require explicit source reasoning')
        case['previous_gold'] = deepcopy(old)
        case['original_split'] = case['split']
        case['split'] = 'tuning'
        case['observed_before_run'] = True
        case['review_status'] = 'approved'
        case['review_kind'] = review['review_kind']
        case['gold'] = {**old, 'decision': decision,
            'expected_summary': correction.get('expected_summary', old['expected_summary']),
            'must_refuse': decision == 'refuse',
            'must_confirm': decision in {'pending', 'partial', 'insufficient'},
            'relevant_ids': sorted(required),
            'roles': {k: [i for i in ids if i in required] for k, ids in old['roles'].items()
                      if required.intersection(ids)},
            'evidence': [e for e in old['evidence'] if e['unit_id'] in required],
            'review_kind': review['review_kind'], 'delegated_business_approved': True,
            'human_business_approved': False, 'generated_answer_release_approved': False,
            'reviewer': review['reviewer'], 'review_reason': correction.get('reason',
                review['negative_case_review'].get(identity, row[3]))}
        result.append(case)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('runtime', 'snapshot', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Preserve the previous reviewed snapshot')
    setup(args.runtime.resolve())
    original = read_json(args.snapshot / 'reviewed-dataset.json')
    source = read_json(args.snapshot / 'reviewed-environment.json')
    repository = Path(__file__).resolve().parents[2]
    documents = repository / 'docs/development/long-run'
    workbook = read_json(documents / 'delegated-workbook-review-20261116.json')
    sql = read_json(documents / 'delegated-sql-review-20261116.json')
    adjudication_path = repository / workbook['adjudications_file']
    if hashlib.sha256(adjudication_path.read_bytes()).hexdigest() != workbook['adjudications_sha256']:
        raise ValueError('Source adjudication bytes changed')
    cases = apply_workbook_review(original, source, workbook, read_json(adjudication_path))
    cases.extend(apply_sql_review(original, source, sql)['cases'])
    if {c['case_id'] for c in cases} != {c['case_id'] for c in original['cases']} or len(cases) != 124:
        raise ValueError('Explicit decisions do not cover exactly the 124 original cases')
    result = {'schema': 'rag-full-delegated-regression-v1', 'cases': cases,
        'previous_dataset_version': original['dataset_version'], 'delegated_reviews': [digest(workbook), digest(sql)],
        'split_policy': 'all_124_observed_cases_are_regression_only',
        'summary': {'cases': 124, 'delegated_approved': 124, 'human_approved': 0, 'new_holdout_cases': 0},
        'blockers': []}
    result['dataset_version'] = digest(result)
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        manifest = freeze_environment(None, source['project_id'], result, session=db)
    if manifest['corpus_hash'] != source['corpus_hash']:
        raise ValueError('The reviewed source corpus changed')
    for case in cases:
        for evidence in case['gold']['evidence']:
            unit = next(u for u in manifest['corpus'] if u['unit_id'] == evidence['unit_id'])
            if any(evidence[k] != unit[k] for k in ('document_id', 'file_hash', 'content_hash')):
                raise ValueError('Evidence identity differs from the explicit review')
    write_json(args.output / 'reviewed-dataset.json', result)
    write_json(args.output / 'reviewed-environment.json', manifest)
    audit = {'schema': 'rag-delegated-case-audit-v1', 'dataset_version': result['dataset_version'],
        'corpus_hash': manifest['corpus_hash'], 'code_hash': manifest['code_hash'],
        'human_business_approved': False, 'generated_answer_release_approved': False,
        'cases': [{'case_id': c['case_id'], 'decision': c['gold']['decision'],
            'required_ids': c['gold']['relevant_ids'], 'evidence_hashes':
                {str(e['unit_id']): e['content_hash'] for e in c['gold']['evidence']},
            'review_kind': c['review_kind'], 'expectation_hash': digest(c['gold']['expected_summary']),
            'previous_gold_hash': digest(c['previous_gold']), 'observed_before_run': True} for c in cases]}
    write_json(documents / 'evidence/ROUND-20261116-28-delegated-cases.json', audit)
    print(json.dumps({'cases': len(cases), 'delegated_approved': len(cases),
        'dataset_version': result['dataset_version'], 'external_model_calls': 0,
        'generated_answers_accepted': False, 'fresh_holdout_cases': 0}))


if __name__ == '__main__':
    main()
