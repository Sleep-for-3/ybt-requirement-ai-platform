"""Fixed-upstream, centrally budgeted relay and pinned SSH acceptance tunnels."""
import argparse
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import socketserver
import sys
import threading

import httpx
import paramiko


class Relay:
    def __init__(self, budget, model, upstream, key, token, transport=None):
        self.budget, self.model, self.upstream = budget, model, upstream.rstrip('/')
        self.key, self.token, self.transport = key, token, transport

    def dispatch(self, path, authorization, raw):
        from app.services.llm.base import LLMProviderError
        from app.services.llm.provider_budget import reservation_tokens
        if not hmac.compare_digest(authorization, 'Bearer ' + self.token):
            return 401, b'{"error":{"message":"Relay authentication required"}}'
        if path != '/v1/chat/completions':
            return 404, b'{"error":{"message":"Route unavailable"}}'
        try:
            payload = json.loads(raw)
            if (not isinstance(payload, dict) or payload.get('model') != self.model
                    or payload.get('stream') or type(payload.get('max_tokens')) is not int
                    or not 1 <= payload['max_tokens'] <= 32768):
                raise ValueError('Invalid relay payload')
            reserved = reservation_tokens(payload)
        except (ValueError, TypeError, LLMProviderError):
            return 400, b'{"error":{"message":"Invalid bounded text request"}}'
        try:
            identity = self.budget.reserve(reserved, self.model)
        except LLMProviderError:
            return 429, b'{"error":{"message":"Shared budget unavailable or exhausted"}}'
        usage = None
        try:
            with httpx.Client(timeout=180, transport=self.transport, follow_redirects=False) as client:
                response = client.post(self.upstream + '/chat/completions', json=payload,
                    headers={'Authorization': 'Bearer ' + self.key})
            if response.is_success:
                body = response.json()
                usage = body.get('usage') if isinstance(body, dict) else None
                return response.status_code, response.content
            return response.status_code, b'{"error":{"message":"Upstream request failed"}}'
        except Exception:
            return 502, b'{"error":{"message":"Upstream transport unavailable"}}'
        finally:
            self.budget.finish(identity, usage)


def remote_credential_path(release_dir):
    release_dir = str(release_dir).rstrip('/')
    expected = '/home/rag-long-run/releases/candidate-20261116-37-attempt2'
    if release_dir != expected:
        raise ValueError('Relay credentials may only be installed for candidate37')
    return release_dir + '/private/relay.private.json'


def pipe(left, right):
    def copy(source, target):
        try:
            while True:
                data = source.recv(65536)
                if not data:
                    break
                target.sendall(data)
        except (OSError, EOFError):
            pass
        finally:
            try:
                target.shutdown(socket.SHUT_WR)
            except (OSError, EOFError):
                pass
    reverse = threading.Thread(target=copy, args=(right, left), daemon=True)
    reverse.start()
    copy(left, right)
    reverse.join(timeout=190)
    left.close()
    right.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--trusted-inventory', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--ssh-key', required=True, type=Path)
    parser.add_argument('--remote-release-dir',
        default='/home/rag-long-run/releases/candidate-20261116-37-attempt2')
    args = parser.parse_args()
    if not args.ssh_key.is_file():
        raise FileNotFoundError('SSH identity file is unavailable')
    target = remote_credential_path(args.remote_release_dir)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    from rag_review_replay import setup
    setup(args.runtime.resolve())
    from app.services.llm.provider_budget import ProviderBudget
    budget = ProviderBudget.from_environment()
    if budget is None:
        raise ValueError('Shared cumulative accounting required')
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    token = secrets.token_urlsafe(48)
    private = {'token': token, 'model': os.environ['LLM_MODEL'], 'remote_port': 18090}
    secret_path = root / 'relay.private.json'
    secret_path.write_text(json.dumps(private), encoding='utf-8')
    secret_path.chmod(0o600)
    relay = Relay(budget, private['model'], os.environ['LLM_BASE_URL'],
                  os.environ[os.environ['LLM_API_KEY_ENV_NAME']], token)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            body = b'{"status":"ready","budget":"central-local-ledger"}'
            self.send_response(200 if self.path == '/health' else 404)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 2_000_000:
                    raise ValueError('Invalid body size')
                status, body = relay.dispatch(self.path, self.headers.get('Authorization', ''),
                                              self.rfile.read(length))
            except Exception:
                status, body = 503, b'{"error":{"message":"Relay unavailable"}}'
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 18131), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    trusted = json.loads(args.trusted_inventory.read_text(encoding='utf-8'))
    assert tuple(trusted[k] for k in ('host', 'port', 'username')) == ('103.236.92.193', 37716, 'root')
    transport = paramiko.Transport((trusted['host'], trusted['port']))
    forward = None
    try:
        transport.start_client(timeout=15)
        fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(
            transport.get_remote_server_key().asbytes()).digest()).decode().rstrip('=')
        if fingerprint != trusted['first_seen_host_key']:
            raise ValueError('Server identity changed')
        transport.auth_publickey(trusted['username'], paramiko.PKey.from_path(args.ssh_key))
        transport.set_keepalive(20)
        def inbound(channel, _origin, _destination):
            def handle():
                local = socket.create_connection(('127.0.0.1', 18131), timeout=10)
                local.settimeout(None)
                pipe(channel, local)
            threading.Thread(target=handle, daemon=True).start()
        transport.request_port_forward('127.0.0.1', 18090, inbound)
        with paramiko.SFTPClient.from_transport(transport) as sftp:
            try:
                sftp.stat(target)
            except FileNotFoundError:
                sftp.put(str(secret_path), target)
                sftp.chmod(target, 0o600)
            else:
                raise ValueError('Preserve existing relay credentials')
        class Forward(socketserver.BaseRequestHandler):
            def handle(self):
                channel = transport.open_channel('direct-tcpip', ('127.0.0.1', 18089),
                                                 self.request.getpeername(), timeout=20)
                pipe(self.request, channel)
        class ForwardServer(socketserver.ThreadingTCPServer):
            daemon_threads = True
        forward = ForwardServer(('127.0.0.1', 18130), Forward)
        threading.Thread(target=forward.serve_forever, daemon=True).start()
        (root / 'state.json').write_text(json.dumps({'pid': os.getpid(),
            'preview_url': 'http://127.0.0.1:18130', 'relay_local_port': 18131,
            'remote_loopback_port': 18090, 'fingerprint': fingerprint,
            'shared_budget_state': str(budget.state), 'upstream_credentials_uploaded': False,
            'public_routing_switched': False}), encoding='utf-8')
        print(json.dumps({'tunnels_ready': True, 'provider_calls_at_start': 0,
                          'preview_url': 'http://127.0.0.1:18130'}), flush=True)
        input('Enter to close acceptance tunnels: ')
    finally:
        transport.close()
        if forward:
            forward.shutdown()
        server.shutdown()


if __name__ == '__main__':
    main()
