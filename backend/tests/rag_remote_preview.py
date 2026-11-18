"""Expose only a loopback preview of the private candidate, preserving public routing."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.error
import urllib.request

ROOT = Path('/home/rag-long-run/releases/candidate-20261116-26')
PREVIEW = Path('/var/tmp/rag-preview-20261116-26')
network = 'rag-candidate-20261116-26'
containers = json.loads(subprocess.check_output(['docker', 'inspect', 'rag-candidate25-api',
                                               'rag-candidate25-frontend']))
addresses = {c['Name'].lstrip('/'): c['NetworkSettings']['Networks'][network]['IPAddress'] for c in containers}
api = addresses['rag-candidate25-api']
frontend = addresses['rag-candidate25-frontend']
checks = {}
for label, url in [('live', f'http://{api}:8000/health/live'),
                   ('version', f'http://{api}:8000/version'),
                   ('ready', f'http://{api}:8000/health/ready'),
                   ('frontend_login', f'http://{frontend}:3000/login')]:
    try:
        with urllib.request.urlopen(url, timeout=45) as response:
            checks[label] = {'status': response.status}
            if label != 'frontend_login':
                checks[label]['body'] = json.load(response)
    except urllib.error.HTTPError as error:
        checks[label] = {'status': error.code, 'body': json.load(error)}
assert checks['live']['status'] == 200 and checks['version']['status'] == 200
assert checks['frontend_login']['status'] == 200
report = json.loads((ROOT / 'release-report.json').read_text())
assert checks['version']['body']['app_commit'] == report['app_commit']
PREVIEW.mkdir(mode=0o755)
temp = PREVIEW / 'client_body'
temp.mkdir(mode=0o700)
shutil.chown(temp, user='www-data', group='www-data')
config = '''user www-data;
pid %s/nginx.pid;
error_log %s/error.log warn;
events { worker_connections 256; }
http {
  access_log %s/access.log;
  client_body_temp_path %s/client_body;
  client_max_body_size 50m;
  server {
    listen 127.0.0.1:18089;
    server_name _;
    proxy_read_timeout 300s;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    location /api/ { proxy_pass http://%s:8000/api/; }
    location /health/ { proxy_pass http://%s:8000/health/; }
    location = /version { proxy_pass http://%s:8000/version; }
    location / { proxy_pass http://%s:3000; }
  }
}
''' % (PREVIEW, PREVIEW, PREVIEW, PREVIEW, api, api, api, frontend)
path = PREVIEW / 'nginx.conf'
path.write_text(config)
subprocess.run(['nginx', '-t', '-p', str(PREVIEW), '-c', str(path)], check=True)
subprocess.run(['nginx', '-p', str(PREVIEW), '-c', str(path)], check=True)
report.update(actual_host_published_ports=[],
    docker_internal_network_has_no_public_port_mapping=True,
    preview_loopback_port=18089, preview_config_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    preview_pid_file=str(PREVIEW / 'nginx.pid'), health_checks=checks,
    public_routing_switched=False, model_requests_enabled=False)
(ROOT / 'release-report.json').write_text(json.dumps(report, indent=2))
with urllib.request.urlopen('http://127.0.0.1:18089/login', timeout=30) as response:
    assert response.status == 200
print(json.dumps(report))
