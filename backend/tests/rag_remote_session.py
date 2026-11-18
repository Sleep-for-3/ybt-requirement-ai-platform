"""Execute recorded maintenance plans on the one authorized test host."""
import argparse
import base64
import getpass
import hashlib
import json
from pathlib import Path
import time

import paramiko


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trusted-inventory', required=True, type=Path)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--interactive', action='store_true')
    args = parser.parse_args()
    trusted = json.loads(args.trusted_inventory.read_text(encoding='utf-8'))
    endpoint = ('103.236.92.193', 37716, 'root')
    if tuple(trusted.get(k) for k in ('host', 'port', 'username')) != endpoint:
        raise ValueError('Unexpected test endpoint')
    password = getpass.getpass('Test server password (hidden): ')
    transport = paramiko.Transport(endpoint[:2])
    try:
        transport.start_client(timeout=15)
        fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(
            transport.get_remote_server_key().asbytes()).digest()).decode().rstrip('=')
        if fingerprint != trusted['first_seen_host_key']:
            raise ValueError('Server identity changed; authentication refused')
        transport.auth_password(endpoint[2], password)
        password = ''
        transport.set_keepalive(20)
        plan_path = args.plan
        while True:
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            root = Path(plan['output_directory']).resolve()
            if root.exists() and any(root.iterdir()):
                raise ValueError('Preserve previous maintenance output')
            root.mkdir(parents=True, exist_ok=True)
            results = []
            for step in plan['steps']:
                record = {'id': step['id'], 'operation': step['operation'],
                          'started_at': time.time(), 'completed': False}
                results.append(record)
                (root / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
                if step['operation'] == 'upload':
                    local = Path(step['local_path']).resolve()
                    record['sha256'] = hashlib.sha256(local.read_bytes()).hexdigest()
                    with paramiko.SFTPClient.from_transport(transport) as sftp:
                        try:
                            sftp.stat(step['remote_path'])
                        except FileNotFoundError:
                            sftp.put(str(local), step['remote_path'], confirm=True)
                        else:
                            raise ValueError('Refuse to overwrite remote artifact')
                    record['exit_code'] = 0
                elif step['operation'] in ('read_only', 'backup', 'restore', 'deploy', 'verify'):
                    channel = transport.open_session(timeout=15)
                    channel.settimeout(step.get('timeout_seconds', 60))
                    channel.exec_command(step['command'])
                    with (root / (step['id'] + '.stdout')).open('wb') as output, (
                            root / (step['id'] + '.stderr')).open('wb') as error:
                        deadline = time.monotonic() + step.get('timeout_seconds', 60)
                        while True:
                            if time.monotonic() > deadline:
                                channel.close()
                                raise TimeoutError('Remote step timed out; inspect state before retry')
                            if channel.recv_ready():
                                output.write(channel.recv(65536))
                            if channel.recv_stderr_ready():
                                error.write(channel.recv_stderr(65536))
                            if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                                break
                            time.sleep(.05)
                    record['exit_code'] = channel.recv_exit_status()
                    channel.close()
                else:
                    raise ValueError('Unknown maintenance operation')
                record['completed'] = True
                record['finished_at'] = time.time()
                (root / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
                print(json.dumps({'step': step['id'], 'exit_code': record['exit_code']}), flush=True)
                if record['exit_code'] != 0:
                    break
            if not args.interactive:
                break
            next_path = input('Next plan path or exit: ').strip()
            if next_path == 'exit':
                break
            plan_path = Path(next_path)
    finally:
        password = ''
        transport.close()


if __name__ == '__main__':
    main()
