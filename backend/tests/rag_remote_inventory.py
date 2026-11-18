"""Read-only inventory of the explicitly authorized external test endpoint."""
import argparse
import base64
import getpass
import hashlib
import json
from pathlib import Path
import re

import paramiko


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--username', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--trusted-inventory', required=True, type=Path)
    args = parser.parse_args()
    if (args.host, args.port, args.username) != ('103.236.92.193', 37716, 'root'):
        raise ValueError('Only the endpoint explicitly supplied for this test deployment is permitted')
    trusted = json.loads(args.trusted_inventory.read_text(encoding='utf-8'))
    if any(trusted.get(k) != getattr(args, k) for k in ('host', 'port', 'username')):
        raise ValueError('Trusted inventory endpoint mismatch')
    expected_key = trusted.get('first_seen_host_key')
    if not expected_key or not expected_key.startswith('SHA256:'):
        raise ValueError('Trusted inventory has no host key')
    root = args.output.resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError('Preserve previous inventory attempts')
    root.mkdir(parents=True, exist_ok=True)
    password = getpass.getpass('Test server password (hidden): ')
    transport = paramiko.Transport((args.host, args.port))
    report = {'host': args.host, 'port': args.port, 'username': args.username,
              'operation': 'read_only_inventory', 'remote_mutations': [], 'commands': []}
    try:
        transport.start_client(timeout=15)
        key = transport.get_remote_server_key()
        fingerprint = 'SHA256:'+base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')
        report.update(first_seen_host_key=fingerprint, host_key_type=key.get_name(),
                      banner=transport.remote_version)
        if fingerprint != expected_key:
            raise ValueError('Host key changed; authentication was not attempted')
        report['host_key_matches_previous_attempt'] = True
        transport.auth_password(args.username, password)
        password = ''
        if not transport.is_authenticated():
            raise RuntimeError('Authentication failed')

        def run(command):
            channel = transport.open_session(timeout=15)
            channel.settimeout(30)
            channel.exec_command(command)
            output = channel.makefile('rb').read(65537)
            error = channel.makefile_stderr('rb').read(4097)
            code = channel.recv_exit_status()
            channel.close()
            if len(output) > 65536:
                raise ValueError('Inventory output exceeded limit')
            result = {'command': command, 'exit_code': code,
                      'stdout': output.decode('utf-8', errors='replace'),
                      'stderr': error[:4096].decode('utf-8', errors='replace')}
            report['commands'].append(result)
            (root/'inventory.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            return result

        for command in (
            'uname -srm', 'hostname', 'cat /etc/os-release', 'df -h',
            'ss -lntp', "docker ps --format '{{.ID}} {{.Names}} {{.Image}} {{.Ports}}'",
            'docker volume ls', 'systemctl --no-pager --type=service --state=running',
            'ls -ld /opt /srv /data /app /root',
        ):
            run(command)
        ids = run('docker ps -q')['stdout'].split()
        for identity in ids:
            if not re.fullmatch('[0-9a-f]{12,64}', identity):
                raise ValueError('Invalid container identity')
            run("docker inspect --format '{{json .Mounts}}' "+identity)
        report['completed'] = True
        print(json.dumps({'completed': True, 'host_key_sha256': fingerprint,
                          'commands': len(report['commands']), 'remote_mutations': 0}), flush=True)
    except Exception as error:
        report.update(completed=False, error_type=type(error).__name__)
        print(json.dumps({'completed': False, 'error_type': type(error).__name__, 'remote_mutations': 0}), flush=True)
        raise SystemExit(1) from None
    finally:
        password = ''
        transport.close()
        (root/'inventory.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
