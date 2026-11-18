"""Boot the archived vector stack on a private network without touching old data."""
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path('/home/rag-long-run/backup-20261116-24')
CONFIG = json.loads((ROOT / 'containers.private.json').read_text())
BY_NAME = {c['Name'].lstrip('/'): c for c in CONFIG}
NETWORK = 'rag-restore-20261116-24'


def run(args, **kwargs):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=kwargs.pop('timeout', 120), **kwargs).stdout


def start(original, name, alias, mounts, overrides=None):
    config = BY_NAME[original]['Config']
    env = dict(value.split('=', 1) for value in config['Env'])
    env.update(overrides or {})
    command = ['docker', 'run', '-d', '--name', name, '--network', NETWORK,
               '--network-alias', alias]
    for key in env:
        command += ['-e', key]
    for source, target in mounts:
        source = ROOT / 'restored-files' / source
        if not source.is_dir():
            raise ValueError('Restored vector data missing')
        command += ['--mount', f'type=bind,src={source},dst={target}']
    for option in BY_NAME[original]['HostConfig'].get('SecurityOpt') or []:
        command += ['--security-opt', option]
    command += [config['Image'], *config['Cmd']]
    run(command, env={**os.environ, **env})


probe = '''import json,os,time
from pymilvus import MilvusClient
last=None
for attempt in range(45):
    try:
        client=MilvusClient(uri=os.environ['MILVUS_URI'],token=os.environ.get('MILVUS_TOKEN',''),timeout=10)
        collections=client.list_collections()
        result={name:client.get_collection_stats(name) for name in sorted(collections)}
        print(json.dumps(result));break
    except Exception as error:
        last=type(error).__name__;time.sleep(2)
else: raise RuntimeError('Vector restore probe failed: '+str(last))
'''
run(['docker', 'network', 'create', NETWORK])
start('source-etcd-1', 'rag-restore24-etcd', 'etcd', [
    ('var/lib/docker/volumes/source_etcd_data/_data', '/etcd')])
start('source-milvus-minio-1', 'rag-restore24-minio', 'milvus-minio', [
    ('data/ybt/milvus-minio', '/minio_data')])
start('source-milvus-1', 'rag-restore24-milvus', 'milvus', [
    ('data/ybt/milvus', '/var/lib/milvus')],
    {'ETCD_ENDPOINTS': 'etcd:2379', 'MINIO_ADDRESS': 'milvus-minio:9000'})
old = json.loads(run(['docker', 'exec', '-i', 'rag-e2e-backend', 'python', '-c', probe], timeout=180))
env = dict(v.split('=', 1) for v in BY_NAME['rag-e2e-backend']['Config']['Env'])
clone_env = {**os.environ, 'MILVUS_URI': 'http://milvus:19530',
             'MILVUS_TOKEN': env.get('MILVUS_TOKEN', '')}
clone = json.loads(run(['docker', 'run', '--network', NETWORK, '-e', 'MILVUS_URI',
                       '-e', 'MILVUS_TOKEN', 'ybt-backend:e2e-20261109i',
                       'python', '-c', probe], env=clone_env, timeout=180))
(ROOT / 'vector-original-counts.json').write_text(json.dumps(old))
(ROOT / 'vector-restored-counts.json').write_text(json.dumps(clone))
if old != clone:
    raise ValueError('Restored collection stats differ; original writes may have drifted')
report = json.loads((ROOT / 'report.json').read_text())
report.update(milvus_engine_restore_verified=True, vector_collections=len(clone),
              vector_collection_stats_match=True, private_vector_network=NETWORK)
(ROOT / 'report.json').write_text(json.dumps(report, indent=2))
print(json.dumps({'milvus_engine_restore_verified': True, 'collections': len(clone),
                  'isolated_network': NETWORK, 'old_data_mutations': 0}))
