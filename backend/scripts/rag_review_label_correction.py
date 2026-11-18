"""Correct SQL evidence bindings using fixed source lines; never regenerate answers."""
from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import threading

from rag_regression import digest, freeze_environment, read_json
from rag_review_answer_audit import SYSTEM, request_for, sha
from rag_review_replay import retrieval_metrics, setup
from rag_source_review import write_json


def corrected_dataset(dataset, manifest, locators):
    result = deepcopy(dataset)
    active = [u for u in manifest['corpus'] if u['enabled'] and u['lifecycle'] == 'active']
    fixes = []
    for case in result['cases']:
        if case['split'] != 'holdout':
            continue
        start, end = case['gold']['source_lines']
        filename = case['provenance'][0]['source']
        candidates = [u for u in active if u['source'] == filename
            and type(locators[u['unit_id']].get('paragraph_index')) is int
            and locators[u['unit_id']]['line_start'] <= start
            and locators[u['unit_id']]['line_end'] >= end]
        if not candidates:
            raise ValueError('Fixed source lines are not covered by raw SQL')
        unit = min(candidates, key=lambda u: len(u['content']))
        old_ids = case['gold']['relevant_ids']
        case['gold'].update(relevant_ids=[unit['unit_id']],
            roles={'archived_sql_implementation': [unit['unit_id']]},
            evidence=[{k: unit[k] for k in ('unit_id', 'document_id', 'file_hash', 'content_hash')}])
        fixes.append({'case_id': case['case_id'], 'old_ids': old_ids,
            'corrected_ids': [unit['unit_id']], 'source_lines': [start, end]})
    for old, new in zip(dataset['cases'], result['cases'], strict=True):
        for key in ('case_id', 'query', 'split', 'provenance'):
            if new.get(key) != old.get(key):
                raise ValueError('Generator-facing fields changed')
        for key in ('expected_summary', 'decision', 'source_lines'):
            if new['gold'].get(key) != old['gold'].get(key):
                raise ValueError('Expected answer or fixed source lines changed')
    result['previous_dataset_version'] = dataset['dataset_version']
    result['label_correction'] = {'reason': 'exclude_derived_sql_summary_from_raw_line_evidence',
        'generator_inputs_unchanged': True, 'reused_frozen_generations': True, 'changes': fixes}
    result.pop('dataset_version')
    result['dataset_version'] = digest(result)
    return result


def main(args):
    setup(Path(args.workspace).resolve())
    from app.core.database import SessionLocal
    from app.models import KnowledgeUnit
    from app.services.llm import prompt_runtime
    from sqlalchemy import select
    run = Path(args.run_directory).resolve()
    original = read_json(run/'snapshot/reviewed-dataset.json')
    manifest = read_json(run/'snapshot/reviewed-environment.json')
    parent = read_json(run/'answer-review-v2/acceptance-summary.json')
    parent_inputs = read_json(run/'answer-review-v2/evaluation-manifest.json')
    v2_budget = read_json(run/'answer-review-v2/budget.json')
    base_attempts = read_json(run/'replay/judge-budget.json')['attempts'] + v2_budget['attempts']
    target = run/'label-correction-v3'
    target.mkdir(exist_ok=True)
    with SessionLocal() as db:
        units = list(db.scalars(select(KnowledgeUnit).where(KnowledgeUnit.project_id == manifest['project_id'])))
        locators = {u.id: (u.metadata_json or {}).get('locator', {}) for u in units}
        # Verify that every raw SQL paragraph is byte-identical to its source span.
        summaries = {u.document_id: (u.metadata_json or {}).get('raw_sql') for u in units
            if (u.metadata_json or {}).get('raw_sql')}
        for unit in units:
            locator = locators[unit.id]
            if unit.document_id not in summaries or 'paragraph_index' not in locator:
                continue
            raw = summaries[unit.document_id]
            if raw[locator['char_start']:locator['char_end']] != unit.content:
                raise ValueError('SQL paragraph no longer matches its original source span')
        current = freeze_environment(None, manifest['project_id'], original, session=db)
    for key in ('corpus_hash', 'config_fingerprint', 'index', 'prompts'):
        if current[key] != manifest[key]:
            raise ValueError(f'Generation environment changed: {key}')
    repository = Path(__file__).resolve().parents[2]
    allowed = {'backend/scripts/rag_review_dataset.py'}
    code_changes = {}
    for name, expected in manifest['code_files'].items():
        actual = sha(repository/name)
        if actual != expected:
            if name not in allowed:
                raise ValueError(f'Original code unexpectedly changed: {name}')
            code_changes[name] = {'before': expected, 'after': actual}
    generation_hashes = {p.name: sha(p) for p in sorted((run/'replay/generation').glob('*.json'))}
    if generation_hashes != parent_inputs['generation_files']:
        raise ValueError('Original model responses changed')
    dataset = corrected_dataset(original, manifest, locators)
    provenance = {'dataset_version': dataset['dataset_version'], 'corpus_hash': manifest['corpus_hash'],
        'parent_dataset_version': original['dataset_version'], 'generation_files': generation_hashes,
        'parent_answer_review_sha256': sha(run/'answer-review-v2/acceptance-summary.json'),
        'generation_code_hash': manifest['code_hash'], 'evaluation_code_hash': current['code_hash'],
        'allowed_evaluation_code_changes': code_changes, 'system_prompt_hash': digest(SYSTEM),
        'parent_judge_attempts': base_attempts, 'max_combined_judge_requests': args.max_combined_judge_requests}
    manifest_path = target/'evaluation-manifest.json'
    if manifest_path.exists() and read_json(manifest_path) != provenance:
        raise ValueError('Corrected evaluation inputs changed')
    write_json(manifest_path, provenance)
    write_json(target/'reviewed-dataset.json', dataset)
    rows_dir = target/'cases'; rows_dir.mkdir(exist_ok=True)
    budget_path = target/'budget.json'
    prior = read_json(budget_path) if budget_path.exists() else {'attempts': 0, 'reported_tokens': 0}
    count, tokens = prior['attempts'], prior['reported_tokens']
    lock = threading.Lock()
    pending = [c for c in dataset['cases'] if c['split'] == 'holdout' and not (rows_dir/(c['case_id']+'.json')).exists()]
    if base_attempts+count+len(pending) > args.max_combined_judge_requests:
        raise ValueError('Insufficient remaining shared judge budget')

    def save_budget():
        write_json(budget_path, {'attempts': count, 'reported_tokens': tokens, 'parent_attempts': base_attempts,
            'combined_attempts': base_attempts+count, 'max_combined_judge_requests': args.max_combined_judge_requests,
            'automatic_retries': 0, 'output_token_ceiling': 8192, 'workers': 2})

    async def assess(case):
        nonlocal count, tokens
        generated = read_json(run/'replay/generation'/(case['case_id']+'.json'))
        request = request_for(case, generated, manifest)
        with SessionLocal() as db:
            runtime = prompt_runtime.get_prompt_runtime(db, 'citation_support_check')
            runtime = replace(runtime, config={**runtime.config, 'retry_count': 0,
                'fallback_models': [], 'max_output_tokens': 8192, 'timeout_seconds': 180})
            prompt = prompt_runtime.prepare_model_input(runtime, json.dumps(request, ensure_ascii=False),
                ['internal'], db=db, project_id=manifest['project_id'])
        service = prompt_runtime.get_runtime_llm_service(runtime)
        row = {'case_id': case['case_id'], 'dataset_version': dataset['dataset_version'],
            'prompt_hash': digest(prompt), 'gold_source_ids': case['gold']['relevant_ids'],
            'judge_model': runtime.model_name, 'judge_provider': runtime.provider_type}
        with lock:
            if base_attempts+count >= args.max_combined_judge_requests:
                raise RuntimeError('shared_judge_budget_exhausted')
            count += 1; save_budget()
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
                tokens += int(usage.get('total_tokens') or 0); save_budget()
        return row

    def one(case):
        row = asyncio.run(assess(case)); write_json(rows_dir/(case['case_id']+'.json'), row)
        return row

    save_budget()
    with ThreadPoolExecutor(max_workers=2) as pool:
        for index, future in enumerate(as_completed([pool.submit(one, c) for c in pending]), 1):
            row = future.result()
            print(json.dumps({'corrected_holdout_review': index, 'total': len(pending),
                'case_id': row['case_id'], 'status': row['status']}), flush=True)
    cases = {c['case_id']: c for c in dataset['cases']}
    rows = deepcopy(parent['rows'])
    for row in rows:
        case = cases[row['case_id']]
        generated = read_json(run/'replay/generation'/(row['case_id']+'.json'))
        row.update(retrieval_metrics(case, generated['retrieved_ids'], generated['context_ids'], generated['cited_ids']))
        if case['split'] == 'holdout':
            audit = read_json(rows_dir/(row['case_id']+'.json')); assessment = audit.get('assessment', {})
            row.update(complete=assessment.get('complete'), unsupported_business_assertion=assessment.get('unsupported_business_assertion'),
                assessment_reason=assessment.get('reason'), assessment_error=audit.get('error_type'),
                expected_uncertainty_acknowledged=assessment.get('expected_uncertainty_acknowledged'))
    report = {**deepcopy(parent), 'schema': 'rag-source-reviewed-real-acceptance-corrected-v3',
        'dataset_version': dataset['dataset_version'], 'evaluation_code_hash': current['code_hash'],
        'parent_dataset_version': original['dataset_version'], 'label_correction': dataset['label_correction'],
        'judgement_failures': sum(type(r['complete']) is not bool for r in rows), 'rows': rows}
    for split, values in report['metrics'].items():
        subset = [r for r in rows if r['split'] == split]
        for key in ('hit5', 'mrr', 'ndcg5'):
            measured = [r[key] for r in subset if r[key] is not None]
            values[key] = sum(measured)/len(measured) if measured else None
        roles = sum(r['role_total'] for r in subset)
        values.update(role_total=roles, role_context_rate=sum(r['role_context'] for r in subset)/roles if roles else None,
            role_cited_rate=sum(r['role_cited'] for r in subset)/roles if roles else None)
        assessed = sum(type(r['complete']) is bool for r in subset); passed = sum(r['complete'] is True for r in subset)
        values.update(completeness_rate=passed/assessed if assessed else None, completeness_samples=assessed,
            complete_cases=passed, end_to_end_completeness_rate=passed/len(subset),
            unsupported_assertion_cases=sum(r['unsupported_business_assertion'] is True for r in subset))
    with SessionLocal() as db:
        end = freeze_environment(None, manifest['project_id'], original, session=db)
    for key in ('corpus_hash', 'config_fingerprint', 'index', 'prompts', 'code_hash'):
        if end[key] != current[key]:
            raise ValueError(f'Corrected evaluation environment changed: {key}')
    if generation_hashes != {p.name: sha(p) for p in sorted((run/'replay/generation').glob('*.json'))}:
        raise ValueError('Frozen model responses changed during corrected evaluation')
    report['shared_judge_budget'] = read_json(budget_path)
    write_json(target/'acceptance-summary.json', report)
    write_json(Path(args.public_output), {**report, 'rows': [{k:v for k,v in r.items()
        if not k.endswith('assessment_reason')} for r in rows]})
    print(json.dumps({'metrics': report['metrics'], 'budget': report['shared_judge_budget']}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True); parser.add_argument('--run-directory', required=True)
    parser.add_argument('--max-combined-judge-requests', type=int, required=True)
    parser.add_argument('--public-output', required=True)
    main(parser.parse_args())
