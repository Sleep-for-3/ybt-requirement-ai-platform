"""Enable candidate37's private, centrally budgeted model relay route."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import time
import urllib.request


ROOT = Path('/home/rag-long-run/releases/candidate-20261116-37-attempt2')
NETWORK = 'rag-candidate-20261116-37'
API = 'rag-candidate37-api'
WORKER = 'rag-candidate37-worker'
ROUTE_PORT = 18092
ROUTE_DIR = ROOT / 'model-route'
PREVIEW = ROOT / 'preview'
os.umask(0o077)


def run(command, *, input_data=None, timeout=90):
    return subprocess.run(command, check=True, input=input_data, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout)


def inspect(name):
    return json.loads(run(['docker', 'inspect', name]).stdout)[0]


def container_environment(container):
    entries = container['Config'].get('Env') or []
    return dict(item.split('=', 1) for item in entries if '=' in item)


def health(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.status, json.load(response)


def candidate_api_health():
    probe = ('import json,urllib.request; '
             'r=urllib.request.urlopen("http://127.0.0.1:8000/health/ready",timeout=4); '
             'print(json.dumps({"status":r.status,**json.load(r)}))')
    response = run(['docker', 'exec', API, 'python', '-c', probe], timeout=10)
    return json.loads(response.stdout)


def validate_zero_candidate_budget(summary, limits_row, attempt_count):
    if not isinstance(summary, dict) or any(summary.get(key) != 0 for key in (
            'max_new_provider_requests', 'max_new_total_tokens', 'provider_requests_used',
            'provider_requests_reserved', 'total_tokens_used', 'total_tokens_reserved',
            'unknown_usage_requests')) or attempt_count != 0:
        raise RuntimeError('Candidate37 budget is not zero and unused')
    if limits_row is not None and limits_row != (summary.get('scope'), 0, 0):
        raise RuntimeError('Candidate37 durable budget limits do not match its zero summary')


def candidate_preflight():
    network = json.loads(run(['docker', 'network', 'inspect', NETWORK]).stdout)[0]
    config = network['IPAM']['Config'][0]
    if network.get('Internal') is not True or config.get('Subnet') != '192.168.80.0/20' \
            or config.get('Gateway') != '192.168.80.1':
        raise RuntimeError('Candidate37 network identity changed')
    if not (ROOT / 'private/relay.private.json').is_file():
        raise RuntimeError('Candidate37 relay credential is missing')
    private = ROOT / 'private'
    limits = json.loads((private / 'BUDGET.json').read_text())
    with socket.socket() as sock:
        sock.settimeout(0.5)
        if sock.connect_ex(('192.168.80.1', ROUTE_PORT)) == 0:
            raise RuntimeError('Candidate37 relay route port is already occupied')
    if ROUTE_DIR.exists() or (PREVIEW / 'nginx.before-relay.conf').exists():
        raise RuntimeError('Candidate37 relay route artifacts already exist')
    if not (PREVIEW / 'nginx.conf').is_file() or not (PREVIEW / 'logs/nginx.pid').is_file():
        raise RuntimeError('Candidate37 preview identity is incomplete')
    if health('http://127.0.0.1:18090/health')[1].get('budget') != 'central-local-ledger':
        raise RuntimeError('Shared central relay is unavailable')
    with (private / 'provider-budget.sqlite3').open('rb') as handle:
        if not handle.read(16).startswith(b'SQLite format 3'):
            raise RuntimeError('Candidate37 budget state is invalid')
    with sqlite3.connect(private / 'provider-budget.sqlite3') as db:
        limits_row = db.execute('SELECT scope, requests, tokens FROM limits').fetchone()
        attempts = db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]
    validate_zero_candidate_budget(limits, limits_row, attempts)
    return network['IPAM']['Config'][0]['Gateway']


def write_env_file(path, environment):
    lines = []
    for key, value in sorted(environment.items()):
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
            raise RuntimeError('Invalid candidate environment key')
        if not isinstance(value, str) or '\n' in value or '\r' in value:
            raise RuntimeError('Invalid candidate environment value')
        lines.append(f'{key}={value}')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    path.chmod(0o600)


def start_replacement(name, previous_name, route_environment, alias=None):
    old = inspect(name)
    if old['State']['Status'] != 'running' or old['Config']['Image'] != 'ybt-backend:rag-longrun-20261116-37':
        raise RuntimeError('Candidate37 container identity changed')
    if subprocess.run(['docker', 'inspect', previous_name], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode == 0:
        raise RuntimeError('Candidate37 rollback container name is already occupied')
    environment = container_environment(old)
    environment.update(route_environment)
    env_file = ROOT / 'private' / f'{name}.relay.env'
    write_env_file(env_file, environment)
    mounts = old.get('Mounts') or []
    expected_targets = {'/candidate-private', '/app/storage'}
    if {mount.get('Destination') for mount in mounts} != expected_targets:
        raise RuntimeError('Candidate37 container mount identity changed')

    run(['docker', 'stop', '-t', '30', name], timeout=45)
    run(['docker', 'rename', name, previous_name])
    command = ['docker', 'run', '-d', '--name', name, '--network', NETWORK]
    if alias:
        command += ['--network-alias', alias]
    command += ['--env-file', str(env_file)]
    for mount in mounts:
        if mount.get('Type') != 'bind':
            raise RuntimeError('Unexpected candidate mount type')
        command += ['--mount', f"type=bind,src={mount['Source']},dst={mount['Destination']}"]
    for option in old['HostConfig'].get('SecurityOpt') or []:
        command += ['--security-opt', option]
    command += [old['Config']['Image'], *(old['Config'].get('Cmd') or [])]
    run(command, timeout=120)
    return old


def restore_containers():
    for name, old_name in ((API, API + '-pre-relay'), (WORKER, WORKER + '-pre-relay')):
        if subprocess.run(['docker', 'inspect', old_name], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode != 0:
            continue
        if subprocess.run(['docker', 'inspect', name], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0:
            subprocess.run(['docker', 'stop', '-t', '20', name], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=40)
            subprocess.run(['docker', 'rename', name, name + '-relay-failed'], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=15)
        if subprocess.run(['docker', 'inspect', old_name], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0:
            subprocess.run(['docker', 'rename', old_name, name], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=15)
            subprocess.run(['docker', 'start', name], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=45)


def update_preview(api_ip):
    config = PREVIEW / 'nginx.conf'
    original = config.read_text(encoding='utf-8')
    match = re.search(r'location /api/ \{ proxy_pass http://([0-9.]+):8000;', original)
    if not match:
        raise RuntimeError('Candidate37 preview API upstream is not recognizable')
    old_ip = match.group(1)
    updated = original.replace(f'http://{old_ip}:8000', f'http://{api_ip}:8000')
    if updated == original:
        raise RuntimeError('Candidate37 preview API upstream did not change')
    backup = PREVIEW / 'nginx.before-relay.conf'
    backup.write_text(original, encoding='ascii')
    backup.chmod(0o600)
    config.write_text(updated, encoding='ascii')
    run(['nginx', '-t', '-p', str(PREVIEW), '-c', str(config)])
    run(['nginx', '-s', 'reload', '-p', str(PREVIEW), '-c', str(config)])


def enable():
    gateway = candidate_preflight()
    private = ROOT / 'private'
    relay = json.loads((private / 'relay.private.json').read_text())
    if not relay.get('token') or not relay.get('model'):
        raise RuntimeError('Candidate37 relay credential is malformed')
    source_environment = json.loads((private / 'environment.private.json').read_text())
    if source_environment.get('RAG_MODEL_BUDGET_PATH') != '/candidate-private/BUDGET.json':
        raise RuntimeError('Candidate37 local budget path changed')
    source_environment.update(
        LLM_PROVIDER='local_vllm',
        LLM_BASE_URL=f'http://{gateway}:{ROUTE_PORT}/v1',
        LLM_MODEL=relay['model'],
        LLM_API_KEY_ENV_NAME='RAG_RELAY_KEY',
        RAG_RELAY_KEY=relay['token'],
        LLM_FALLBACK_MODELS='',
        LLM_TIMEOUT_SECONDS='180',
        LLM_INTERACTIVE_TIMEOUT_SECONDS='180',
        LLM_MAX_OUTPUT_TOKENS='32768',
        CITATION_SUPPORT_CHECK='off',
    )
    selected_environment = private / 'environment-relay.private.json'
    if selected_environment.exists():
        raise RuntimeError('Candidate37 relay environment already exists')
    selected_environment.write_text(json.dumps(source_environment, indent=2) + '\n',
                                    encoding='utf-8')
    selected_environment.chmod(0o600)

    route_config = ROUTE_DIR / 'nginx.conf'
    ROUTE_DIR.mkdir(mode=0o700)
    route_config.write_text(f'''pid {ROUTE_DIR}/nginx.pid;
error_log {ROUTE_DIR}/error.log warn;
events {{ worker_connections 128; }}
http {{
  access_log off;
  server {{
    listen {gateway}:{ROUTE_PORT};
    client_max_body_size 2m;
    proxy_read_timeout 200s;
    location = /health {{ proxy_pass http://127.0.0.1:18090/health; }}
    location = /v1/chat/completions {{
      proxy_pass http://127.0.0.1:18090/v1/chat/completions;
    }}
    location / {{ return 404; }}
  }}
}}
''', encoding='ascii')
    run(['nginx', '-t', '-p', str(ROUTE_DIR), '-c', str(route_config)])
    run(['nginx', '-p', str(ROUTE_DIR), '-c', str(route_config)])
    if health(f'http://{gateway}:{ROUTE_PORT}/health')[1].get('budget') != 'central-local-ledger':
        raise RuntimeError('Candidate37 host relay route did not pass health verification')

    route_environment = {key: source_environment[key] for key in (
        'LLM_PROVIDER', 'LLM_BASE_URL', 'LLM_MODEL', 'LLM_API_KEY_ENV_NAME',
        'RAG_RELAY_KEY', 'LLM_FALLBACK_MODELS', 'LLM_TIMEOUT_SECONDS',
        'LLM_INTERACTIVE_TIMEOUT_SECONDS', 'LLM_MAX_OUTPUT_TOKENS',
        'CITATION_SUPPORT_CHECK')}
    try:
        start_replacement(API, API + '-pre-relay', route_environment, alias='backend')
        start_replacement(WORKER, WORKER + '-pre-relay', route_environment)
        api_ip = inspect(API)['NetworkSettings']['Networks'][NETWORK]['IPAddress']
        update_preview(api_ip)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                ready = candidate_api_health()
                if ready.get('status') == 'ready':
                    break
            except Exception:
                pass
            time.sleep(2)
        else:
            raise RuntimeError('Candidate37 API did not reach readiness')

        profile_backup = private / 'model-profile.before-relay.private.json'
        if profile_backup.exists():
            raise RuntimeError('Candidate37 model profile backup already exists')
        backup_script = '''import json
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models import ModelProfile
with SessionLocal() as db:
    rows = [{'id': p.id, 'enabled': p.enabled, 'provider_type': p.provider_type,
        'base_url': p.base_url, 'api_key_env_name': p.api_key_env_name,
        'local_only': p.local_only, 'config_json': p.config_json}
        for p in db.scalars(select(ModelProfile))]
with open('/candidate-private/model-profile.before-relay.private.json','w') as f:
    json.dump(rows, f)
'''
        run(['docker', 'exec', '-i', API, 'python', '-'],
            input_data=backup_script.encode('utf-8'), timeout=45)
        script = '''import json
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models import ModelProfile
with SessionLocal() as db:
    profiles = list(db.scalars(select(ModelProfile)))
    matches = [p for p in profiles if p.profile_name == 'candidate-central-budget-relay']
    if len(matches) != 1 or matches[0].model_name != ''' + repr(relay['model']) + ''':
        raise RuntimeError('Candidate37 relay profile identity changed')
    selected = matches[0]
    selected.provider_type = 'local_vllm'
    selected.base_url = ''' + repr(source_environment['LLM_BASE_URL']) + '''
    selected.api_key_env_name = 'RAG_RELAY_KEY'
    selected.enabled = True
    selected.local_only = False
    selected.config_json = {'retry_count': 0, 'fallback_models': [],
        'max_output_tokens': 32768, 'timeout_seconds': 180, 'json_mode': True}
    for profile in profiles:
        if profile.id != selected.id:
            profile.enabled = False
    db.commit()
print(json.dumps({'profile_updated': True, 'retry_count': 0,
                  'fallback_models': 0, 'external_calls': 0}))
'''
        run(['docker', 'exec', '-i', API, 'python', '-'], input_data=script.encode('utf-8'), timeout=45)
        profile_backup.chmod(0o600)
        report = {
            'candidate': 'candidate-20261116-37-attempt2',
            'network': NETWORK,
            'gateway': gateway,
            'relay_port': ROUTE_PORT,
            'model': relay['model'],
            'central_budget_authoritative': True,
            'candidate_budget_requests': 0,
            'candidate_budget_tokens': 0,
            'retry_count': 0,
            'fallback_models': 0,
            'old_api_worker_preserved': True,
            'public_route_changed': False,
            'provider_calls_made': 0,
        }
        (ROOT / 'budget-route-report.json').write_text(json.dumps(report, indent=2) + '\n',
                                                       encoding='ascii')
        (ROOT / 'budget-route-report.json').chmod(0o600)
        print(json.dumps(report))
    except Exception:
        restore_containers()
        profile_backup = private / 'model-profile.before-relay.private.json'
        if profile_backup.is_file() and subprocess.run(
                ['docker', 'inspect', API], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL).returncode == 0:
            restore_script = '''import json
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models import ModelProfile
rows=json.load(open('/candidate-private/model-profile.before-relay.private.json'))
with SessionLocal() as db:
    profiles={p.id:p for p in db.scalars(select(ModelProfile))}
    for row in rows:
        p=profiles[row['id']]
        for key in ('enabled','provider_type','base_url','api_key_env_name','local_only','config_json'):
            setattr(p,key,row[key])
    db.commit()
'''
            subprocess.run(['docker', 'exec', '-i', API, 'python', '-'],
                           input=restore_script.encode('utf-8'), check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        backup = PREVIEW / 'nginx.before-relay.conf'
        if backup.is_file():
            (PREVIEW / 'nginx.conf').write_text(backup.read_text(encoding='ascii'), encoding='ascii')
            subprocess.run(['nginx', '-s', 'reload', '-p', str(PREVIEW),
                            '-c', str(PREVIEW / 'nginx.conf')], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        raise


def rollback():
    restore_containers()
    profile_backup = ROOT / 'private/model-profile.before-relay.private.json'
    if profile_backup.is_file():
        restore_script = '''import json
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models import ModelProfile
rows=json.load(open('/candidate-private/model-profile.before-relay.private.json'))
with SessionLocal() as db:
    profiles={p.id:p for p in db.scalars(select(ModelProfile))}
    for row in rows:
        p=profiles[row['id']]
        for key in ('enabled','provider_type','base_url','api_key_env_name','local_only','config_json'):
            setattr(p,key,row[key])
    db.commit()
'''
        run(['docker', 'exec', '-i', API, 'python', '-'],
            input_data=restore_script.encode('utf-8'), timeout=45)
    backup = PREVIEW / 'nginx.before-relay.conf'
    if backup.is_file():
        (PREVIEW / 'nginx.conf').write_text(backup.read_text(encoding='ascii'), encoding='ascii')
        run(['nginx', '-t', '-p', str(PREVIEW), '-c', str(PREVIEW / 'nginx.conf')])
        run(['nginx', '-s', 'reload', '-p', str(PREVIEW), '-c', str(PREVIEW / 'nginx.conf')])
    pid = ROUTE_DIR / 'nginx.pid'
    if pid.is_file():
        run(['nginx', '-s', 'stop', '-p', str(ROUTE_DIR), '-c', str(ROUTE_DIR / 'nginx.conf')])
    print(json.dumps({'candidate37_route_rolled_back': True,
                      'artifacts_preserved': True, 'public_route_changed': False}))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--enable', action='store_true')
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    if args.enable == args.rollback:
        parser.error('Choose exactly one of --enable or --rollback')
    if args.enable:
        enable()
    else:
        rollback()
