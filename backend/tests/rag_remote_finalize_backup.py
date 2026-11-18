"""Finalize verified backup after probing the actual old application routes."""
import json
from pathlib import Path
import subprocess
import time
import urllib.request

root = Path('/home/rag-long-run/backup-20261116-24')
report = json.loads((root / 'report.json').read_text())
assert report['archives_complete'] and report['restored_regular_files_verified'] > 0
assert not report['paused'] and len(report['restored_databases']) == 2
assert all(d['all_table_row_counts_match'] for d in report['restored_databases'])
services = {}
for port in (18000, 18086):
    for route in ('/health/live', '/version'):
        with urllib.request.urlopen(f'http://127.0.0.1:{port}{route}', timeout=30) as response:
            assert response.status == 200
        services[f'{port}{route}'] = 200
containers = json.loads(subprocess.check_output(['docker', 'inspect', 'ybt-backend', 'ybt-worker',
    'ybt-beat', 'rag-e2e-backend', 'rag-e2e-worker', 'source-milvus-1', 'source-etcd-1',
    'source-milvus-minio-1', 'source-object-storage-1', 'ybt-redis']))
assert all(c['State']['Running'] and not c['State']['Paused'] for c in containers)
report.update(completed=True, finished_at=time.time(), live_and_version_checks=services,
              isolated_restore_container='rag-restore-20261116-24-attempt2',
              initial_verification_error='nonexistent_health_route_404',
              database_and_file_restore_verified=True,
              milvus_engine_restore_verified=False)
(root / 'report.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report))
