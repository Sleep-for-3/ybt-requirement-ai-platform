"""Round-trip the isolated preview between preserved releases without schema writes."""
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.request

BASE = Path('/home/rag-long-run/releases')
CURRENT = BASE / 'candidate-20261116-28'
PREVIOUS = BASE / 'candidate-20261116-26'
CONFIG = Path('/var/tmp/rag-preview-20261116-26/nginx.conf')
NETWORK = 'rag-candidate-20261116-26'
REPORT = CURRENT / 'rollback-probe-20261116-28.json'
assert not REPORT.exists(), 'preserve earlier rollback evidence'


def run(args, **kwargs):
    return subprocess.check_output(args, stderr=subprocess.PIPE,
        timeout=kwargs.pop('timeout', 120), **kwargs)


def inspect(name):
    return json.loads(run(['docker', 'inspect', name]))[0]


def address(name):
    return inspect(name)['NetworkSettings']['Networks'][NETWORK]['IPAddress']


def readiness(prefix, expected):
    api = prefix + '-api'
    for attempt in range(45):
        try:
            for path in ('/health/ready', '/version'):
                with urllib.request.urlopen(f'http://{address(api)}:8000{path}', timeout=10) as response:
                    assert response.status == 200
                    body = json.load(response)
                    if path == '/version':
                        assert body['app_commit'] == expected
            with urllib.request.urlopen(f'http://{address(prefix + "-frontend")}:3000/login', timeout=10) as response:
                assert response.status == 200
            return
        except Exception:
            if attempt == 44:
                raise
            time.sleep(2)


def snapshot(prefix):
    script = '''import hashlib, json
from pathlib import Path
from sqlalchemy import select, func
from app.core.database import SessionLocal
from app.models import AgentTask, BackgroundJob, KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeUnit, EmbeddingRecord
with SessionLocal() as db:
    for model in (AgentTask, BackgroundJob):
        assert not db.scalar(select(func.count()).select_from(model).where(
            model.project_id.in_([34,35]), model.status.in_(['queued','running','cancelling'])))
    counts = {model.__tablename__: db.scalar(select(func.count()).select_from(model))
        for model in (AgentTask, BackgroundJob, KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeUnit, EmbeddingRecord)}
    task = db.get(AgentTask,15)
    assert task.project_id == 34 and task.status == 'completed'
    version = db.get(KnowledgeDocumentVersion,45)
    assert version.project_id == 34 and version.lifecycle_status == 'superseded'
    from app.services.storage import get_storage_service
    digest = hashlib.sha256(get_storage_service().read(version.storage_path)).hexdigest()
    assert digest == '863f2b4feb253a02eaac8209ff6f0c1d87d60e7f1729537c20d3d649a2862938'
print(json.dumps({'counts':counts,'task15_status':task.status,'version45_sha256':digest}))
'''
    return json.loads(run(['docker', 'exec', '-i', prefix + '-api', 'python', '-'], input=script.encode()))


def file_hashes(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


current_names = ['rag-candidate28-' + part for part in ('api', 'worker', 'frontend')]
previous_names = ['rag-candidate25-' + part for part in ('api', 'worker', 'frontend')]
assert all(inspect(name)['State']['Running'] for name in current_names)
assert all(not inspect(name)['State']['Running'] for name in previous_names)
assert file_hashes(CURRENT / 'backend/alembic') == file_hashes(PREVIOUS / 'backend/alembic')
report = {'steps': [], 'public_routing_switched': False,
          'schema_migrations_run': 0, 'model_calls_by_probe': 0,
          'previous_source': json.loads((PREVIOUS / 'release-report.json').read_text())['source_hash'],
          'current_source': json.loads((CURRENT / 'release-report.json').read_text())['source_hash']}
original = CONFIG.read_text()
current_api, current_frontend = address(current_names[0]), address(current_names[2])
assert f'http://{current_api}:8000' in original and f'http://{current_frontend}:3000' in original
original_storage = file_hashes(PREVIOUS / 'storage')
before = snapshot('rag-candidate28')


def save():
    REPORT.write_text(json.dumps(report, indent=2))


def route(prefix, commit):
    config = original.replace(f'http://{current_api}:8000', f'http://{address(prefix + "-api")}:8000')
    config = config.replace(f'http://{current_frontend}:3000', f'http://{address(prefix + "-frontend")}:3000')
    CONFIG.write_text(config)
    run(['nginx', '-t', '-p', str(CONFIG.parent), '-c', str(CONFIG)])
    run(['nginx', '-s', 'reload', '-p', str(CONFIG.parent), '-c', str(CONFIG)])
    for _ in range(15):
        try:
            with urllib.request.urlopen('http://127.0.0.1:18089/version', timeout=10) as response:
                assert json.load(response)['app_commit'] == commit
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError('Preview version did not switch')


save()
try:
    for name in current_names:
        run(['docker', 'stop', '-t', '30', name])
    for name in previous_names:
        run(['docker', 'start', name])
    previous_commit = json.loads((PREVIOUS / 'release-report.json').read_text())['app_commit']
    readiness('rag-candidate25', previous_commit)
    route('rag-candidate25', previous_commit)
    assert snapshot('rag-candidate25') == before
    report['steps'].append('previous_release_ready_preview_version_and_task_evidence_preserved')
    save()
finally:
    for name in previous_names:
        if inspect(name)['State']['Running']:
            run(['docker', 'stop', '-t', '30', name])
    for name in current_names:
        if not inspect(name)['State']['Running']:
            run(['docker', 'start', name])
    current_commit = json.loads((CURRENT / 'release-report.json').read_text())['app_commit']
    readiness('rag-candidate28', current_commit)
    route('rag-candidate28', current_commit)
    report['current_release_restored'] = True
    save()
assert snapshot('rag-candidate28') == before
assert file_hashes(PREVIOUS / 'storage') == original_storage
report.update(steps=[*report['steps'], 'current_release_restored_with_same_records_and_storage'],
    records=before, storage_files=len(original_storage), previous_containers_preserved=True,
    completed=True)
save()
print(json.dumps(report))
