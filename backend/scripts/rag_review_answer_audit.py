"""Reassess frozen answers with all actually cited evidence and one shared budget."""
from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import threading

from rag_regression import digest, freeze_environment, read_json
from rag_review_replay import ASSESSMENT_SYSTEM, assessment_request, setup
from rag_source_review import write_json


SYSTEM = ASSESSMENT_SYSTEM + '''
gold_sources is the reviewed reference scope; actual_cited_sources contains the
original content of every source actually cited by this answer. Evaluate extra
claims against actual_cited_sources too. A source outside gold_sources is not
automatically unsupported. Candidate sources never cited are not evidence.
Distinguish an institution's proposed solution from an approved response.
For archived SQL questions evaluate that script, not current regulatory authority.
Return complete=false if evidence does not settle every requested point.
'''


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def request_for(case, generated, manifest):
    return assessment_request(case, generated, manifest)


def verify_generation_sources(manifest, repository):
    allowed = {'backend/scripts/rag_review_answer_audit.py', 'backend/scripts/rag_review_replay.py'}
    changed = {}
    for name, expected in manifest['code_files'].items():
        actual = sha(repository / name)
        if actual != expected and name not in allowed:
            raise ValueError(f'Original generation code changed: {name}')
        if actual != expected:
            changed[name] = {'generation_sha256': expected, 'evaluation_sha256': actual}
    return changed


def verify_parent(run, dataset, manifest, results=None):
    results = results or run/'replay'
    repository = Path(__file__).resolve().parents[2]
    changed = verify_generation_sources(manifest, repository)
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        current = freeze_environment(None, manifest['project_id'], dataset, session=db)
    for key in ('dataset_version', 'corpus_hash', 'config_fingerprint', 'index', 'prompts'):
        if current[key] != manifest[key]:
            raise ValueError(f'Parent environment changed: {key}')
    return {'dataset_version': dataset['dataset_version'], 'corpus_hash': manifest['corpus_hash'],
        'generation_code_hash': manifest['code_hash'], 'evaluation_code_hash': current['code_hash'],
        'system_prompt_hash': digest(SYSTEM), 'evaluation_only_source_changes': changed,
        'parent_summary_sha256': sha(results/'acceptance-summary.json'),
        'generation_files': {p.name: sha(p) for p in sorted((results/'generation').glob('*.json'))}}


def refresh_metrics(report):
    for split, values in report['metrics'].items():
        subset = [r for r in report['rows'] if r['split'] == split]
        assessed = sum(type(r['complete']) is bool for r in subset)
        passed = sum(r['complete'] is True for r in subset)
        values.update(completeness_rate=passed/assessed if assessed else None,
            completeness_samples=assessed, complete_cases=passed,
            end_to_end_completeness_rate=passed/len(subset) if subset else None,
            unsupported_assertion_cases=sum(r['unsupported_business_assertion'] is True for r in subset))


def main(args):
    run = Path(args.run_directory).resolve()
    results = Path(args.results_directory).resolve() if args.results_directory else run/'replay'
    setup(Path(args.workspace).resolve())
    from app.core.database import SessionLocal
    from app.services.llm import prompt_runtime
    dataset = read_json(run/'snapshot/reviewed-dataset.json')
    manifest = read_json(run/'snapshot/reviewed-environment.json')
    parent = read_json(results/'acceptance-summary.json')
    prior_budget = read_json(results/'judge-budget.json')
    if prior_budget['dataset_version'] != dataset['dataset_version']:
        raise ValueError('Parent judge budget belongs to another dataset')
    target = Path(args.output_directory).resolve() if args.output_directory else run/'answer-review-v2'
    target.mkdir(parents=True, exist_ok=True)
    provenance = verify_parent(run, dataset, manifest, results)
    provenance.update(parent_judge_attempts=prior_budget['attempts'],
        max_combined_judge_requests=args.max_combined_judge_requests)
    provenance_path = target/'evaluation-manifest.json'
    finalizer_provenance = dict(provenance)
    if provenance_path.exists():
        prior_provenance = read_json(provenance_path)
        ignored = {'evaluation_code_hash', 'evaluation_only_source_changes'} if args.finalize_only else set()
        if {k:v for k,v in prior_provenance.items() if k not in ignored} != {
                k:v for k,v in provenance.items() if k not in ignored}:
            raise ValueError('Supplemental evaluation inputs changed')
        provenance = prior_provenance
    elif args.finalize_only:
        raise ValueError('Finalization requires existing evaluation provenance')
    else:
        write_json(provenance_path, provenance)
    budget_path = target/'budget.json'
    prior = read_json(budget_path) if budget_path.exists() else {'attempts': 0, 'reported_tokens': 0}
    count, tokens = prior['attempts'], prior['reported_tokens']
    lock = threading.Lock()
    rows_dir = target/'cases'
    rows_dir.mkdir(exist_ok=True)
    pending = [c for c in dataset['cases'] if not (rows_dir/(c['case_id']+'.json')).exists()]
    if args.finalize_only and pending:
        raise ValueError('Finalization cannot dispatch missing model reviews')
    if prior_budget['attempts'] + count + len(pending) > args.max_combined_judge_requests:
        raise ValueError('Remaining shared budget is insufficient')

    def save_budget():
        write_json(budget_path, {'attempts': count, 'reported_tokens': tokens,
            'parent_attempts': prior_budget['attempts'], 'combined_attempts': count+prior_budget['attempts'],
            'max_combined_judge_requests': args.max_combined_judge_requests,
            'output_token_ceiling': 8192, 'automatic_retries': 0, 'workers': 2})

    async def assess(case):
        nonlocal count, tokens
        generated = read_json(results/'generation'/(case['case_id']+'.json'))
        row = {'case_id': case['case_id'], 'dataset_version': dataset['dataset_version']}
        if generated['status'] != 'completed':
            return {**row, 'status': 'not_run', 'reason': 'generation_failed'}
        request = request_for(case, generated, manifest)
        with SessionLocal() as db:
            runtime = prompt_runtime.get_prompt_runtime(db, 'citation_support_check')
            runtime = replace(runtime, config={**runtime.config, 'retry_count': 0,
                'fallback_models': [], 'max_output_tokens': 8192, 'timeout_seconds': 180})
            prompt = prompt_runtime.prepare_model_input(runtime, json.dumps(request, ensure_ascii=False),
                ['internal'], db=db, project_id=manifest['project_id'])
        service = prompt_runtime.get_runtime_llm_service(runtime)
        row.update(prompt_hash=digest(prompt), cited_source_count=len(request['actual_cited_sources']),
            judge_model=runtime.model_name, judge_provider=runtime.provider_type)
        with lock:
            if count+prior_budget['attempts'] >= args.max_combined_judge_requests:
                raise RuntimeError('shared_judge_budget_exhausted')
            count += 1
            save_budget()
        try:
            result = await service.chat_json(SYSTEM, prompt)
            if not isinstance(result, dict) or any(type(result.get(k)) is not bool for k in (
                'complete', 'unsupported_business_assertion', 'expected_uncertainty_acknowledged')):
                raise ValueError('Invalid assessment JSON')
            row.update(status='completed', assessment=result)
        except Exception as error:
            row.update(status='failed', error_type=type(error).__name__)
        finally:
            usage = getattr(getattr(service, 'last_call', None), 'token_usage', {}) or {}
            with lock:
                tokens += int(usage.get('total_tokens') or 0)
                save_budget()
        return row

    def one(case):
        row = asyncio.run(assess(case))
        write_json(rows_dir/(case['case_id']+'.json'), row)
        return row

    save_budget()
    with ThreadPoolExecutor(max_workers=2) as pool:
        for index, future in enumerate(as_completed([pool.submit(one, c) for c in pending]), 1):
            row = future.result()
            print(json.dumps({'answer_review': index, 'pending': len(pending),
                'case_id': row['case_id'], 'status': row['status']}), flush=True)
    if verify_parent(run, dataset, manifest, results) != {k:v for k,v in finalizer_provenance.items()
        if k not in ('parent_judge_attempts', 'max_combined_judge_requests')}:
        raise ValueError('Frozen answers or environment changed during supplemental review')
    rows = []
    for old in parent['rows']:
        row = dict(old)
        audit = read_json(rows_dir/(row['case_id']+'.json'))
        result = audit.get('assessment', {})
        for name in ('complete', 'unsupported_business_assertion', 'assessment_reason', 'assessment_error'):
            row['initial_'+name] = row.get(name)
        row.update(complete=result.get('complete'), unsupported_business_assertion=result.get('unsupported_business_assertion'),
            assessment_reason=result.get('reason'), assessment_error=audit.get('error_type'),
            expected_uncertainty_acknowledged=result.get('expected_uncertainty_acknowledged'))
        rows.append(row)
    report = {**parent, 'schema': 'rag-source-reviewed-real-acceptance-answer-review-v2',
        'generation_code_hash': manifest['code_hash'], 'evaluation_code_hash': provenance['evaluation_code_hash'],
        'finalizer_code_hash': finalizer_provenance['evaluation_code_hash'],
        'answer_review': 'all_actually_cited_original_sources_plus_gold_sources',
        'initial_judgement_failures': parent['judgement_failures'],
        'judgement_failures': sum(type(r['complete']) is not bool for r in rows), 'rows': rows}
    refresh_metrics(report)
    write_json(target/'acceptance-summary.json', report)
    if args.public_output:
        public = {**report, 'rows': [{k:v for k,v in row.items() if not k.endswith('assessment_reason')}
            for row in rows]}
        write_json(Path(args.public_output), public)
    print(json.dumps({'metrics': report['metrics'], 'budget': read_json(budget_path)}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--run-directory', required=True)
    parser.add_argument('--results-directory')
    parser.add_argument('--output-directory')
    parser.add_argument('--finalize-only', action='store_true',
                        help='Summarize saved reviews without dispatching provider requests')
    parser.add_argument('--max-combined-judge-requests', type=int, required=True)
    parser.add_argument('--public-output')
    main(parser.parse_args())
