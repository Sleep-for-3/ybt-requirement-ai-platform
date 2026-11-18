"""Owned real-component API with explicit loopback-only provider fault injection.

This is a transport fault harness, never a successful-real-model acceptance by
itself. It does not update shared model profiles, queues, documents or indexes.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sys
import threading


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--port', type=int, default=18112)
    parser.add_argument('--fault-port', type=int, default=18113)
    args = parser.parse_args()
    for port in (args.port, args.fault_port):
        if not 1024 <= port <= 65535:
            raise ValueError('Expected unprivileged local ports')
        with socket.socket() as connection:
            if connection.connect_ex(('127.0.0.1', port)) == 0:
                raise ValueError('Preserve occupied port')
    if args.port == args.fault_port:
        raise ValueError('Distinct ports required')
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError('Preserve existing fault run; choose a new directory')
    backend = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(backend), str(backend/'scripts')]
    from rag_review_replay import setup
    from rag_review_environment import source_identity
    from rag_source_review import write_json
    state = setup(args.workspace.resolve())
    identity = source_identity()
    mode_path = root/'fault-mode.json'
    write_json(mode_path, {'mode': 'generation_network'})
    os.environ['RAG_LOCAL_FAULT_KEY'] = 'loopback-test-key'
    os.environ['APP_COMMIT'] = identity['git_head']+'+fault.'+identity['code_hash'][:12]
    os.environ['BUILD_TIME'] = datetime.now(timezone.utc).isoformat()
    os.environ['CITATION_SUPPORT_CHECK'] = 'judge'
    from app.services.llm import prompt_runtime
    original = prompt_runtime.get_runtime_llm_service
    lock = threading.Lock()

    def event(kind):
        with lock, (root/'transport-events.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps({'event': kind, 'at': datetime.now(timezone.utc).isoformat()})+'\n')

    class FaultHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', '0')))
            mode = json.loads(mode_path.read_text(encoding='utf-8'))['mode']
            if mode == 'generation_network':
                event('injected_connection_closed_without_response')
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            event('injected_http_503')
            body = b'{"error":{"message":"test-only provider unavailable"}}'
            self.send_response(503)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    transport = ThreadingHTTPServer(('127.0.0.1', args.fault_port), FaultHandler)
    threading.Thread(target=transport.serve_forever, daemon=True).start()

    def fault_service(runtime, **kwargs):
        mode = json.loads(mode_path.read_text(encoding='utf-8'))['mode']
        if mode not in {'generation_network', 'judge_http', 'healthy'}:
            raise ValueError('Unknown test mode')
        inject = mode == 'generation_network' or (
            mode == 'judge_http' and runtime.prompt_key == 'citation_support_check')
        runtime = replace(runtime, config={**runtime.config, 'retry_count': 0, 'fallback_models': []})
        if inject:
            event('redirected_'+runtime.prompt_key)
            runtime = replace(runtime, provider_type='local_vllm', local_only=True,
                              base_url=f'http://127.0.0.1:{args.fault_port}/v1',
                              api_key_env_name='RAG_LOCAL_FAULT_KEY')
        return original(runtime, **kwargs)

    prompt_runtime.get_runtime_llm_service = fault_service
    from app.main import app
    from app.core.settings import get_settings
    from starlette.responses import JSONResponse
    get_settings().citation_support_check = 'judge'

    @app.middleware('http')
    async def prevent_fixture_mutation(request, call_next):
        if request.method not in {'GET', 'HEAD', 'OPTIONS'} and not (
            request.url.path == '/api/auth/login' or request.url.path.endswith('/knowledge/ask')):
            return JSONResponse({'detail': 'Fault harness permits login and ask only'}, status_code=403)
        return await call_next(request)

    write_json(root/'source-identity.json', identity)
    write_json(root/'state.json', {**state, 'backend_url': f'http://127.0.0.1:{args.port}',
        'fault_port': args.fault_port, 'fault_mode_path': str(mode_path),
        'pid': os.getpid(), 'injected_transport_provider': 'local_vllm',
        'evidence_tier': 'real_components_browser_with_explicit_transport_fault_injection',
        'worker_started': False, 'shared_model_profiles_changed': False})
    print(json.dumps({'fault_api_port': args.port, 'fault_transport_port': args.fault_port,
                      'source_hash': identity['code_hash'], 'provider_calls_at_start': 0}), flush=True)
    import uvicorn
    try:
        uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning')
    finally:
        transport.shutdown()


if __name__ == '__main__':
    main()
