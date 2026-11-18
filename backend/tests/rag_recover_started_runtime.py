"""Recover metadata after an owned runtime became ready after startup timeout."""
import argparse
import json
from pathlib import Path
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from rag_review_environment import source_identity
from rag_source_review import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--previous', required=True, type=Path)
    parser.add_argument('--port', required=True, type=int)
    args = parser.parse_args()
    root = args.workspace.resolve()
    if (root / 'state.json').exists():
        raise ValueError('Existing runtime metadata must be preserved')
    frozen = json.loads((root / 'source-identity.json').read_text(encoding='utf-8'))
    current = source_identity()
    if frozen['code_hash'] != current['code_hash']:
        raise ValueError('Runtime is stale')
    processes = json.loads((root / 'processes.json').read_text(encoding='utf-8'))
    command = processes['backend']['command']
    if command[-2:] != ['--port', str(args.port)]:
        raise ValueError('Registered runtime port mismatch')
    base = f'http://127.0.0.1:{args.port}'
    with httpx.Client(base_url=base, timeout=30) as client:
        client.get('/health/ready').raise_for_status()
        response = client.get('/version')
        response.raise_for_status()
        version = response.json()
    if (version.get('app_commit') != current['git_head'] + '+worktree.' + current['code_hash'][:12]
            or version.get('build_time') != frozen['build_time']):
        raise ValueError('Running API identity mismatch')
    original = json.loads((args.previous / 'state.json').read_text(encoding='utf-8'))
    write_json(root / 'state.json', {**{k: original[k] for k in ('username', 'password')},
               'backend_url': base, 'previous_workspace': str(args.previous.resolve())})
    print(json.dumps({'recovered': True, 'source_hash': current['code_hash'],
                      'ready': True, 'external_calls': 0}))


if __name__ == '__main__':
    main()
