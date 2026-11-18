import httpx
import pytest

from app.services.llm.base import LLMProviderError
from app.services.llm.openai_compatible import OpenAICompatibleLLMService


@pytest.mark.asyncio
@pytest.mark.parametrize('retries', [0, 2])
async def test_remote_disconnect_is_classified_and_retries_stay_bounded(retries):
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        raise httpx.RemoteProtocolError('Server disconnected without sending a response', request=request)

    async def no_sleep(_seconds):
        pass

    service = OpenAICompatibleLLMService(
        base_url='https://provider.example.com/v1', api_key='test-only', model='example-model',
        retry_count=retries, transport=httpx.MockTransport(handler), sleep_func=no_sleep)
    with pytest.raises(LLMProviderError) as error:
        await service.chat_json('Return JSON', 'question')
    assert error.value.error_type == 'network_error'
    assert 'RemoteProtocolError' in error.value.detail
    assert attempts == retries + 1
    assert service.last_call.retry_count == retries
    assert service.last_call.http_status is None


@pytest.mark.asyncio
async def test_local_protocol_bug_is_not_retried_as_remote_outage():
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        raise httpx.LocalProtocolError('Invalid request header', request=request)

    service = OpenAICompatibleLLMService(
        base_url='https://provider.example.com/v1', api_key='test-only', model='example-model',
        retry_count=2, transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.LocalProtocolError):
        await service.chat_json('Return JSON', 'question')
    assert attempts == 1
