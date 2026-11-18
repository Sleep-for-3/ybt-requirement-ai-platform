"""Freeze a small previously observed P0 regression against a fresh runtime."""
from __future__ import annotations

import argparse
from pathlib import Path

import httpx

from rag_regression import digest, freeze_environment, read_json
from rag_review_environment import source_identity
from rag_review_replay import setup
from rag_source_review import write_json


def freeze(workspace: Path, original: Path, target: Path, case_ids: list[str]):
    if target.exists() and any(target.iterdir()):
        raise ValueError('Preserve old results; snapshot target must be empty')
    if len(case_ids) != len(set(case_ids)) or not case_ids:
        raise ValueError('Explicit unique regression case IDs required')
    state = setup(workspace)
    old = read_json(original / 'reviewed-dataset.json')
    old_manifest = read_json(original / 'reviewed-environment.json')
    by_id = {c['case_id']: c for c in old['cases']}
    cases = [{**by_id[identity], 'split': 'tuning', 'observed_before_run': True} for identity in case_ids]
    dataset = {**old, 'cases': cases, 'previous_dataset_version': old['dataset_version'],
               'split_policy': 'known_failure_regression_only_not_a_new_holdout',
               'summary': {'cases': len(cases), 'new_holdout_cases': 0, 'human_approved': 0}}
    dataset.pop('dataset_version', None)
    dataset['dataset_version'] = digest(dataset)
    identity = source_identity()
    running = read_json(workspace / 'source-identity.json')
    if running['code_hash'] != identity['code_hash']:
        raise ValueError('Runtime source identity is stale')
    with httpx.Client(base_url=state['backend_url'], timeout=30) as client:
        ready = client.get('/health/ready')
        ready.raise_for_status()
        version = client.get('/version')
        version.raise_for_status()
    api = version.json()
    expected = identity['git_head'] + '+worktree.' + identity['code_hash'][:12]
    if api.get('app_commit') != expected or api.get('build_time') != running['build_time']:
        raise ValueError('API runtime identity mismatch')
    from app.core.database import SessionLocal
    from app.workers import celery_app
    worker_task = celery_app.send_task('app.workers.version_report')
    worker = worker_task.get(timeout=40)
    if any(worker.get(k) != api.get(k) for k in ('app_commit', 'build_time', 'schema_head')):
        raise ValueError('API/worker identity mismatch')
    with SessionLocal() as db:
        manifest = freeze_environment(None, old_manifest['project_id'], dataset, session=db)
    if manifest['corpus_hash'] != old_manifest['corpus_hash']:
        raise ValueError('Original regression corpus changed; re-review sources before proceeding')
    if manifest['code_hash'] != identity['code_hash']:
        raise ValueError('Source changed while freezing')
    target.mkdir(parents=True, exist_ok=True)
    write_json(target / 'reviewed-dataset.json', dataset)
    write_json(target / 'reviewed-environment.json', manifest)
    evidence = dict(source_hash=identity['code_hash'], dataset_version=dataset['dataset_version'],
        corpus_hash=manifest['corpus_hash'], api_version=api, worker_version=worker,
        worker_task_id=worker_task.id, readiness_status=ready.json().get('status'),
        case_ids=case_ids, external_model_requests=0, new_holdout_cases=0)
    write_json(target / 'runtime-verification.json', evidence)
    print({k: evidence[k] for k in ('source_hash', 'dataset_version', 'readiness_status',
                                    'case_ids', 'external_model_requests')})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--original-snapshot', required=True, type=Path)
    parser.add_argument('--output-directory', required=True, type=Path)
    parser.add_argument('--case-id', action='append', required=True)
    args = parser.parse_args()
    freeze(args.workspace.resolve(), args.original_snapshot.resolve(), args.output_directory.resolve(), args.case_id)
