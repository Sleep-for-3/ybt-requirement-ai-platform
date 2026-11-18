import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx
from pydantic import BaseModel

from app.services.llm.base import LLMProviderError
from app.services.llm.provider_budget import ProviderBudget, reservation_tokens
from app.services.llm.openai_compatible import OpenAICompatibleLLMService


class ProviderBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.summary = Path(self.temp.name) / 'BUDGET.json'
        self.state = Path(self.temp.name) / 'attempts.sqlite3'
        self.env = {'RAG_MODEL_BUDGET_PATH': str(self.summary),
                    'RAG_MODEL_BUDGET_STATE': str(self.state)}
        self.configure()

    def configure(self, requests=10, tokens=1000000):
        self.summary.write_text(json.dumps(dict(scope='test', max_new_provider_requests=requests,
            max_new_total_tokens=tokens, provider_requests_used=0, provider_requests_reserved=0,
            total_tokens_used=0, total_tokens_reserved=0, unknown_usage_requests=0)), encoding='utf-8')

    def budget(self):
        return ProviderBudget(self.summary, self.state)

    def counters(self):
        return json.loads(self.summary.read_text(encoding='utf-8'))

    def test_input_reservation_includes_utf8_bytes_and_output(self):
        payload = {'messages': [{'role': 'user', 'content': '\u53ea\u5141\u8bb8\u586b01'}], 'max_tokens': 800}
        self.assertGreaterEqual(reservation_tokens(payload),
            len(json.dumps(payload, ensure_ascii=False).encode('utf-8')) + 800)

    def test_reservation_survives_restart_and_missing_usage_is_charged(self):
        budget = self.budget()
        first = budget.reserve(1000, 'model')
        self.assertEqual(self.counters()['total_tokens_reserved'], 1000)
        self.budget().finish(first, None)
        self.assertEqual(self.counters()['unknown_usage_requests'], 1)
        self.assertEqual(self.counters()['total_tokens_used'], 1000)
        self.assertEqual(self.counters()['provider_requests_used'], 1)
        with self.assertRaises(LLMProviderError):
            budget.finish(first, {'total_tokens': 5})

    def test_crashed_reservation_blocks_next_attempt_at_cap(self):
        self.configure(requests=1)
        self.budget().reserve(1000, 'model')
        with self.assertRaises(LLMProviderError) as caught:
            self.budget().reserve(1000, 'model')
        self.assertEqual(caught.exception.error_type, 'budget_exhausted')
        self.assertEqual(self.counters()['provider_requests_reserved'], 1)

    def test_token_cap_includes_pending_requests(self):
        self.configure(tokens=1500)
        self.budget().reserve(1000, 'model')
        with self.assertRaises(LLMProviderError):
            self.budget().reserve(501, 'model')

    def test_reported_usage_and_invalid_usage(self):
        budget = self.budget()
        for usage, expected in [({'total_tokens': 9}, 9), ({}, 100),
                ({'total_tokens': 0}, 100), ({'total_tokens': True}, 100),
                ({'total_tokens': -1}, 100), ({'total_tokens': float('nan')}, 100),
                ({'total_tokens': 1, 'prompt_tokens': 12, 'completion_tokens': 3}, 100)]:
            before = self.counters()['total_tokens_used']
            token = budget.reserve(100, 'model')
            budget.finish(token, usage)
            self.assertEqual(self.counters()['total_tokens_used'] - before, expected)

    def test_concurrent_threads_and_processes_cannot_overbook(self):
        self.configure(requests=3)
        def attempt(_):
            try:
                self.budget().reserve(100, 'model')
                return True
            except LLMProviderError:
                return False
        with ThreadPoolExecutor(max_workers=6) as pool:
            self.assertEqual(sum(pool.map(attempt, range(8))), 3)
        code = ('from app.services.llm.provider_budget import ProviderBudget; '
                'import sys; ProviderBudget(sys.argv[1],sys.argv[2]).reserve(100,"model")')
        completed = subprocess.run([sys.executable, '-c', code, str(self.summary), str(self.state)],
            capture_output=True, text=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(self.counters()['provider_requests_reserved'], 3)

    def test_lost_state_cannot_silently_reset_nonzero_summary(self):
        self.budget().reserve(100, 'model')
        with self.assertRaises(LLMProviderError):
            ProviderBudget(self.summary, Path(self.temp.name) / 'lost.sqlite3').reserve(100, 'model')

    def test_usage_over_reservation_stops_future_calls(self):
        budget = self.budget()
        token = budget.reserve(100, 'model')
        budget.finish(token, {'total_tokens': 200})
        self.assertEqual(self.counters()['total_tokens_used'], 200)
        with self.assertRaises(LLMProviderError):
            budget.reserve(100, 'model')

    def test_missing_state_environment_fails_before_http(self):
        async def exercise():
            async def handler(request):
                self.fail('must stop before dispatch')
            service = self.service(handler)
            with patch.dict(os.environ, {'RAG_MODEL_BUDGET_PATH': str(self.summary),
                                         'RAG_MODEL_BUDGET_STATE': ''}):
                with self.assertRaises(LLMProviderError):
                    await service.chat_json('json', 'test')
        asyncio.run(exercise())

    def test_required_budget_fails_closed_before_http_when_paths_are_missing(self):
        async def exercise():
            async def handler(request):
                self.fail('must stop before dispatch')
            service = self.service(handler)
            with patch.dict(os.environ, {'RAG_MODEL_BUDGET_PATH': '',
                                         'RAG_MODEL_BUDGET_STATE': '',
                                         'RAG_MODEL_BUDGET_REQUIRED': 'true'}):
                with self.assertRaises(LLMProviderError) as caught:
                    await service.chat_json('json', 'test')
            self.assertEqual(caught.exception.error_type, 'budget_accounting_error')
        asyncio.run(exercise())

    def test_budget_remains_opt_in_for_unmanaged_regular_provider_runtime(self):
        with patch.dict(os.environ, {'RAG_MODEL_BUDGET_PATH': '',
                                     'RAG_MODEL_BUDGET_STATE': '',
                                     'RAG_MODEL_BUDGET_REQUIRED': ''}):
            self.assertIsNone(ProviderBudget.from_environment())

    def service(self, handler, **kwargs):
        return OpenAICompatibleLLMService('https://example.test/v1', 'test-key', 'model',
            transport=httpx.MockTransport(handler), **kwargs)

    def test_retries_and_json_repairs_each_consume_provider_request(self):
        class Answer(BaseModel):
            ok: bool
        async def exercise():
            calls = 0
            async def handler(request):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return httpx.Response(503)
                content = '{"wrong":1}' if calls == 2 else '{"ok":true}'
                return httpx.Response(200, json={'choices': [{'message': {'content': content}}],
                    'usage': {'total_tokens': 15}})
            service = self.service(handler, retry_count=1)
            with patch.dict(os.environ, self.env):
                result = await service.chat_structured('json', 'test', Answer)
            self.assertTrue(result.ok)
            self.assertEqual(calls, 3)
            self.assertEqual(self.counters()['provider_requests_used'], 3)
            self.assertEqual(self.counters()['unknown_usage_requests'], 1)
        asyncio.run(exercise())

    def test_network_error_conservatively_charged_and_cap_stops_retry(self):
        self.configure(requests=1)
        async def exercise():
            calls = 0
            async def handler(request):
                nonlocal calls
                calls += 1
                raise httpx.ConnectError('offline', request=request)
            with patch.dict(os.environ, self.env):
                with self.assertRaises(LLMProviderError) as caught:
                    await self.service(handler, retry_count=2).chat_json('json', 'test')
            self.assertEqual(caught.exception.error_type, 'budget_exhausted')
            self.assertEqual(calls, 1)
            self.assertEqual(self.counters()['unknown_usage_requests'], 1)
        asyncio.run(exercise())


if __name__ == '__main__':
    unittest.main()
