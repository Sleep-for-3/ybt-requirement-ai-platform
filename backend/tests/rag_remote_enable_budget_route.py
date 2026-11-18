"""Enable only the candidate's fixed SSH relay, never direct cloud egress."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import urllib.request

ROOT = Path('/home/rag-long-run/releases/candidate-20261116-26')
NETWORK = 'rag-candidate-20261116-26'
os.umask(0o077)
relay = json.loads((ROOT / 'private/relay.private.json').read_text())
network = json.loads(subprocess.check_output(['docker', 'network', 'inspect', NETWORK]))[0]
assert network['Internal'] is True
gateway = network['IPAM']['Config'][0]['Gateway']
private = ROOT / 'private'
prior = private / 'environment.private.json'
env = json.loads(prior.read_text())
assert env['RAG_MODEL_BUDGET_PATH'] == '/candidate-private/BUDGET.json'
assert json.loads((private / 'BUDGET.json').read_text())['max_new_provider_requests'] == 0
with urllib.request.urlopen('http://127.0.0.1:18090/health', timeout=15) as response:
    assert json.load(response)['budget'] == 'central-local-ledger'
proxy = Path('/var/tmp/rag-model-route-20261116-27')
proxy.mkdir()
config = proxy / 'nginx.conf'
config.write_text('''pid %s/nginx.pid;
error_log %s/error.log warn;
events { worker_connections 128; }
http {
  access_log off;
  server {
    listen %s:18091;
    client_max_body_size 2m;
    proxy_read_timeout 200s;
    location = /health { proxy_pass http://127.0.0.1:18090/health; }
    location = /v1/chat/completions { proxy_pass http://127.0.0.1:18090/v1/chat/completions; }
    location / { return 404; }
  }
}
''' % (proxy, proxy, gateway))
subprocess.run(['nginx', '-t', '-p', str(proxy), '-c', str(config)], check=True)
subprocess.run(['nginx', '-p', str(proxy), '-c', str(config)], check=True)
env.pop('RAG_MODEL_BUDGET_PATH')
env.pop('RAG_MODEL_BUDGET_STATE')
env.update(LLM_PROVIDER='local_vllm', LLM_BASE_URL=f'http://{gateway}:18091/v1',
    LLM_MODEL=relay['model'], LLM_API_KEY_ENV_NAME='RAG_RELAY_KEY', RAG_RELAY_KEY=relay['token'],
    LLM_FALLBACK_MODELS='', LLM_INTERACTIVE_TIMEOUT_SECONDS='180',
    LLM_TIMEOUT_SECONDS='180', LLM_MAX_OUTPUT_TOKENS='32768')
target_env = private / 'environment-relay.private.json'
assert not target_env.exists()
target_env.write_text(json.dumps(env))
credential = private / 'acceptance-account.private.json'
assert not credential.exists()
account = {'username': 'rag_accept_20261116', 'password': secrets.token_urlsafe(32)}
credential.write_text(json.dumps(account))

script = '''import json, os
from pathlib import Path
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models import ModelProfile, User, Institution, InstitutionMembership
from app.services.auth.password import hash_password
p = Path('/candidate-private')
account = json.loads((p/'acceptance-account.private.json').read_text())
with SessionLocal() as db:
    profiles = list(db.scalars(select(ModelProfile)))
    old = [{'id': m.id, 'enabled': m.enabled} for m in profiles]
    assert not (p/'previous-profiles.private.json').exists()
    (p/'previous-profiles.private.json').write_text(json.dumps(old))
    for m in profiles:
        m.enabled = False
    db.add(ModelProfile(profile_name='candidate-central-budget-relay', provider_type='local_vllm',
        base_url=os.environ['LLM_BASE_URL'], model_name=os.environ['LLM_MODEL'],
        api_key_env_name='RAG_RELAY_KEY', enabled=True, local_only=False,
        max_context_tokens=65536, config_json={'retry_count': 0, 'fallback_models': [],
        'max_output_tokens': 32768, 'timeout_seconds': 180, 'json_mode': True},
        created_by='authorized-test-deployment'))
    assert db.scalar(select(User).where(User.username == account['username'])) is None
    institution = db.scalar(select(Institution).where(Institution.institution_type == 'platform_operator',
                                                    Institution.status == 'active'))
    assert institution is not None
    user = User(username=account['username'], password_hash=hash_password(account['password']),
                display_name='RAG acceptance', status='active')
    db.add(user)
    db.flush()
    db.add(InstitutionMembership(user_id=user.id, institution_id=institution.id,
                                role='institution_admin', status='active'))
    db.commit()
print(json.dumps({'profile_created': True, 'test_account_created': True,
                  'classification_local_only': False}))
'''
image = 'ybt-backend:rag-longrun-20261116-26'
for name, command, component in [
        ('rag-candidate25-api', ['uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '8000'], 'api'),
        ('rag-candidate25-worker', ['celery', '-A', 'app.workers.celery_app', 'worker', '--pool=solo',
                                    '--concurrency=1', '--loglevel=INFO'], 'worker')]:
    old = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
    assert old['Config']['Image'] == image
    subprocess.run(['docker', 'stop', '-t', '30', name], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(['docker', 'rename', name, name + '-zero-budget'], check=True)
    args = ['docker', 'run', '-d', '--name', name, '--network', NETWORK]
    if component == 'api':
        args += ['--network-alias', 'backend']
    selected = {**env, 'SERVICE_COMPONENT': component}
    for key in selected:
        args += ['-e', key]
    for source, target in [(ROOT/'storage', '/app/storage'), (private, '/candidate-private')]:
        args += ['--mount', f'type=bind,src={source},dst={target}']
    args += [image, *command]
    subprocess.run(args, check=True, env={**os.environ, **selected}, stdout=subprocess.DEVNULL)
    if component == 'api':
        execute = ['docker', 'exec', '-i', name, 'python', '-']
        subprocess.run(execute, input=script.encode(), check=True)

# The preview resolves container IPs at configuration time; refresh only its own file.
preview = Path('/var/tmp/rag-preview-20261116-26/nginx.conf')
old_config = preview.read_text()
old_api = json.loads(subprocess.check_output(['docker', 'inspect',
    'rag-candidate25-api-zero-budget']))[0]['NetworkSettings']['Networks'][NETWORK]['IPAddress']
new_api = json.loads(subprocess.check_output(['docker', 'inspect',
    'rag-candidate25-api']))[0]['NetworkSettings']['Networks'][NETWORK]['IPAddress']
# Stopped containers can have an empty IP; prior release checks preserve the original address.
if not old_api:
    import re
    old_api = re.search(r'location /api/ \{ proxy_pass http://([^:]+):8000', old_config).group(1)
preview.with_suffix('.before-relay.conf').write_text(old_config)
preview.write_text(old_config.replace(f'http://{old_api}:8000', f'http://{new_api}:8000'))
subprocess.run(['nginx', '-t', '-p', str(preview.parent), '-c', str(preview)], check=True)
subprocess.run(['nginx', '-s', 'reload', '-p', str(preview.parent), '-c', str(preview)], check=True)
for attempt in range(40):
    try:
        with urllib.request.urlopen('http://127.0.0.1:18089/health/ready', timeout=10) as response:
            health = json.load(response)
        if health['status'] == 'ready':
            break
    except Exception:
        pass
    time.sleep(2)
else:
    raise RuntimeError('Candidate readiness not reached')
report = {'shared_budget_route_enabled': True, 'public_routing_switched': False,
    'direct_cloud_egress': False, 'original_deployments_changed': False,
    'classification_local_only': False, 'model': relay['model'],
    'central_accounting': 'local-existing-SQLite', 'new_api_ip': new_api,
    'health': health, 'external_model_calls_in_configuration': 0}
(ROOT/'budget-route-report.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report))
