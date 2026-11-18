"""Create and upgrade a dedicated synthetic fixture for real browser acceptance."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

from rag_component_acceptance import authenticate_client, checked, reindex, upload
from rag_regression import read_json
from rag_review_environment import source_identity
from rag_review_replay import setup
from rag_source_review import write_json


def run(command: str, runtime: Path, output: Path):
    state = setup(runtime)
    identity = source_identity()
    frozen = read_json(runtime / 'source-identity.json')
    if identity['code_hash'] != frozen['code_hash']:
        raise ValueError('Runtime does not match current source')
    from app.core.database import SessionLocal
    from app.models import AgentToolCall, Project
    from sqlalchemy import select
    from sqlalchemy.engine import make_url
    from app.core.settings import get_settings

    url = make_url(get_settings().database_url)
    if url.host != '127.0.0.1' or url.port != 15439 or url.database != 'rag_accept':
        raise ValueError('Dedicated local component database required')
    fixture_path = output / 'fixture-state.json'
    fixture = read_json(fixture_path) if fixture_path.exists() else {
        'runtime_code_hash': identity['code_hash'], 'backend_url': state['backend_url'],
        'corpus_kind': 'synthetic_version_lifecycle', 'external_embedding_calls': 0,
    }
    if fixture['runtime_code_hash'] != identity['code_hash'] or fixture['backend_url'] != state['backend_url']:
        raise ValueError('Fixture belongs to a different runtime')

    with httpx.Client(base_url=state['backend_url'], timeout=120) as client:
        version = checked(client.get('/version'))
        if version['app_commit'] != identity['git_head'] + '+worktree.' + identity['code_hash'][:12]:
            raise ValueError('Running API identity mismatch')
        authenticate_client(client, state)
        if command == 'prepare':
            if not fixture.get('project_id'):
                with SessionLocal() as db:
                    institution = db.get(Project, 1).institution_id
                project = checked(client.post('/api/projects', json={
                    'name': 'P0版本链路-' + runtime.name, 'bank_name': 'RAG本地组件验收',
                    'institution_id': institution,
                }))
                fixture['project_id'] = project['id']
                fixture['other_project_id'] = 3
                write_json(fixture_path, fixture)
            if not fixture.get('original'):
                original = '合作方式字段F250007只能填01，01表示营销获客。'.encode('utf-8')
                fixture['original'] = upload(client, fixture['project_id'], 'lifecycle-policy.md', original,
                                             version='LIFECYCLE-V1', knowledge_type='regulatory_policy',
                                             source_category='internal_policy')
                write_json(fixture_path, fixture)
            if not fixture.get('index_v1_ready'):
                reindex(client, fixture['project_id'])
                fixture['index_v1_ready'] = True
                write_json(fixture_path, fixture)
        else:
            task_state = read_json(output / 'task-state.json')
            task = checked(client.get(f"/api/agent/tasks/{task_state['task_id']}"))
            if task['task']['project_id'] != fixture['project_id'] or task['task']['status'] != 'completed':
                raise ValueError('Fixture task must have completed in its own project')
            with SessionLocal() as db:
                calls = list(db.scalars(select(AgentToolCall).where(
                    AgentToolCall.task_id == task_state['task_id'],
                    AgentToolCall.tool_key == 'answer_knowledge_question')))
                if not any((call.execution_metadata_json or {}).get('execution_kind') == 'real_model' for call in calls):
                    raise ValueError('Fixture answer has no real-model execution identity')
            if not fixture.get('newer'):
                newer = '合作方式字段F250007只能填02，02表示联合贷款。'.encode('utf-8')
                fixture['newer'] = upload(client, fixture['project_id'], 'lifecycle-policy.md', newer,
                    document_id=fixture['original']['document_id'], version='LIFECYCLE-V2',
                    knowledge_type='regulatory_policy', source_category='internal_policy')
                write_json(fixture_path, fixture)
            if not fixture.get('index_v2_ready'):
                reindex(client, fixture['project_id'])
                fixture['index_v2_ready'] = True
                write_json(fixture_path, fixture)
    print(json.dumps({'stage': command, 'project_id': fixture['project_id'],
                      'code_hash': identity['code_hash'], 'fixture_kind': fixture['corpus_kind']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'upgrade'))
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.command, args.runtime.resolve(), args.output_directory.resolve())
    except Exception as error:
        print(json.dumps({'stage': args.command, 'failed': True, 'error_type': type(error).__name__}))
        raise SystemExit(1) from None
