"""Resume an existing index wait without submitting another ingestion or index job."""
import argparse
import json
from pathlib import Path
import sys
import time

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from rag_component_acceptance import authenticate_client, checked
from rag_regression import read_json
from rag_review_environment import source_identity
from rag_review_replay import setup
from rag_source_review import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--job-id', required=True, type=int)
    parser.add_argument('--deadline-seconds', type=int, default=1800)
    args = parser.parse_args()
    state = setup(args.runtime.resolve())
    identity = source_identity()
    assert identity['code_hash'] == read_json(args.runtime / 'source-identity.json')['code_hash']
    checkpoint = args.output / 'ingestion-state.private.json'
    progress = read_json(checkpoint)
    deadline = time.monotonic() + args.deadline_seconds
    previous = None
    failures = 0
    with httpx.Client(base_url=state['backend_url'], timeout=60, trust_env=False) as client:
        version = checked(client.get('/version'))
        assert version['app_commit'] == identity['git_head'] + '+worktree.' + identity['code_hash'][:12]
        authenticate_client(client, state)
        while time.monotonic() < deadline:
            try:
                response = client.get(f'/api/jobs/{args.job_id}')
                if response.status_code == 401:
                    authenticate_client(client, state)
                    response = client.get(f'/api/jobs/{args.job_id}')
                if response.status_code in {502, 503, 504}:
                    raise httpx.TransportError('Transient index polling response')
                job = checked(response)
                failures = 0
            except httpx.TransportError as exc:
                failures += 1
                if failures > 8:
                    raise RuntimeError('Index polling transient retry limit exceeded') from exc
                print(json.dumps({'poll_retry': failures, 'job_id': args.job_id}), flush=True)
                time.sleep(min(failures * 2, 10))
                continue
            assert job['project_id'] == progress['project_id']
            stage = (job['status'], job.get('current_step'))
            if stage != previous:
                print(json.dumps({'job_id': args.job_id, 'status': stage[0], 'step': stage[1]}), flush=True)
                previous = stage
            if job['status'] == 'completed':
                index = checked(client.get(f"/api/projects/{progress['project_id']}/semantic-index/status"))
                assert index['active_index_current'] and index['milvus_health']['healthy']
                assert index['chunk_count'] > 0
                assert index['active_index']['corpus_hash'] == index['corpus_hash']
                result = {'job_id': args.job_id, 'status': 'completed',
                    'source_hash': identity['code_hash'], 'project_id': progress['project_id'],
                    'index_id': index['active_index']['id'], 'corpus_hash': index['corpus_hash'],
                    'chunks': index['chunk_count'], 'new_jobs_submitted': 0, 'external_model_calls': 0}
                write_json(args.output / 'index-resume-summary.json', result)
                progress['index_ready'] = True
                write_json(checkpoint, progress)
                print(json.dumps(result), flush=True)
                return
            if job['status'] in {'failed', 'cancelled', 'partially_completed'}:
                raise RuntimeError(f"Existing index job ended with {job['status']}")
            time.sleep(4)
    raise TimeoutError('Existing index job did not finish before the bounded deadline')


if __name__ == '__main__':
    main()
