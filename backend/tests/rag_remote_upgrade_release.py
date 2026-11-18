"""Upgrade only the isolated candidate; preserve its previous images and containers."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time
import urllib.request

ROOT = Path('/home/rag-long-run/releases/candidate-20261116-28')
PREVIOUS = Path('/home/rag-long-run/releases/candidate-20261116-26')
NETWORK = 'rag-candidate-20261116-26'
TAG = 'rag-longrun-20261116-28'
PREVIEW = Path('/var/tmp/rag-preview-20261116-26/nginx.conf')
os.umask(0o077)


def run(command, **kwargs):
    return subprocess.check_output(command, stderr=subprocess.PIPE, timeout=kwargs.pop('timeout', 120), **kwargs)


def inspect(name):
    return json.loads(run(['docker', 'inspect', name]))[0]


def address(name):
    return inspect(name)['NetworkSettings']['Networks'][NETWORK]['IPAddress']


def wait_ready(name, path, expected=None):
    port = 3000 if name.endswith('frontend') else 8000
    for _ in range(45):
        try:
            with urllib.request.urlopen(f'http://{address(name)}:{port}{path}', timeout=10) as response:
                assert response.status == 200
                body = json.load(response) if expected else None
            if expected:
                assert body['app_commit'] == expected
            return body
        except Exception:
            time.sleep(2)
    raise RuntimeError('Candidate readiness deadline exceeded: ' + name)


manifest = json.loads(Path('/home/rag-release-20261116-28-manifest.json').read_text())
archive = Path('/home/rag-release-20261116-28.tar.gz')
assert hashlib.sha256(archive.read_bytes()).hexdigest() == manifest['archive_sha256']
old_names = ['rag-candidate25-api', 'rag-candidate25-worker', 'rag-candidate25-frontend']
assert all(inspect(name)['State']['Running'] for name in old_names)
assert all(inspect(name)['Config']['Image'].endswith('rag-longrun-20261116-26') for name in old_names)
assert json.loads(run(['docker', 'network', 'inspect', NETWORK]))[0]['Internal'] is True
with urllib.request.urlopen('http://127.0.0.1:18090/health', timeout=15) as response:
    assert json.load(response)['budget'] == 'central-local-ledger'
ROOT.mkdir(parents=True, exist_ok=False)
with tarfile.open(archive, 'r:gz') as source:
    assert all(m.isfile() and m.name in manifest['source_files'] for m in source.getmembers())
    source.extractall(ROOT)
for name, expected in manifest['source_files'].items():
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
identity = manifest['git_head'] + '+worktree.' + manifest['source_hash'][:12]
build_time = datetime.now(timezone.utc).isoformat()
report = {'source_hash': manifest['source_hash'], 'app_commit': identity, 'build_time': build_time,
    'public_routing_switched': False, 'previous_deployments_preserved': True,
    'model_calls_in_deployment': 0, 'steps': ['package_verified']}


def save():
    (ROOT / 'release-report.json').write_text(json.dumps(report, indent=2))


save()
assert run(['docker', 'exec', 'rag-candidate25-api', 'sha256sum',
            '/app/requirements.lock.txt']).decode().split()[0] == manifest['source_files']['backend/requirements.lock.txt']
dockerfile = ROOT / 'backend/Dockerfile.candidate'
dockerfile.write_text('FROM ybt-backend:rag-longrun-20261116-26\nWORKDIR /app\n'
    'RUN rm -rf /app/app /app/scripts /app/alembic\n'
    'COPY app ./app\nCOPY scripts ./scripts\nCOPY alembic ./alembic\n'
    'COPY alembic.ini requirements.txt requirements.lock.txt ./\n'
    'COPY candidate-build-info.json ./build-info.json\n')
(ROOT / 'backend/candidate-build-info.json').write_text(json.dumps({'app_commit': identity, 'build_time': build_time}))
with (ROOT / 'backend-build.log').open('wb') as log:
    subprocess.run(['docker', 'build', '-f', str(dockerfile), '-t', 'ybt-backend:' + TAG,
        str(ROOT / 'backend')], stdout=log, stderr=subprocess.STDOUT, timeout=900, check=True)
report['steps'].append('backend_built')
save()
with (ROOT / 'frontend-build.log').open('wb') as log:
    subprocess.run(['docker', 'build', '-t', 'ybt-frontend:' + TAG,
        '--build-arg', 'NPM_REGISTRY=https://registry.npmmirror.com',
        '--build-arg', 'NEXT_PUBLIC_API_BASE_URL=/api', '--build-arg', 'NEXT_PUBLIC_APP_COMMIT=' + identity,
        '--build-arg', 'NEXT_PUBLIC_BUILD_TIME=' + build_time, str(ROOT / 'frontend')],
        stdout=log, stderr=subprocess.STDOUT, timeout=1200, check=True)
report['steps'].append('frontend_production_built')
save()
env = json.loads((PREVIOUS / 'private/environment-relay.private.json').read_text())
assert env['LLM_PROVIDER'] == 'local_vllm' and 'RAG_MODEL_BUDGET_PATH' not in env
env.update(APP_COMMIT=identity, BUILD_TIME=build_time)
private = ROOT / 'private'
private.mkdir(mode=0o700)
(private / 'environment-relay.private.json').write_text(json.dumps(env))
original_config = PREVIEW.read_text()
(ROOT / 'preview-before.conf').write_text(original_config)
old_api, old_frontend = address(old_names[0]), address(old_names[2])
assert f'http://{old_api}:8000' in original_config and f'http://{old_frontend}:3000' in original_config
started = []
stopped = []
try:
    for old in old_names:
        run(['docker', 'stop', '-t', '30', old])
        stopped.append(old)
    for component, command in [
        ('api', ['uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '8000']),
        ('worker', ['celery', '-A', 'app.workers.celery_app', 'worker', '--pool=solo', '--concurrency=1', '--loglevel=INFO']),
        ('frontend', []),
    ]:
        name = 'rag-candidate28-' + component
        selected = {**env, 'SERVICE_COMPONENT': component} if component != 'frontend' else {}
        command_line = ['docker', 'run', '-d', '--name', name, '--network', NETWORK]
        if component == 'api':
            command_line += ['--network-alias', 'backend']
        for key in selected:
            command_line += ['-e', key]
        if component != 'frontend':
            for src, dest in [(PREVIOUS / 'storage', '/app/storage'), (PREVIOUS / 'private', '/candidate-private')]:
                command_line += ['--mount', f'type=bind,src={src},dst={dest}']
        image = 'ybt-' + ('frontend' if component == 'frontend' else 'backend') + ':' + TAG
        run([*command_line, image, *command], env={**os.environ, **selected})
        started.append(name)
    wait_ready('rag-candidate28-api', '/health/ready')
    version = wait_ready('rag-candidate28-api', '/version', identity)
    wait_ready('rag-candidate28-frontend', '/login')
    replacement = original_config.replace(f'http://{old_api}:8000', f'http://{address(started[0])}:8000')
    replacement = replacement.replace(f'http://{old_frontend}:3000', f'http://{address(started[2])}:3000')
    PREVIEW.write_text(replacement)
    run(['nginx', '-t', '-p', str(PREVIEW.parent), '-c', str(PREVIEW)])
    run(['nginx', '-s', 'reload', '-p', str(PREVIEW.parent), '-c', str(PREVIEW)])
    for _ in range(15):
        try:
            with urllib.request.urlopen('http://127.0.0.1:18089/version', timeout=15) as response:
                assert json.load(response)['app_commit'] == identity
            break
        except Exception:
            time.sleep(1)
    else:
        raise RuntimeError('Preview did not switch to the verified candidate')
    report.update(steps=[*report['steps'], 'isolated_preview_upgraded'], version=version,
        shared_budget_route_enabled=True, old_candidate_containers_stopped_preserved=stopped,
        candidate_containers=started, existing_database_and_storage_preserved=True,
        rollback_config=str(ROOT / 'preview-before.conf'))
    save()
except Exception:
    for name in started:
        run(['docker', 'stop', '-t', '30', name])
    for name in stopped:
        run(['docker', 'start', name])
    # Restarted containers may receive different addresses.
    restored = original_config.replace(f'http://{old_api}:8000', f'http://{address(old_names[0])}:8000')
    restored = restored.replace(f'http://{old_frontend}:3000', f'http://{address(old_names[2])}:3000')
    PREVIEW.write_text(restored)
    run(['nginx', '-t', '-p', str(PREVIEW.parent), '-c', str(PREVIEW)])
    run(['nginx', '-s', 'reload', '-p', str(PREVIEW.parent), '-c', str(PREVIEW)])
    report.update(deployment_failed=True, previous_candidate_restarted=True)
    save()
    raise
print(json.dumps(report))
