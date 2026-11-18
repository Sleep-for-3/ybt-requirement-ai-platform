import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from rag_remote_budget_bridge import Relay, remote_credential_path
from app.services.llm.provider_budget import ProviderBudget


def fixture(tmp_path, cap=2, status=200):
    summary = tmp_path / 'budget.json'
    summary.write_text(json.dumps({'scope': 'relay-test', 'max_new_provider_requests': cap,
                                   'max_new_total_tokens': 100000}))
    budget = ProviderBudget(summary, tmp_path / 'state.sqlite3')
    sent = []
    def upstream(request):
        sent.append(request)
        return httpx.Response(status, json={'usage': {'total_tokens': 8,
            'prompt_tokens': 5, 'completion_tokens': 3}, 'choices': []})
    relay = Relay(budget, 'test-model', 'https://fixed.invalid/v1', 'upstream-secret',
                  'test-token', httpx.MockTransport(upstream))
    return relay, summary, sent


def body(**changes):
    return json.dumps({'model': 'test-model', 'messages': [{'role': 'user', 'content': 'test'}],
                       'max_tokens': 50, **changes}).encode()


def test_remote_credential_path_is_pinned_to_candidate37():
    assert remote_credential_path(
        '/home/rag-long-run/releases/candidate-20261116-37-attempt2'
    ) == '/home/rag-long-run/releases/candidate-20261116-37-attempt2/private/relay.private.json'
    with pytest.raises(ValueError, match='candidate37'):
        remote_credential_path('/home/rag-long-run/releases/candidate-20261116-37')


@pytest.mark.parametrize('path,auth,payload,expected', [
    ('/v1/chat/completions', '', body(), 401),
    ('/v1/embeddings', 'Bearer test-token', body(), 404),
    ('/v1/chat/completions', 'Bearer test-token', body(model='other'), 400),
    ('/v1/chat/completions', 'Bearer test-token', body(stream=True), 400),
    ('/v1/chat/completions', 'Bearer test-token', body(max_tokens=32769), 400),
    ('/v1/chat/completions', 'Bearer test-token', b'null', 400),
])
def test_invalid_never_dispatches(tmp_path, path, auth, payload, expected):
    relay, _, sent = fixture(tmp_path)
    assert relay.dispatch(path, auth, payload)[0] == expected
    assert not sent


def test_shared_budget_counts_concurrent_dispatch_and_blocks_exhaustion(tmp_path):
    relay, summary, sent = fixture(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as workers:
        statuses = list(workers.map(lambda _: relay.dispatch('/v1/chat/completions',
            'Bearer test-token', body())[0], range(4)))
    assert sorted(statuses) == [200, 200, 429, 429]
    totals = json.loads(summary.read_text())
    assert totals['provider_requests_used'] == 2
    assert totals['total_tokens_used'] == 16
    assert totals['provider_requests_reserved'] == 0
    assert len(sent) == 2
    assert all(str(r.url) == 'https://fixed.invalid/v1/chat/completions' for r in sent)
    assert all(r.headers['authorization'] == 'Bearer upstream-secret' for r in sent)


def test_upstream_failure_is_counted_without_retry_or_body_leak(tmp_path):
    relay, summary, sent = fixture(tmp_path, status=503)
    status, response = relay.dispatch('/v1/chat/completions', 'Bearer test-token', body())
    totals = json.loads(summary.read_text())
    assert status == 503 and b'usage' not in response
    assert len(sent) == 1
    assert totals['provider_requests_used'] == totals['unknown_usage_requests'] == 1
    assert totals['provider_requests_reserved'] == 0
