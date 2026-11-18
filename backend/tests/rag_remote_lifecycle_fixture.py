"""Resume a synthetic lifecycle fixture through the actual isolated remote API."""
import argparse
import json
from pathlib import Path
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from rag_component_acceptance import authenticate_client, checked, reindex, upload
from rag_regression import read_json
from rag_review_environment import source_identity
from rag_source_review import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'upgrade', 'withdraw'))
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--account', required=True, type=Path)
    parser.add_argument('--budget', required=True, type=Path)
    parser.add_argument('--previous-fixture', type=Path)
    args = parser.parse_args()
    root = args.output.resolve()
    runtime = root / 'runtime'
    fixture_path = root / 'fixture-state.json'
    identity = source_identity()
    state = {**read_json(args.account), 'frontend_url': 'http://127.0.0.1:18130',
             'backend_url': 'http://127.0.0.1:18130'}
    fixture = read_json(fixture_path) if fixture_path.exists() else {
        'runtime_code_hash': identity['code_hash'], 'corpus_kind': 'remote_synthetic_version_lifecycle'}
    if args.previous_fixture:
        if fixture_path.exists() or args.command != 'prepare':
            raise ValueError('Import a previous fixture only into a new preparation directory')
        previous = read_json(args.previous_fixture)
        fixture = {**previous, 'previous_runtime_code_hash': previous['runtime_code_hash'],
            'runtime_code_hash': identity['code_hash'], 'previous_fixture': str(args.previous_fixture.resolve())}
    assert fixture['runtime_code_hash'] == identity['code_hash']
    with httpx.Client(base_url=state['backend_url'], timeout=120) as client:
        version = checked(client.get('/version'))
        assert version['app_commit'] == identity['git_head'] + '+worktree.' + identity['code_hash'][:12]
        authenticate_client(client, state)
        me = checked(client.get('/api/auth/me'))
        institution_id = next(m['institution_id'] for m in me['institution_memberships']
                              if m['role'] == 'institution_admin')
        if args.command == 'prepare':
            if fixture.get('original'):
                versions = checked(client.get(
                    f"/api/knowledge/documents/{fixture['original']['document_id']}/versions",
                    params={'project_id': fixture['project_id']}))
                assert any(v['id'] == fixture['original']['version_id']
                    and v['file_hash'] == fixture['original']['source_sha256'] for v in versions)
            for key, name in [('project_id', 'Remote P0 synthetic lifecycle 20261116'),
                              ('other_project_id', 'Remote P0 other project 20261116')]:
                if not fixture.get(key):
                    fixture[key] = checked(client.post('/api/projects', json={
                        'name': name, 'bank_name': 'Isolated acceptance',
                        'institution_id': institution_id}))['id']
                    write_json(fixture_path, fixture)
            if not fixture.get('original'):
                fixture['original'] = upload(client, fixture['project_id'], 'lifecycle-policy.md',
                    '合作方式字段F250007只能填01，01表示营销获客。'.encode(),
                    version='LIFECYCLE-V1', knowledge_type='regulatory_policy', source_category='internal_policy')
                write_json(fixture_path, fixture)
            if not fixture.get('index_v1_ready'):
                reindex(client, fixture['project_id'])
                fixture['index_v1_ready'] = True
        else:
            task = read_json(root / 'task-state.json')
            snapshot = checked(client.get(f"/api/agent/tasks/{task['task_id']}"))
            assert snapshot['task']['status'] == 'completed'
            assert snapshot['task']['project_id'] == fixture['project_id']
            if args.command == 'upgrade':
                if not fixture.get('newer'):
                    fixture['newer'] = upload(client, fixture['project_id'], 'lifecycle-policy.md',
                        '合作方式字段F250007只能填02，02表示联合贷款。'.encode(),
                        document_id=fixture['original']['document_id'], version='LIFECYCLE-V2',
                        knowledge_type='regulatory_policy', source_category='internal_policy')
                    write_json(fixture_path, fixture)
                if not fixture.get('index_v2_ready'):
                    reindex(client, fixture['project_id'])
                    fixture['index_v2_ready'] = True
            else:
                assert fixture.get('index_v2_ready')
                if not fixture.get('withdrawn'):
                    checked(client.post(f"/api/knowledge/document-versions/{fixture['original']['version_id']}/withdraw",
                        params={'project_id': fixture['project_id']}))
                    fixture['withdrawn'] = True
        write_json(fixture_path, fixture)
        write_json(runtime / 'state.json', state)
        write_json(runtime / 'source-identity.json', identity)
        write_json(runtime / 'environment.json', {'RAG_MODEL_BUDGET_PATH': str(args.budget.resolve()),
            'LLM_MODEL': 'deepseek-v4.1-flash', 'LLM_PROVIDER': 'local_vllm'})
        write_json(runtime / 'production-build.json', {'mode': 'next_start', **version})
    print(json.dumps({'stage': args.command, 'project_id': fixture['project_id'],
                      'source_hash': identity['code_hash'], 'provider_calls_in_fixture_setup': 0}))


if __name__ == '__main__':
    main()
