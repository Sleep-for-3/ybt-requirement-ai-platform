"""Create an isolated candidate37 beside the preserved remote test releases.

The default mode is read-only. --execute creates new candidate37 resources but
never stops/replaces an older release, changes the public route, or runs schema
migrations. All candidate data and logs remain under the new release directory.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import shutil
import sqlite3
import subprocess
import tarfile
import time
import urllib.request
from urllib.parse import urlsplit, urlunsplit


ROOT = Path('/home/rag-long-run/releases/candidate-20261116-37-attempt2')
SOURCE = Path('/home/source.tar.gz')
MANIFEST = Path('/home/release-manifest.json')
NETWORK = 'rag-candidate-20261116-37'
TAG = 'rag-longrun-20261116-37'
PREVIEW_PORT = 18137
SOURCE_API = 'rag-candidate28-api'
SOURCE_DB = 'rag-candidate25-postgres'
SOURCE_EMBEDDING = 'rag-candidate25-embedding'
BASE_IMAGE = 'ybt-backend:rag-longrun-20261116-28'
BACKUP_ROOT = Path('/home/rag-long-run/backup-20261116-24')
VECTOR_REPORT = BACKUP_ROOT / 'report.json'
VECTOR_COUNTS = BACKUP_ROOT / 'vector-original-counts.json'
VECTOR_ETCD_SOURCE = BACKUP_ROOT / 'restored-files/var/lib/docker/volumes/source_etcd_data/_data'
VECTOR_MINIO_SOURCE = BACKUP_ROOT / 'restored-files/data/ybt/milvus-minio'
VECTOR_MILVUS_SOURCE = BACKUP_ROOT / 'restored-files/data/ybt/milvus'
VECTOR_ETCD_CONFIG = 'source-etcd-1'
VECTOR_MINIO_CONFIG = 'source-milvus-minio-1'
VECTOR_MILVUS_CONFIG = 'source-milvus-1'
EXPECTED_SOURCE_HASH = 'f30a4cd5116b40582cd13a5159182c1ba59507f1b4b72662534f5eec971e8476'
EXPECTED_SOURCE_CANDIDATE_HASH = 'd181c0a380835b86fc7a05dae9a3711d0078440090857d825780c1c1903f50f7'
os.umask(0o077)


def run(command, *, timeout=120, input_data=None, stdout=subprocess.PIPE, env=None, stdin=None):
    return subprocess.run(command, check=True, stdout=stdout, stderr=subprocess.PIPE,
                          timeout=timeout, input=input_data, env=env, stdin=stdin)


def inspect(name):
    return json.loads(run(['docker', 'inspect', name]).stdout)[0]


def container_env(name):
    entries = inspect(name)['Config']['Env'] or []
    return dict(item.split('=', 1) for item in entries if '=' in item)


def database_url_for_candidate(value):
    parsed = urlsplit(value)
    if parsed.scheme not in ('postgresql', 'postgresql+psycopg', 'postgresql+psycopg2'):
        raise RuntimeError('Source database URL is not PostgreSQL')
    userinfo = parsed.netloc.rsplit('@', 1)[0]
    return urlunsplit((parsed.scheme, userinfo + '@postgres:5432', parsed.path or '/ybt',
                       parsed.query, ''))


def table_counts(container, user, database):
    tables = run(['docker', 'exec', container, 'psql', '-U', user, '-d', database, '-Atc',
                  "SELECT schemaname || E'\\t' || tablename FROM pg_tables "
                  "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') ORDER BY 1"]
                 ).stdout.decode().splitlines()
    parsed = []
    for row in tables:
        schema, table = row.split('\t', 1)
        if not re.fullmatch(r'[A-Za-z0-9_]+', schema) or not re.fullmatch(r'[A-Za-z0-9_]+', table):
            raise RuntimeError('Unexpected database identifier in source catalog')
        parsed.append((schema, table))
    if not parsed:
        raise RuntimeError('Candidate database contains no application tables')
    terms = ["SELECT '" + schema + '.' + table + "', count(*) FROM \"" + schema +
             "\".\"" + table + "\"" for schema, table in parsed]
    query = ' UNION ALL '.join(terms) + ' ORDER BY 1'
    rows = run(['docker', 'exec', container, 'psql', '-U', user, '-d', database, '-Atc', query]
               ).stdout.decode().splitlines()
    return dict(row.rsplit('|', 1) for row in rows)


def verify_package():
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if manifest.get('source_hash') != EXPECTED_SOURCE_HASH:
        raise RuntimeError('Release source identity does not match the approved checkpoint')
    if manifest.get('credentials_included') is not False or manifest.get('database_or_uploads_included') is not False:
        raise RuntimeError('Release manifest includes prohibited runtime material')
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != manifest.get('archive_sha256'):
        raise RuntimeError('Release archive hash mismatch')
    names = set(manifest.get('source_files', {}))
    if any(PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts
           or '\\' in name for name in names):
        raise RuntimeError('Release manifest contains an unsafe relative path')
    with tarfile.open(SOURCE, 'r:gz') as archive:
        members = archive.getmembers()
        if any(not member.isfile() or member.name not in names for member in members):
            raise RuntimeError('Release archive has an unexpected path or non-file member')
        if {member.name for member in members} != names:
            raise RuntimeError('Release archive contents differ from manifest')
    return manifest


def extract_package(destination, archive_path, manifest):
    if destination.exists():
        if not destination.is_dir() or any(destination.iterdir()):
            raise RuntimeError('Release extraction destination must be a new empty directory')
    else:
        destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    seen = set()
    with tarfile.open(archive_path, 'r:gz') as archive:
        for member in archive.getmembers():
            if not member.isfile() or member.name not in manifest['source_files'] or member.name in seen:
                raise RuntimeError('Release archive contains an unsafe or duplicate member')
            seen.add(member.name)
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            source_file = archive.extractfile(member)
            if source_file is None:
                raise RuntimeError('Release archive member cannot be read')
            with source_file, target.open('xb') as output:
                shutil.copyfileobj(source_file, output)
            target.chmod(0o644)
    if seen != set(manifest['source_files']):
        raise RuntimeError('Release archive contents differ from manifest')
    for name, digest in manifest['source_files'].items():
        target = destination / name
        if target.is_symlink() or not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise RuntimeError('Extracted source file verification failed')


def preflight(manifest):
    if ROOT.exists():
        raise RuntimeError('Candidate37 release path already exists; refusing to reuse it')
    if shutil.disk_usage('/').free < 3 * 1024**3:
        raise RuntimeError('Root filesystem has less than 3 GiB free')
    if shutil.disk_usage('/home').free < 3 * 1024**3:
        raise RuntimeError('Home filesystem has less than 3 GiB free')
    for command in (['docker', 'network', 'inspect', NETWORK],
                    ['docker', 'volume', 'inspect', 'rag-candidate37-pgdata']):
        if subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            raise RuntimeError('A candidate37 Docker resource already exists')
    for name in ('rag-candidate37-etcd', 'rag-candidate37-minio', 'rag-candidate37-milvus',
                 'rag-candidate37-postgres', 'rag-candidate37-redis', 'rag-candidate37-api',
                 'rag-candidate37-worker', 'rag-candidate37-frontend'):
        if subprocess.run(['docker', 'inspect', name], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0:
            raise RuntimeError('A candidate37 container name already exists')
    for image in ('ybt-backend:' + TAG, 'ybt-frontend:' + TAG):
        if subprocess.run(['docker', 'image', 'inspect', image], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0:
            raise RuntimeError('A candidate37 image tag already exists')
    old_api, old_db = inspect(SOURCE_API), inspect(SOURCE_DB)
    if old_api['State']['Status'] != 'running' or old_db['State']['Status'] != 'running':
        raise RuntimeError('Existing source candidate services are not running')
    if old_api['Config']['Image'] != 'ybt-backend:rag-longrun-20261116-28':
        raise RuntimeError('Unexpected source candidate image')
    if old_db['Config']['Image'] != 'postgres:16':
        raise RuntimeError('Unexpected source database image')
    if not Path('/var/run/docker.sock').exists():
        raise RuntimeError('Docker daemon is unavailable')
    if not run(['docker', 'image', 'inspect', BASE_IMAGE]).stdout:
        raise RuntimeError('Pinned backend base image is unavailable')
    if not shutil.which('nginx'):
        raise RuntimeError('Standalone Nginx is unavailable')
    with socket.socket() as listener:
        try:
            listener.bind(('127.0.0.1', PREVIEW_PORT))
        except OSError as exc:
            raise RuntimeError('Candidate37 preview port is already occupied') from exc
    for name in (SOURCE_EMBEDDING,):
        if inspect(name)['State']['Status'] != 'running':
            raise RuntimeError('Existing read-only retrieval dependency is not running')
    proof = json.loads(VECTOR_REPORT.read_text(encoding='utf-8'))
    if not (proof.get('completed') and proof.get('milvus_engine_restore_verified')
            and proof.get('vector_collection_stats_match') and proof.get('vector_collections') == 7):
        raise RuntimeError('The archived independent vector restore proof is incomplete')
    for path in (VECTOR_COUNTS, VECTOR_ETCD_SOURCE, VECTOR_MINIO_SOURCE, VECTOR_MILVUS_SOURCE):
        if not path.exists():
            raise RuntimeError('An archived vector restore input is missing')
    vector_bytes = sum(path.stat().st_size for root in
        (VECTOR_ETCD_SOURCE, VECTOR_MINIO_SOURCE, VECTOR_MILVUS_SOURCE)
        for path in root.rglob('*') if path.is_file())
    if shutil.disk_usage('/home').free < vector_bytes + 2 * 1024**3:
        raise RuntimeError('Insufficient /home capacity for isolated vector copy plus safety margin')
    source_env = container_env(SOURCE_API)
    if not source_env.get('DATABASE_URL'):
        raise RuntimeError('Source application database configuration is incomplete')
    pg_env = container_env(SOURCE_DB)
    if not all(pg_env.get(key) for key in ('POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB')):
        raise RuntimeError('Source PostgreSQL bootstrap configuration is incomplete')
    source_db_url = urlsplit(source_env['DATABASE_URL'])
    if (source_db_url.path.strip('/') or pg_env['POSTGRES_DB']) != pg_env['POSTGRES_DB']:
        raise RuntimeError('Source application and PostgreSQL database names do not match')
    with urllib.request.urlopen('http://127.0.0.1:18089/version', timeout=8) as response:
        source_version = json.load(response)
    expected_identity_suffix = '+worktree.' + EXPECTED_SOURCE_CANDIDATE_HASH[:12]
    if not str(source_version.get('app_commit', '')).endswith(expected_identity_suffix):
        raise RuntimeError('Existing candidate28 source identity differs from the reviewed database baseline')
    budget = urllib.request.urlopen('http://127.0.0.1:18090/health', timeout=8)
    relay = json.load(budget)
    if relay.get('status') != 'ready' or relay.get('budget') != 'central-local-ledger':
        raise RuntimeError('Shared model budget relay health check failed')
    return {'source_api': SOURCE_API, 'source_database': SOURCE_DB,
            'source_hash': manifest['source_hash'], 'base_image': BASE_IMAGE,
            'root_free_bytes': shutil.disk_usage('/').free,
            'home_free_bytes': shutil.disk_usage('/home').free,
            'relay_ready': True, 'model_budget': {'max_new_provider_requests': 0,
            'max_new_total_tokens': 0}, 'public_route_change': False,
            'database_migration': False, 'independent_vector_backup_verified': True,
            'vector_collections': proof['vector_collections'],
            'isolated_vector_copy_bytes': vector_bytes,
            'shared_milvus_connection': False}


def start_container(name, image, command, env, *, mounts=(), aliases=()):
    args = ['docker', 'run', '-d', '--name', name, '--network', NETWORK]
    for alias in aliases:
        args += ['--network-alias', alias]
    for key in env:
        args += ['-e', key]
    for src, dst in mounts:
        args += ['--mount', f'type=bind,src={src},dst={dst}']
    args += [image, *command]
    return run(args, timeout=180, env={**os.environ, **env}).stdout.decode().strip()


def archived_container(name):
    configs = json.loads((BACKUP_ROOT / 'containers.private.json').read_text(encoding='utf-8'))
    return next(item for item in configs if item.get('Name', '').lstrip('/') == name)


def start_vector_component(original_name, candidate_name, alias, data_source, data_target,
                           *, overrides=None, data_root=None):
    config = archived_container(original_name)
    environment = dict(value.split('=', 1) for value in config['Config']['Env'] if '=' in value)
    environment.update(overrides or {})
    command = ['docker', 'run', '-d', '--name', candidate_name, '--network', NETWORK,
               '--network-alias', alias]
    for key in environment:
        command += ['-e', key]
    for option in config['HostConfig'].get('SecurityOpt') or []:
        command += ['--security-opt', option]
    command += ['--mount', f'type=bind,src={data_source},dst={data_target}',
                config['Config']['Image'], *(config['Config'].get('Cmd') or [])]
    run(command, timeout=180, env={**os.environ, **environment})


def verify_candidate_vector_copy(token):
    probe = ('import json,os,time; from pymilvus import MilvusClient; '
             'c=MilvusClient(uri=os.environ["MILVUS_URI"],token=os.environ.get("MILVUS_TOKEN",""),timeout=10); '
             'names=sorted(c.list_collections()); '
             'print(json.dumps({n:c.get_collection_stats(n) for n in names},sort_keys=True))')
    env = {**os.environ, 'MILVUS_URI': 'http://milvus:19530', 'MILVUS_TOKEN': token or ''}
    result = run(['docker', 'run', '--rm', '--network', NETWORK, '-e', 'MILVUS_URI',
                  '-e', 'MILVUS_TOKEN', 'ybt-backend:' + TAG, 'python', '-c', probe],
                 timeout=45, env=env).stdout.decode()
    actual = json.loads(result)
    expected = json.loads(VECTOR_COUNTS.read_text(encoding='utf-8'))
    if actual != expected:
        raise RuntimeError('Candidate isolated Milvus collections differ from verified backup stats')
    return actual


def export_incremental_vector_collections(source_environment):
    backup_json = json.dumps(json.loads(VECTOR_COUNTS.read_text(encoding='utf-8')))
    script = '''import json,os
from pymilvus import MilvusClient
c=MilvusClient(uri=os.environ["MILVUS_URI"],token=os.environ.get("MILVUS_TOKEN",""),timeout=12)
base=json.loads(''' + repr(backup_json) + ''')
result={}
for name in sorted(c.list_collections()):
 if not name.startswith("rag_candidate25_") or name in base: continue
 stats=c.get_collection_stats(name)
 description=c.describe_collection(name)
 indexes=c.describe_index(name,index_name="vector")
 rows=[]
 iterator=c.query_iterator(collection_name=name,batch_size=128,filter="id != ''",output_fields=["*"])
 try:
  while True:
   batch=iterator.next()
   if not batch: break
   rows.extend(batch)
 finally: iterator.close()
 result[name]={"stats":stats,"dimension":next(int(f["params"]["dim"]) for f in description["fields"] if f["name"]=="vector"),"index":indexes,"rows":rows}
print(json.dumps(result,separators=(",",":")))
'''
    env = {key: value for key, value in source_environment.items()
           if key in ('MILVUS_URI', 'MILVUS_TOKEN') and value}
    env.setdefault('MILVUS_URI', 'http://milvus:19530')
    result = run(['docker', 'exec', '-i', SOURCE_API, 'python', '-'], input_data=script.encode('utf-8'),
                 timeout=90, env={**os.environ, **env}).stdout
    return json.loads(result)


def import_incremental_vector_collections(collections, token):
    script = '''import json,os,sys
from pymilvus import MilvusClient
c=MilvusClient(uri=os.environ["MILVUS_URI"],token=os.environ.get("MILVUS_TOKEN",""),timeout=12)
data=json.load(sys.stdin)
for name,item in data.items():
 idx=item["index"]
 if idx.get("field_name")!="vector" or idx.get("index_type")!="AUTOINDEX" or idx.get("metric_type")!="COSINE":
  raise RuntimeError("Incremental collection index contract is unexpected")
 if not c.has_collection(name):
  c.create_collection(collection_name=name,dimension=item["dimension"],metric_type="COSINE",auto_id=False,
   primary_field_name="id",id_type="string",max_length=128,vector_field_name="vector",enable_dynamic_field=True)
  if item["rows"]: c.insert(collection_name=name,data=item["rows"])
  c.flush(collection_name=name)
 actual=c.get_collection_stats(name)
 if actual != item["stats"]: raise RuntimeError("Incremental collection row count did not match")
print(json.dumps({n:c.get_collection_stats(n) for n in data},sort_keys=True))
'''
    payload = json.dumps(collections, separators=(',', ':')).encode('utf-8')
    env = {'MILVUS_URI': 'http://milvus:19530', 'MILVUS_TOKEN': token or ''}
    result = subprocess.run(['docker', 'run', '--rm', '-i', '--network', NETWORK,
                  '-e', 'MILVUS_URI', '-e', 'MILVUS_TOKEN', 'ybt-backend:' + TAG,
                  'python', '-c', script], input=payload, stdout=subprocess.PIPE,
                  stderr=subprocess.PIPE, timeout=120, env={**os.environ, **env})
    if result.returncode:
        raise RuntimeError('Candidate vector import failed: ' + result.stderr.decode(errors='replace')[-1200:])
    return json.loads(result.stdout)


def sync_existing_candidate_vector_stack():
    if not ROOT.is_dir():
        raise RuntimeError('Candidate37 attempt directory does not exist')
    for name in ('rag-candidate37-milvus', 'rag-candidate37-minio', 'rag-candidate37-etcd'):
        if inspect(name)['State']['Status'] != 'running':
            raise RuntimeError('Candidate37 isolated vector service is not running')
    source_env = container_env(SOURCE_API)
    additions = export_incremental_vector_collections(source_env)
    archived = json.loads(VECTOR_COUNTS.read_text(encoding='utf-8'))
    for name, stats in archived.items():
        source_stats = json.loads(run(['docker', 'exec', '-i', SOURCE_API, 'python', '-'],
            input_data=(('from pymilvus import MilvusClient; import os,json; '
                'c=MilvusClient(uri=os.environ.get("MILVUS_URI","http://milvus:19530"),'
                'token=os.environ.get("MILVUS_TOKEN",""),timeout=8); '
                f'print(json.dumps(c.get_collection_stats("{name}")))').encode('utf-8')), timeout=20,
            env={**os.environ, **{k: v for k, v in source_env.items()
                if k in ('MILVUS_URI', 'MILVUS_TOKEN') and v}}).stdout)
        if source_stats != stats:
            raise RuntimeError('Archived collection differs from current source collection: ' + name)
    if not additions:
        raise RuntimeError('No incremental source collections were found')
    for name, value in additions.items():
        if not name.startswith('rag_candidate25_') or value['stats'].get('row_count') != len(value['rows']):
            raise RuntimeError('Incremental collection export is incomplete')
    token = source_env.get('MILVUS_TOKEN', '')
    imported = import_incremental_vector_collections(additions, token)
    expected = {**archived, **{name: value['stats'] for name, value in additions.items()}}
    probe = ('import json,os; from pymilvus import MilvusClient; '
             'c=MilvusClient(uri="http://milvus:19530",timeout=10); '
             'n=sorted(c.list_collections()); print(json.dumps({x:c.get_collection_stats(x) for x in n},sort_keys=True))')
    actual = json.loads(run(['docker', 'run', '--rm', '--network', NETWORK,
        'ybt-backend:' + TAG, 'python', '-c', probe], timeout=60).stdout)
    if actual != expected:
        raise RuntimeError('Candidate37 independent vector collection set differs from current source')
    report_path = ROOT / 'vector-sync-attempt.json'
    report_path.write_text(json.dumps({'source_collections': len(expected),
        'archived_collections_verified': len(archived), 'incremental_collections_imported': len(additions),
        'incremental_collection_stats': {name: value['stats'] for name, value in additions.items()},
        'candidate_collection_stats_match': True, 'source_mutations': 0}, indent=2) + '\n', encoding='utf-8')
    return json.loads(report_path.read_text(encoding='utf-8'))


def continue_candidate_after_vector_sync():
    vector_report = json.loads((ROOT / 'vector-sync-attempt.json').read_text(encoding='utf-8'))
    if not vector_report.get('candidate_collection_stats_match'):
        raise RuntimeError('Candidate vector snapshot has not passed parity verification')
    release_report = json.loads((ROOT / 'release-report.json').read_text(encoding='utf-8'))
    if not (release_report.get('steps') and 'frontend_built' in release_report['steps']):
        raise RuntimeError('Candidate images are not fully built')
    identity = EXPECTED_SOURCE_CANDIDATE_HASH
    identity = json.loads((ROOT / 'backend/candidate-build-info.json').read_text())['app_commit']
    if not (ROOT / 'private/BUDGET.json').is_file() or not (ROOT / 'private/provider-budget.sqlite3').is_file():
        raise RuntimeError('Candidate zero-budget guard files are missing')
    private = ROOT / 'private'
    report = release_report
    report_path = ROOT / 'release-report.json'

    def save():
        report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

    old_db_env = container_env(SOURCE_DB)
    pg_env = {key: old_db_env[key] for key in ('POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB')}
    source_app_env = container_env(SOURCE_API)
    db_name = urlsplit(source_app_env['DATABASE_URL']).path.strip('/')
    if db_name != pg_env['POSTGRES_DB']:
        raise RuntimeError('Source database name changed since the candidate snapshot')
    run(['docker', 'network', 'connect', '--alias', 'embedding', NETWORK, SOURCE_EMBEDDING])
    run(['docker', 'volume', 'create', 'rag-candidate37-pgdata'])
    pg_args = ['docker', 'run', '-d', '--name', 'rag-candidate37-postgres', '--network', NETWORK,
               '--network-alias', 'postgres', '--mount',
               'type=volume,src=rag-candidate37-pgdata,dst=/var/lib/postgresql/data']
    for key in pg_env:
        pg_args += ['-e', key]
    pg_args += ['postgres:16']
    run(pg_args, env={**os.environ, **pg_env})
    for _ in range(60):
        if subprocess.run(['docker', 'exec', 'rag-candidate37-postgres', 'pg_isready',
                           '-U', pg_env['POSTGRES_USER'], '-d', pg_env['POSTGRES_DB']],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            break
        time.sleep(2)
    else:
        raise RuntimeError('Candidate37 PostgreSQL did not become ready')
    dump_path = ROOT / 'postgres-candidate-snapshot.dump'
    if dump_path.exists() and dump_path.stat().st_size:
        raise RuntimeError('A prior database snapshot exists; refusing to overwrite it')
    dump_path.touch(mode=0o600)
    dump_path.chmod(0o600)
    with dump_path.open('wb') as output:
        subprocess.run(['docker', 'exec', SOURCE_DB, 'pg_dump', '-U', pg_env['POSTGRES_USER'],
                        '-d', db_name, '-Fc', '--no-owner', '--no-acl'], check=True,
                       stdout=output, stderr=subprocess.PIPE, timeout=900)
    with dump_path.open('rb') as source:
        listed = subprocess.run(['docker', 'exec', '-i', 'rag-candidate37-postgres',
                                 'pg_restore', '--list'], stdin=source,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if listed.returncode or not listed.stdout.strip():
        raise RuntimeError('Candidate database snapshot archive validation failed')
    with dump_path.open('rb') as source:
        restore = subprocess.Popen(['docker', 'exec', '-i', 'rag-candidate37-postgres',
            'pg_restore', '-U', pg_env['POSTGRES_USER'], '-d', pg_env['POSTGRES_DB'],
            '--no-owner', '--no-acl'], stdin=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _stdout, stderr = restore.communicate(timeout=900)
    if restore.returncode:
        raise RuntimeError('Candidate database restore failed: ' + stderr.decode(errors='replace')[-1200:])
    source_schema = run(['docker', 'exec', SOURCE_DB, 'psql', '-U', pg_env['POSTGRES_USER'],
        '-d', db_name, '-Atc', 'SELECT version_num FROM alembic_version ORDER BY version_num']
        ).stdout.decode().splitlines()
    target_schema = run(['docker', 'exec', 'rag-candidate37-postgres', 'psql', '-U',
        pg_env['POSTGRES_USER'], '-d', pg_env['POSTGRES_DB'], '-Atc',
        'SELECT version_num FROM alembic_version ORDER BY version_num']).stdout.decode().splitlines()
    source_rows = table_counts(SOURCE_DB, pg_env['POSTGRES_USER'], db_name)
    target_rows = table_counts('rag-candidate37-postgres', pg_env['POSTGRES_USER'], pg_env['POSTGRES_DB'])
    if not source_schema or source_schema != target_schema or source_rows != target_rows:
        raise RuntimeError('Candidate database restore schema/row parity failed')
    report.update(steps=[*report['steps'], 'consistent_database_dump_restored'],
        database_schema_head=target_schema, database_table_counts=source_rows)
    save()
    storage_source = Path('/home/rag-long-run/releases/candidate-20261116-26/storage')
    storage = ROOT / 'storage'
    if not storage.is_dir():
        shutil.copytree(storage_source, storage, symlinks=False)
    if any(p.is_symlink() for p in storage.rglob('*')):
        raise RuntimeError('Candidate storage contains a symlink')
    source_env = dict(source_app_env)
    source_env.update(DATABASE_URL=database_url_for_candidate(source_app_env['DATABASE_URL']),
        CELERY_BROKER_URL='redis://redis:6379/0', CELERY_RESULT_BACKEND='redis://redis:6379/1',
        REDIS_URL='redis://redis:6379/0', MILVUS_URI='http://milvus:19530',
        EMBEDDING_BASE_URL='http://embedding:11434/v1', MILVUS_COLLECTION_PREFIX='rag_candidate25',
        STORAGE_DIR='/app/storage', APP_COMMIT=identity,
        RAG_MODEL_BUDGET_PATH='/candidate-private/BUDGET.json',
        RAG_MODEL_BUDGET_STATE='/candidate-private/provider-budget.sqlite3',
        RAG_MODEL_BUDGET_REQUIRED='true', CITATION_SUPPORT_CHECK='off')
    for key in tuple(source_env):
        if key.endswith('_API_KEY') or key == 'RAG_RELAY_KEY':
            source_env.pop(key, None)
    env_path = private / 'environment.private.json'
    env_path.write_text(json.dumps(source_env, indent=2) + '\n', encoding='utf-8')
    env_path.chmod(0o600)
    run(['docker', 'run', '-d', '--name', 'rag-candidate37-redis', '--network', NETWORK,
         '--network-alias', 'redis', 'redis:7-alpine'])
    mounts = ((storage, '/app/storage'), (private, '/candidate-private'))
    for component, command in (
        ('api', ['uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '8000']),
        ('worker', ['celery', '-A', 'app.workers.celery_app', 'worker', '--pool=solo',
                    '--concurrency=1', '--loglevel=INFO']),
    ):
        start_container('rag-candidate37-' + component, 'ybt-backend:' + TAG,
            command, {**source_env, 'SERVICE_COMPONENT': component}, mounts=mounts,
            aliases=('backend',) if component == 'api' else ())
    start_container('rag-candidate37-frontend', 'ybt-frontend:' + TAG, [], {})
    api_ip = inspect('rag-candidate37-api')['NetworkSettings']['Networks'][NETWORK]['IPAddress']
    web_ip = inspect('rag-candidate37-frontend')['NetworkSettings']['Networks'][NETWORK]['IPAddress']
    preview = ROOT / 'preview'
    (preview / 'logs').mkdir(parents=True, mode=0o700, exist_ok=True)
    nginx_conf = preview / 'nginx.conf'
    nginx_conf.write_text(f'''pid {preview}/logs/nginx.pid;
error_log {preview}/logs/error.log warn;
events {{ worker_connections 128; }}
http {{
  access_log {preview}/logs/access.log;
  server {{
    listen 127.0.0.1:{PREVIEW_PORT};
    location = /version {{ proxy_pass http://{api_ip}:8000/version; }}
    location = /health/ready {{ proxy_pass http://{api_ip}:8000/health/ready; }}
    location /api/ {{ proxy_pass http://{api_ip}:8000; proxy_read_timeout 200s; }}
    location / {{ proxy_pass http://{web_ip}:3000; proxy_set_header Host $host; }}
  }}
}}
''', encoding='ascii')
    run(['nginx', '-t', '-p', str(preview), '-c', str(nginx_conf)])
    run(['nginx', '-p', str(preview), '-c', str(nginx_conf)])
    version = wait_http(f'http://127.0.0.1:{PREVIEW_PORT}/version', expected=identity)
    wait_http(f'http://127.0.0.1:{PREVIEW_PORT}/health/ready')
    with urllib.request.urlopen(f'http://127.0.0.1:{PREVIEW_PORT}/login', timeout=10) as response:
        if response.status != 200:
            raise RuntimeError('Candidate frontend login page is not ready')
    report.update(steps=[*report['steps'], 'candidate_api_worker_frontend_ready'], version=version,
        preview_url=f'http://127.0.0.1:{PREVIEW_PORT}/login', model_requests_made=0,
        public_route_changed=False, schema_migration_run=False,
        old_release_changed=False, independent_milvus=True)
    save()
    return report


def wait_http(url, *, expected=None, timeout_seconds=120):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                payload = json.load(response) if expected is not None else None
                if expected is not None and payload.get('app_commit') != expected:
                    raise RuntimeError('Candidate identity mismatch')
                return payload
        except RuntimeError:
            raise
        except Exception:
            time.sleep(2)
    raise RuntimeError('Candidate readiness deadline exceeded')


def execute(manifest):
    report = preflight(manifest)
    ROOT.mkdir(parents=True, mode=0o700, exist_ok=False)
    report_path = ROOT / 'release-report.json'
    report.update(started_at=datetime.now(timezone.utc).isoformat(), steps=['preflight_passed'])

    def save():
        report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

    try:
        extract_package(ROOT, SOURCE, manifest)
        identity = manifest['git_head'] + '+worktree.' + manifest['source_hash'][:12]
        build_time = datetime.now(timezone.utc).isoformat()
        backend = ROOT / 'backend'
        dockerfile = backend / 'Dockerfile.candidate'
        dockerfile.write_text(
            f'FROM {BASE_IMAGE}\nWORKDIR /app\n'
            'RUN rm -rf /app/app /app/scripts /app/alembic\n'
            'COPY app ./app\nCOPY scripts ./scripts\nCOPY alembic ./alembic\n'
            'COPY alembic.ini requirements.txt requirements.lock.txt ./\n'
            'COPY candidate-build-info.json ./build-info.json\n', encoding='ascii')
        (backend / 'candidate-build-info.json').write_text(json.dumps(
            {'app_commit': identity, 'build_time': build_time}), encoding='ascii')
        if hashlib.sha256((backend / 'requirements.lock.txt').read_bytes()).hexdigest() != \
                manifest['source_files']['backend/requirements.lock.txt']:
            raise RuntimeError('Dependency lock mismatch')
        with (ROOT / 'backend-build.log').open('wb') as log:
            run(['docker', 'build', '-f', str(dockerfile), '-t', 'ybt-backend:' + TAG, str(backend)],
                timeout=1200, stdout=log)
        report['steps'].append('backend_built')
        save()
        with (ROOT / 'frontend-build.log').open('wb') as log:
            run(['docker', 'build', '-t', 'ybt-frontend:' + TAG,
                 '--build-arg', 'NPM_REGISTRY=https://registry.npmmirror.com',
                 '--build-arg', 'NEXT_PUBLIC_API_BASE_URL=/api',
                 '--build-arg', 'NEXT_PUBLIC_APP_COMMIT=' + identity,
                 '--build-arg', 'NEXT_PUBLIC_BUILD_TIME=' + build_time, str(ROOT / 'frontend')],
                timeout=1500, stdout=log)
        report['steps'].append('frontend_built')
        save()

        private = ROOT / 'private'
        private.mkdir(mode=0o700)
        summary = {'scope': 'candidate37-zero-model-until-explicit-budget-authorization',
                   'max_new_provider_requests': 0, 'max_new_total_tokens': 0,
                   'provider_requests_used': 0, 'provider_requests_reserved': 0,
                   'total_tokens_used': 0, 'total_tokens_reserved': 0, 'unknown_usage_requests': 0}
        (private / 'BUDGET.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='ascii')
        db_state = private / 'provider-budget.sqlite3'
        with sqlite3.connect(db_state) as db:
            db.execute('CREATE TABLE limits (scope TEXT, requests INTEGER, tokens INTEGER)')
            db.execute('CREATE TABLE attempts (id TEXT PRIMARY KEY, model TEXT, reserved INTEGER, '
                       'charged INTEGER, unknown INTEGER, created_at TEXT, finished_at TEXT)')
        old_db_env = container_env(SOURCE_DB)
        pg_env = {key: old_db_env[key] for key in ('POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB')
                  if key in old_db_env}
        if set(pg_env) != {'POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB'}:
            raise RuntimeError('Source database bootstrap environment is incomplete')
        run(['docker', 'network', 'create', '--internal', NETWORK])
        report['steps'].append('private_internal_network_created')
        save()
        vector_data = ROOT / 'vector-data'
        vector_data.mkdir(mode=0o700)
        vector_paths = {
            'etcd': (VECTOR_ETCD_SOURCE, vector_data / 'etcd', '/etcd'),
            'minio': (VECTOR_MINIO_SOURCE, vector_data / 'minio', '/minio_data'),
            'milvus': (VECTOR_MILVUS_SOURCE, vector_data / 'milvus', '/var/lib/milvus'),
        }
        for source, target, _container_path in vector_paths.values():
            shutil.copytree(source, target, symlinks=False, copy_function=shutil.copy2)
            if any(path.is_symlink() for path in target.rglob('*')):
                raise RuntimeError('Archived vector copy contains a symlink')
        start_vector_component(VECTOR_ETCD_CONFIG, 'rag-candidate37-etcd', 'etcd',
                               vector_paths['etcd'][1], vector_paths['etcd'][2])
        start_vector_component(VECTOR_MINIO_CONFIG, 'rag-candidate37-minio', 'milvus-minio',
                               vector_paths['minio'][1], vector_paths['minio'][2])
        start_vector_component(VECTOR_MILVUS_CONFIG, 'rag-candidate37-milvus', 'milvus',
                               vector_paths['milvus'][1], vector_paths['milvus'][2],
                               overrides={'ETCD_ENDPOINTS': 'etcd:2379',
                                          'MINIO_ADDRESS': 'milvus-minio:9000'})
        report['steps'].append('independent_vector_stack_started_from_verified_backup_copy')
        save()
        for _ in range(60):
            try:
                vector_stats = verify_candidate_vector_copy(container_env(SOURCE_API).get('MILVUS_TOKEN', ''))
                break
            except Exception:
                time.sleep(2)
        else:
            raise RuntimeError('Candidate independent vector stack did not match backup evidence')
        report['candidate_vector_collections'] = len(vector_stats)
        report['steps'].append('independent_vector_stats_matched_before_api_start')
        save()
        run(['docker', 'network', 'connect', '--alias', 'embedding', NETWORK, SOURCE_EMBEDDING])
        run(['docker', 'volume', 'create', 'rag-candidate37-pgdata'])
        pg_args = ['docker', 'run', '-d', '--name', 'rag-candidate37-postgres', '--network', NETWORK,
                   '--network-alias', 'postgres', '--mount',
                   'type=volume,src=rag-candidate37-pgdata,dst=/var/lib/postgresql/data']
        for key in pg_env:
            pg_args += ['-e', key]
        pg_args += ['postgres:16']
        run(pg_args, env={**os.environ, **pg_env})
        for _ in range(60):
            probe = subprocess.run(['docker', 'exec', 'rag-candidate37-postgres',
                                    'pg_isready', '-U', pg_env['POSTGRES_USER'],
                                    '-d', pg_env['POSTGRES_DB']], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
            if probe.returncode == 0:
                break
            time.sleep(2)
        else:
            raise RuntimeError('Candidate37 PostgreSQL did not become ready')
        report['steps'].append('independent_postgres_started')
        save()

        source_app_env = container_env(SOURCE_API)
        source_db_url = urlsplit(source_app_env['DATABASE_URL'])
        db_name = source_db_url.path.strip('/') or pg_env['POSTGRES_DB']
        if db_name != pg_env['POSTGRES_DB']:
            raise RuntimeError('Source application and PostgreSQL database names do not match')
        dump_path = ROOT / 'postgres-candidate-snapshot.dump'
        dump_path.touch(mode=0o600)
        dump_path.chmod(0o600)
        with dump_path.open('wb') as dump:
            subprocess.run(['docker', 'exec', SOURCE_DB, 'pg_dump', '-U', pg_env['POSTGRES_USER'],
                            '-d', db_name, '-Fc', '--no-owner', '--no-acl'], check=True,
                           stdout=dump, stderr=subprocess.PIPE, timeout=900)
        with dump_path.open('rb') as dump:
            listed = subprocess.run(['docker', 'exec', '-i', 'rag-candidate37-postgres',
                                     'pg_restore', '--list'], stdin=dump, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=60)
            if listed.returncode or not listed.stdout.strip():
                raise RuntimeError('Database dump archive validation failed')
        with dump_path.open('rb') as dump:
            restore = subprocess.Popen(['docker', 'exec', '-i', 'rag-candidate37-postgres',
                'pg_restore', '-U', pg_env['POSTGRES_USER'], '-d', pg_env['POSTGRES_DB'],
                '--no-owner', '--no-acl'], stdin=dump, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _stdout, restore_error = restore.communicate(timeout=900)
            if restore.returncode:
                raise RuntimeError('Candidate database restore failed: ' +
                                   restore_error.decode(errors='replace')[-1200:])
        schema_query = 'SELECT version_num FROM alembic_version ORDER BY version_num'
        source_schema = run(['docker', 'exec', SOURCE_DB, 'psql', '-U', pg_env['POSTGRES_USER'],
                             '-d', db_name, '-Atc', schema_query]).stdout.decode().splitlines()
        target_schema = run(['docker', 'exec', 'rag-candidate37-postgres', 'psql', '-U',
                             pg_env['POSTGRES_USER'], '-d', pg_env['POSTGRES_DB'], '-Atc',
                             schema_query]).stdout.decode().splitlines()
        if not source_schema or source_schema != target_schema:
            raise RuntimeError('Restored database schema head differs from the source')
        source_counts = table_counts(SOURCE_DB, pg_env['POSTGRES_USER'], db_name)
        target_counts = table_counts('rag-candidate37-postgres', pg_env['POSTGRES_USER'],
                                     pg_env['POSTGRES_DB'])
        if source_counts != target_counts:
            raise RuntimeError('Restored database table row counts differ from source')
        report['steps'].append('consistent_database_dump_restored')
        report['database_schema_head'] = target_schema
        report['database_table_counts'] = source_counts
        save()

        storage_source = Path('/home/rag-long-run/releases/candidate-20261116-26/storage')
        if not storage_source.is_dir():
            raise RuntimeError('Preserved test storage source is unavailable')
        storage = ROOT / 'storage'
        shutil.copytree(storage_source, storage, symlinks=False)
        if any(path.is_symlink() for path in storage.rglob('*')):
            raise RuntimeError('Storage copy contains a symlink')

        private = ROOT / 'private'
        source_env = dict(source_app_env)
        source_env.update(DATABASE_URL=database_url_for_candidate(source_app_env['DATABASE_URL']),
            CELERY_BROKER_URL='redis://redis:6379/0', CELERY_RESULT_BACKEND='redis://redis:6379/1',
            REDIS_URL='redis://redis:6379/0', MILVUS_URI='http://milvus:19530',
            EMBEDDING_BASE_URL='http://embedding:11434/v1', MILVUS_COLLECTION_PREFIX='rag_candidate25',
            STORAGE_DIR='/app/storage', APP_COMMIT=identity, BUILD_TIME=build_time,
            RAG_MODEL_BUDGET_PATH='/candidate-private/BUDGET.json',
            RAG_MODEL_BUDGET_STATE='/candidate-private/provider-budget.sqlite3',
            RAG_MODEL_BUDGET_REQUIRED='true',
            CITATION_SUPPORT_CHECK='off')
        for key in tuple(source_env):
            if key.endswith('_API_KEY') or key == 'RAG_RELAY_KEY':
                source_env.pop(key, None)
        env_path = private / 'environment.private.json'
        env_path.write_text(json.dumps(source_env, indent=2) + '\n', encoding='utf-8')
        env_path.chmod(0o600)
        report['steps'].append('storage_and_zero_budget_prepared')
        save()

        run(['docker', 'run', '-d', '--name', 'rag-candidate37-redis', '--network', NETWORK,
             '--network-alias', 'redis', 'redis:7-alpine'])
        mounts = ((storage, '/app/storage'), (private, '/candidate-private'))
        for component, command in (
            ('api', ['uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '8000']),
            ('worker', ['celery', '-A', 'app.workers.celery_app', 'worker', '--pool=solo',
                        '--concurrency=1', '--loglevel=INFO']),
        ):
            selected = {**source_env, 'SERVICE_COMPONENT': component}
            start_container('rag-candidate37-' + component, 'ybt-backend:' + TAG, command,
                            selected, mounts=mounts, aliases=('backend',) if component == 'api' else ())
        start_container('rag-candidate37-frontend', 'ybt-frontend:' + TAG, [], {})
        api_ip = inspect('rag-candidate37-api')['NetworkSettings']['Networks'][NETWORK]['IPAddress']
        web_ip = inspect('rag-candidate37-frontend')['NetworkSettings']['Networks'][NETWORK]['IPAddress']
        preview = ROOT / 'preview'
        (preview / 'logs').mkdir(parents=True, mode=0o700)
        nginx_conf = preview / 'nginx.conf'
        nginx_conf.write_text(f'''pid {preview}/logs/nginx.pid;
error_log {preview}/logs/error.log warn;
events {{ worker_connections 128; }}
http {{
  access_log {preview}/logs/access.log;
  server {{
    listen 127.0.0.1:{PREVIEW_PORT};
    location = /version {{ proxy_pass http://{api_ip}:8000/version; }}
    location = /health/ready {{ proxy_pass http://{api_ip}:8000/health/ready; }}
    location /api/ {{ proxy_pass http://{api_ip}:8000; proxy_read_timeout 200s; }}
    location / {{ proxy_pass http://{web_ip}:3000; proxy_set_header Host $host; }}
  }}
}}
''', encoding='ascii')
        run(['nginx', '-t', '-p', str(preview), '-c', str(nginx_conf)])
        run(['nginx', '-p', str(preview), '-c', str(nginx_conf)])
        version = wait_http(f'http://127.0.0.1:{PREVIEW_PORT}/version', expected=identity)
        wait_http(f'http://127.0.0.1:{PREVIEW_PORT}/health/ready')
        expected_image = 'ybt-backend:' + TAG
        if inspect('rag-candidate37-api')['Config']['Image'] != expected_image \
                or inspect('rag-candidate37-worker')['Config']['Image'] != expected_image \
                or inspect('rag-candidate37-frontend')['Config']['Image'] != 'ybt-frontend:' + TAG:
            raise RuntimeError('Candidate API, worker, and frontend image identities differ')
        if any(inspect('rag-candidate37-' + component)['State']['Status'] != 'running'
               for component in ('api', 'worker', 'frontend')):
            raise RuntimeError('Candidate API, worker, or frontend is not running')
        with urllib.request.urlopen(f'http://127.0.0.1:{PREVIEW_PORT}/login', timeout=10) as response:
            if response.status != 200:
                raise RuntimeError('Candidate frontend login page is not ready')
        budget_probe = "from app.services.llm.provider_budget import ProviderBudget; from app.services.llm.base import LLMProviderError; b=ProviderBudget.from_environment(); assert b is not None;\ntry: b.reserve(1, 'guard-probe')\nexcept LLMProviderError as e: assert e.error_type == 'budget_exhausted'\nelse: raise AssertionError('zero budget allowed a provider attempt')"
        run(['docker', 'exec', '-e', 'RAG_MODEL_BUDGET_PATH=/candidate-private/BUDGET.json',
             '-e', 'RAG_MODEL_BUDGET_STATE=/candidate-private/provider-budget.sqlite3',
             '-e', 'RAG_MODEL_BUDGET_REQUIRED=true',
             'rag-candidate37-api', 'python', '-c', budget_probe], timeout=30)
        report.update(steps=[*report['steps'], 'candidate_started_zero_budget',
            'api_worker_frontend_identity_verified', 'loopback_preview_ready',
            'zero_budget_provider_guard_verified'], version=version,
            preview_url=f'http://127.0.0.1:{PREVIEW_PORT}/login', network=NETWORK,
            container_names=['rag-candidate37-etcd', 'rag-candidate37-minio',
                'rag-candidate37-milvus', 'rag-candidate37-postgres', 'rag-candidate37-redis',
                'rag-candidate37-api', 'rag-candidate37-worker', 'rag-candidate37-frontend'],
            old_release_changed=False, public_route_changed=False, schema_migration_run=False,
            model_requests_made=0, rollback='stop only candidate37 nginx and containers; preserve all artifacts')
        save()
        return report
    except Exception as exc:
        report.update(failed=True, failure_type=type(exc).__name__, partial_resources_preserved=True,
                      old_release_changed=False, public_route_changed=False)
        save()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Create the independent candidate37 resources')
    parser.add_argument('--rollback', action='store_true', help='Stop only candidate37 services, preserving artifacts')
    parser.add_argument('--sync-vector-only', action='store_true',
                        help='Synchronize current missing collections into the existing isolated vector copy')
    parser.add_argument('--continue-after-vector-sync', action='store_true',
                        help='Continue the preserved partial attempt after vector parity is verified')
    args = parser.parse_args()
    if args.rollback:
        preview = ROOT / 'preview'
        config = preview / 'nginx.conf'
        pid = preview / 'logs/nginx.pid'
        if config.is_file() and pid.is_file():
            subprocess.run(['nginx', '-s', 'stop', '-p', str(preview), '-c', str(config)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=15)
        for name in ('rag-candidate37-frontend', 'rag-candidate37-worker', 'rag-candidate37-api',
                     'rag-candidate37-milvus', 'rag-candidate37-minio', 'rag-candidate37-etcd',
                     'rag-candidate37-redis', 'rag-candidate37-postgres'):
            if subprocess.run(['docker', 'inspect', name], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0:
                subprocess.run(['docker', 'stop', '-t', '20', name], check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=40)
        print(json.dumps({'candidate37_stopped': True, 'artifacts_preserved': True,
                          'old_candidate_changed': False, 'public_route_changed': False}))
        return
    if args.sync_vector_only:
        print(json.dumps(sync_existing_candidate_vector_stack(), indent=2))
        return
    if args.continue_after_vector_sync:
        print(json.dumps(continue_candidate_after_vector_sync(), indent=2))
        return
    manifest = verify_package()
    plan = preflight(manifest)
    if not args.execute:
        print(json.dumps({'mode': 'read_only_preflight', **plan}, indent=2))
        return
    print(json.dumps(execute(manifest), indent=2))


if __name__ == '__main__':
    main()
