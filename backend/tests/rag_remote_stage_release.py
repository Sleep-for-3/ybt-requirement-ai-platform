"""Build an immutable candidate beside the preserved test deployments."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT = Path('/home/rag-long-run/releases/candidate-20261116-26')
BACKUP = Path('/home/rag-long-run/backup-20261116-24')
NETWORK = 'rag-candidate-20261116-26'
TAG = 'rag-longrun-20261116-26'


def run(command, **kwargs):
    return subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=kwargs.pop('timeout', 120), **kwargs).stdout


def start(name, image, command, env, mounts=(), ports=(), aliases=()):
    args = ['docker', 'run', '-d', '--name', name, '--network', NETWORK]
    for alias in aliases:
        args += ['--network-alias', alias]
    for key in env:
        args += ['-e', key]
    for source, target in mounts:
        args += ['--mount', f'type=bind,src={source},dst={target}']
    for port in ports:
        args += ['-p', port]
    args += [image, *command]
    return run(args, env={**os.environ, **env})


os.umask(0o077)
proof = json.loads((BACKUP / 'report.json').read_text())
assert proof['completed'] and proof['milvus_engine_restore_verified']
manifest = json.loads(Path('/home/rag-release-20261116-26-manifest.json').read_text())
archive = Path('/home/rag-release-20261116-26.tar.gz')
assert hashlib.sha256(archive.read_bytes()).hexdigest() == manifest['archive_sha256']
ROOT.mkdir(parents=True, exist_ok=False)
with tarfile.open(archive, 'r:gz') as source:
    assert all(m.isfile() and m.name in manifest['source_files'] for m in source.getmembers())
    source.extractall(ROOT)
for name, expected in manifest['source_files'].items():
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
identity = manifest['git_head'] + '+worktree.' + manifest['source_hash'][:12]
build_time = datetime.now(timezone.utc).isoformat()
report = {'source_hash': manifest['source_hash'], 'app_commit': identity, 'build_time': build_time,
          'archive_sha256': manifest['archive_sha256'], 'old_releases_preserved': True,
          'public_routing_switched': False, 'model_requests_enabled': False,
          'steps': ['source_package_verified']}


def save():
    (ROOT / 'release-report.json').write_text(json.dumps(report, indent=2))


save()
base = 'ybt-backend:e2e-20261109i'
expected_lock = manifest['source_files']['backend/requirements.lock.txt']
actual_lock = run(['docker', 'exec', 'rag-e2e-backend', 'sha256sum', '/app/requirements.lock.txt']).decode().split()[0]
assert actual_lock == expected_lock
dockerfile = ROOT / 'backend' / 'Dockerfile.candidate'
dockerfile.write_text('FROM ' + base + '\nWORKDIR /app\nRUN rm -rf /app/app /app/scripts /app/alembic\n'
    'COPY app ./app\nCOPY scripts ./scripts\n'
    'COPY alembic ./alembic\nCOPY alembic.ini requirements.txt requirements.lock.txt ./\n'
    'COPY candidate-build-info.json ./build-info.json\n'
    'LABEL org.ybt.app.commit="' + identity + '" org.ybt.build.time="' + build_time + '"\n')
(ROOT / 'backend' / 'candidate-build-info.json').write_text(json.dumps({'app_commit': identity, 'build_time': build_time}))
with (ROOT / 'backend-build.log').open('wb') as log:
    subprocess.run(['docker', 'build', '-f', str(dockerfile), '-t', 'ybt-backend:' + TAG,
                    str(ROOT / 'backend')], check=True, stdout=log, stderr=subprocess.STDOUT, timeout=900)
report['steps'].append('backend_built_from_verified_equal_lock_base')
save()
with (ROOT / 'frontend-build.log').open('wb') as log:
    subprocess.run(['docker', 'build', '-t', 'ybt-frontend:' + TAG,
        '--build-arg', 'NPM_REGISTRY=https://registry.npmmirror.com',
        '--build-arg', 'NEXT_PUBLIC_API_BASE_URL=/api',
        '--build-arg', 'NEXT_PUBLIC_APP_COMMIT=' + identity,
        '--build-arg', 'NEXT_PUBLIC_BUILD_TIME=' + build_time,
        str(ROOT / 'frontend')], check=True, stdout=log, stderr=subprocess.STDOUT, timeout=1200)
report['steps'].append('frontend_production_built')
save()
run(['docker', 'network', 'create', '--internal', NETWORK])
config = json.loads((BACKUP / 'containers.private.json').read_text())
old = next(c for c in config if c['Name'] == '/ybt-backend')
env = dict(v.split('=', 1) for v in old['Config']['Env'])
pg = next(c for c in config if c['Name'] == '/ybt-postgres')
pg_env = {k: v for k, v in (item.split('=', 1) for item in pg['Config']['Env'])
          if k in ('POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB')}
start('rag-candidate25-postgres', 'postgres:16', [], pg_env,
      [(BACKUP / 'postgres-restore-attempt2', '/var/lib/postgresql/data')], aliases=['postgres'])
start('rag-candidate25-redis', 'redis:7-alpine', [], {}, aliases=['redis'])
run(['docker', 'network', 'connect', '--alias', 'milvus', NETWORK, 'rag-restore24-milvus'])
# The embedding model cache is copied, so the prior service's files remain unchanged.
shutil.copytree('/data/ybt/fastembed-cache', ROOT / 'embedding-cache')
start('rag-candidate25-embedding', base,
      ['uvicorn', 'app.local_embedding_server:app', '--host', '0.0.0.0', '--port', '11434'],
      {'FASTEMBED_CACHE_PATH': '/data/fastembed-cache', 'HF_HUB_OFFLINE': '1'},
      [(ROOT / 'embedding-cache', '/data/fastembed-cache')], aliases=['embedding'])
shutil.copytree(BACKUP / 'restored-files/var/lib/docker/volumes/source_backend_storage/_data', ROOT / 'storage')
if env.get('STORAGE_PROVIDER') == 's3':
    original = next(c for c in config if c['Name'] == '/source-object-storage-1')
    obj_env = dict(v.split('=', 1) for v in original['Config']['Env'])
    shutil.copytree(BACKUP / 'restored-files/data/ybt/object-storage', ROOT / 'object-storage')
    start('rag-candidate25-objects', original['Config']['Image'], original['Config']['Cmd'], obj_env,
          [(ROOT / 'object-storage', '/data')], aliases=['object-storage'])
from urllib.parse import urlsplit, urlunsplit
database = urlsplit(env['DATABASE_URL'])
userinfo = database.netloc.rsplit('@', 1)[0]
env.update(DATABASE_URL=urlunsplit((database.scheme, userinfo + '@postgres:5432', '/ybt', '', '')),
    CELERY_BROKER_URL='redis://redis:6379/0', CELERY_RESULT_BACKEND='redis://redis:6379/1',
    REDIS_URL='redis://redis:6379/0', MILVUS_URI='http://milvus:19530',
    EMBEDDING_BASE_URL='http://embedding:11434/v1', S3_ENDPOINT_URL='http://object-storage:9000',
    MILVUS_COLLECTION_PREFIX='rag_candidate25', APP_COMMIT=identity, BUILD_TIME=build_time,
    STORAGE_DIR='/app/storage', CITATION_SUPPORT_CHECK='off',
    RAG_MODEL_BUDGET_PATH='/candidate-private/BUDGET.json',
    RAG_MODEL_BUDGET_STATE='/candidate-private/provider-budget.sqlite3')
private = ROOT / 'private'
private.mkdir(mode=0o700)
(private / 'BUDGET.json').write_text(json.dumps({'scope': 'remote-disabled-until-shared-budget-route',
    'max_new_provider_requests': 0, 'max_new_total_tokens': 0, 'provider_requests_used': 0,
    'provider_requests_reserved': 0, 'total_tokens_used': 0, 'total_tokens_reserved': 0, 'unknown_usage_requests': 0}))
(private / 'environment.private.json').write_text(json.dumps(env))
mounts = [(ROOT / 'storage', '/app/storage'), (private, '/candidate-private')]
image = 'ybt-backend:' + TAG
args = ['docker', 'run', '--name', 'rag-candidate25-migrate', '--network', NETWORK]
for key in env:
    args += ['-e', key]
args += [image, 'alembic', 'upgrade', 'head']
run(args, env={**os.environ, **env}, timeout=180)
api_env = {**env, 'SERVICE_COMPONENT': 'api'}
start('rag-candidate25-api', image,
      ['uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '8000'], api_env, mounts,
      ['127.0.0.1:18126:8000'], aliases=['backend'])
start('rag-candidate25-worker', image,
      ['celery', '-A', 'app.workers.celery_app', 'worker', '--pool=solo', '--concurrency=1', '--loglevel=INFO'],
      {**env, 'SERVICE_COMPONENT': 'worker'}, mounts)
start('rag-candidate25-frontend', 'ybt-frontend:' + TAG, [], {}, ports=['127.0.0.1:13125:3000'])
report['steps'].append('isolated_candidate_started_with_zero_model_budget')
report.update(network=NETWORK, backend_port=18126, frontend_port=13125,
              candidate_database='restored_ybt_in_independent_postgres')
save()
print(json.dumps(report))
