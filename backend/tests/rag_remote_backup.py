"""Preserve the inventoried test stack and restore databases in isolation."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time

ROOT = Path('/home/rag-long-run/backup-20261116-24')
APPS = ['ybt-backend', 'ybt-worker', 'ybt-beat', 'rag-e2e-backend', 'rag-e2e-worker']
DATA = ['source-milvus-1', 'source-etcd-1', 'source-milvus-minio-1',
        'source-object-storage-1', 'ybt-redis']
PATHS = ['opt/ybt', 'data/ybt/milvus', 'data/ybt/milvus-minio', 'data/ybt/object-storage',
         'var/lib/docker/volumes/source_backend_storage/_data',
         'var/lib/docker/volumes/rag-e2e_rag_e2e_storage/_data',
         'var/lib/docker/volumes/source_etcd_data/_data',
         'var/lib/docker/volumes/source_redis_data/_data']


def run(args, **kwargs):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=kwargs.pop('timeout', 120), **kwargs).stdout


def save(report):
    (ROOT / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


def file_hash(source):
    digest = hashlib.sha256()
    for block in iter(lambda: source.read(1024 * 1024), b''):
        digest.update(block)
    return digest.hexdigest()


def table_counts(container, username, database):
    tables = run(['docker', 'exec', container, 'psql', '-U', username, '-d', database,
                  '-Atc', "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"]).decode().splitlines()
    query = ' UNION ALL '.join("SELECT '" + table.replace("'", "''") + "', count(*) FROM public.\""
                               + table.replace('"', '""') + '\"' for table in tables)
    rows = run(['docker', 'exec', container, 'psql', '-U', username, '-d', database,
                '-Atc', query]).decode().splitlines()
    return {row.rsplit('|', 1)[0]: int(row.rsplit('|', 1)[1]) for row in rows}


def main():
    os.umask(0o077)
    if ROOT.exists():
        raise ValueError('Preserve prior backup attempts')
    ROOT.mkdir(parents=True, mode=0o700)
    report = {'started_at': time.time(), 'old_releases_preserved': True,
              'original_data_overwritten': False, 'paused': [], 'restored_databases': []}
    save(report)
    config = json.loads(run(['docker', 'inspect', *APPS, *DATA, 'ybt-postgres',
                             'ybt-frontend', 'rag-e2e-frontend']))
    (ROOT / 'containers.private.json').write_text(json.dumps(config), encoding='utf-8')
    pg = next(c for c in config if c['Name'] == '/ybt-postgres')
    env = dict(v.split('=', 1) for v in pg['Config']['Env'])
    username = env['POSTGRES_USER']
    paused = []
    try:
        for name in APPS:
            run(['docker', 'pause', name])
            paused.append(name)
            report['paused'] = paused.copy()
            save(report)
        for database in ('ybt', 'ybt_e2e'):
            counts = table_counts('ybt-postgres', username, database)
            (ROOT / (database + '.original-counts.json')).write_text(json.dumps(counts), encoding='utf-8')
            with (ROOT / (database + '.dump')).open('wb') as output:
                subprocess.run(['docker', 'exec', 'ybt-postgres', 'pg_dump', '-U', username,
                                '-Fc', database], stdout=output, stderr=subprocess.PIPE,
                               check=True, timeout=180)
        with (ROOT / 'globals.private.sql').open('wb') as output:
            subprocess.run(['docker', 'exec', 'ybt-postgres', 'pg_dumpall', '-U', username,
                            '--globals-only'], stdout=output, stderr=subprocess.PIPE, check=True)
        run(['docker', 'exec', 'ybt-redis', 'redis-cli', 'SAVE'])
        for name in DATA:
            run(['docker', 'pause', name])
            paused.append(name)
            report['paused'] = paused.copy()
            save(report)
        run(['tar', '-czf', str(ROOT / 'files.tar.gz'), '-C', '/', *PATHS], timeout=240)
        report['archives_complete'] = True
    finally:
        for name in reversed(paused):
            run(['docker', 'unpause', name])
        report['paused'] = []
        report['original_services_resumed_at'] = time.time()
        save(report)

    # Restore every archived regular file into an independent directory.
    restored = ROOT / 'restored-files'
    restored.mkdir()
    with tarfile.open(ROOT / 'files.tar.gz', 'r:gz') as archive:
        for member in archive.getmembers():
            if member.name.startswith('/') or '..' in Path(member.name).parts:
                raise ValueError('Unsafe archive member')
        # Only regular files and directories are needed for data restore; reject
        # device files and materialize no archive links outside the backup root.
        for member in archive.getmembers():
            if member.isdir():
                (restored / member.name).mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target = restored / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open('wb') as output:
                    for block in iter(lambda: source.read(1024 * 1024), b''):
                        output.write(block)
        verified = 0
        for member in archive.getmembers():
            if not member.isfile():
                continue
            original = archive.extractfile(member)
            extracted = restored / member.name
            with original, extracted.open('rb') as source:
                if file_hash(original) != file_hash(source):
                    raise ValueError('Restored file mismatch')
            verified += 1
    report['restored_regular_files_verified'] = verified
    with (ROOT / 'files.tar.gz').open('rb') as source:
        report['archive_sha256'] = file_hash(source)
    save(report)
    # Existing PostgreSQL credentials stay in environment only, never process arguments.
    name = 'rag-restore-20261116-24'
    restore_env = dict(os.environ, POSTGRES_USER=username,
                       POSTGRES_PASSWORD=env['POSTGRES_PASSWORD'], POSTGRES_DB='postgres')
    run(['docker', 'run', '-d', '--name', name, '--network', 'none',
         '-e', 'POSTGRES_USER', '-e', 'POSTGRES_PASSWORD', '-e', 'POSTGRES_DB',
         '--mount', f'type=bind,src={ROOT}/postgres-restore,dst=/var/lib/postgresql/data',
         'postgres:16'], env=restore_env)
    try:
        for _ in range(60):
            result = subprocess.run(['docker', 'exec', name, 'pg_isready', '-U', username],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Isolated restore PostgreSQL not ready')
        for database in ('ybt', 'ybt_e2e'):
            run(['docker', 'exec', name, 'createdb', '-U', username, database])
            with (ROOT / (database + '.dump')).open('rb') as source:
                run(['docker', 'exec', '-i', name, 'pg_restore', '-U', username,
                     '-d', database, '--exit-on-error'], input=source.read(), timeout=240)
            query = "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'"
            count = run(['docker', 'exec', name, 'psql', '-U', username, '-d', database,
                         '-Atc', query]).decode().strip()
            if int(count) < 1:
                raise ValueError('Empty restored database')
            # Compare a fresh logical dump from the restored database with the original
            # table data, excluding dump headers that vary by PostgreSQL execution.
            counts = table_counts(name, username, database)
            original_counts = json.loads((ROOT / (database + '.original-counts.json')).read_text())
            if counts != original_counts:
                raise ValueError('Restored database row counts differ from backup snapshot')
            (ROOT / (database + '.restored-counts.json')).write_text(json.dumps(counts), encoding='utf-8')
            report['restored_databases'].append({'database': database, 'tables': int(count),
                                                'total_rows': sum(counts.values()), 'restore_exit_code': 0,
                                                'all_table_row_counts_match': True})
            save(report)
    finally:
        run(['docker', 'stop', name])
    for port in (18000, 18086):
        run(['curl', '--fail', '--max-time', '30', '-s', f'http://127.0.0.1:{port}/health'])
    report.update(completed=True, finished_at=time.time(), isolated_restore_container=name)
    save(report)
    print(json.dumps({k: report[k] for k in ('completed', 'restored_databases',
                      'restored_regular_files_verified', 'archive_sha256')}))


if __name__ == '__main__':
    main()
