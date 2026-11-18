"""Resume only isolated database restore from the completed immutable backup."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time

spec = importlib.util.spec_from_file_location('backup', '/home/rag-remote-backup-20261116-24.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)
root = backup.ROOT
report = json.loads((root / 'report.json').read_text())
if not report.get('archives_complete') or report.get('paused'):
    raise ValueError('Archive incomplete or original services not resumed')
if not report.get('restored_regular_files_verified'):
    raise ValueError('Regular file restore not verified')
config = json.loads((root / 'containers.private.json').read_text())
pg = next(c for c in config if c['Name'] == '/ybt-postgres')
env = dict(v.split('=', 1) for v in pg['Config']['Env'])
username = env['POSTGRES_USER']
name = 'rag-restore-20261116-24-attempt2'
data = root / 'postgres-restore-attempt2'
data.mkdir(mode=0o700)
restore_env = dict(os.environ, POSTGRES_USER=username, POSTGRES_PASSWORD=env['POSTGRES_PASSWORD'],
                   POSTGRES_DB='postgres')
backup.run(['docker', 'run', '-d', '--name', name, '--network', 'none', '-e', 'POSTGRES_USER',
            '-e', 'POSTGRES_PASSWORD', '-e', 'POSTGRES_DB', '--mount',
            f'type=bind,src={data},dst=/var/lib/postgresql/data', 'postgres:16'], env=restore_env)
try:
    for _ in range(60):
        ready = subprocess.run(['docker', 'exec', name, 'pg_isready', '-U', username],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if ready.returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError('Restore database not ready')
    for database in ('ybt', 'ybt_e2e'):
        backup.run(['docker', 'exec', name, 'createdb', '-U', username, database])
        with (root / (database + '.dump')).open('rb') as source:
            backup.run(['docker', 'exec', '-i', name, 'pg_restore', '-U', username, '-d',
                        database, '--exit-on-error'], input=source.read(), timeout=240)
        counts = backup.table_counts(name, username, database)
        expected = json.loads((root / (database + '.original-counts.json')).read_text())
        if counts != expected:
            raise ValueError('Restored table row counts mismatch')
        (root / (database + '.restored-counts.json')).write_text(json.dumps(counts))
        report['restored_databases'].append({'database': database, 'tables': len(counts),
            'total_rows': sum(counts.values()), 'all_table_row_counts_match': True,
            'restore_exit_code': 0})
        backup.save(report)
finally:
    backup.run(['docker', 'stop', name])
for port in (18000, 18086):
    backup.run(['curl', '--fail', '--max-time', '30', '-s', f'http://127.0.0.1:{port}/health'])
report.update(completed=True, finished_at=time.time(), isolated_restore_container=name,
              first_restore_attempt='bind_source_missing_before_database_restore')
backup.save(report)
print(json.dumps({k: report[k] for k in ('completed', 'restored_databases',
                 'restored_regular_files_verified', 'archive_sha256')}))
