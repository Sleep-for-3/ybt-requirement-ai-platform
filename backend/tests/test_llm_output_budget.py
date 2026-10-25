"""推理型模型的输出预算必须可配置，且不能在校验层被悄悄夹到 8192。

真实证据（2026-10-24，真实网关 deepseek-v4.1-flash）：同一需求输入下，模型先输出
reasoning_content（约 26000 字符），8192 的输出上限被思维链吃光，`finish_reason=length`
且 `content` 为空，链路如实报 `LLMResponseError`。把上限放宽后同样的输入能产出结构化
正文（单次 output_tokens 12927）。所以这里的断言固定两件事：
1) 设置项允许大于 8192 的值，并且在越界时报明确的错误；
2) LLM 客户端不会把调用方给的预算再夹回 8192。
"""

from app.core.settings import Settings
from app.services.llm.openai_compatible import OpenAICompatibleLLMService


def _codes(settings: Settings) -> set[str]:
    return {issue["code"] for issue in settings.validate_configuration()}


def test_settings_accepts_budget_above_8192():
    settings = Settings(llm_max_output_tokens=16384, _env_file=None)
    assert "llm_max_output_tokens_invalid" not in _codes(settings)


def test_settings_rejects_budget_above_32768():
    settings = Settings(llm_max_output_tokens=32769, _env_file=None)
    assert "llm_max_output_tokens_invalid" in _codes(settings)


def test_settings_still_rejects_tiny_budget():
    settings = Settings(llm_max_output_tokens=255, _env_file=None)
    assert "llm_max_output_tokens_invalid" in _codes(settings)


def test_client_does_not_clamp_budget_back_to_8192():
    service = OpenAICompatibleLLMService(
        base_url="http://127.0.0.1:9/v1",
        api_key="test-key",
        model="deepseek-v4.1-flash",
        max_output_tokens=16384,
    )
    assert service.max_output_tokens == 16384


def test_client_still_bounds_absurd_budget():
    service = OpenAICompatibleLLMService(
        base_url="http://127.0.0.1:9/v1",
        api_key="test-key",
        model="deepseek-v4.1-flash",
        max_output_tokens=10**6,
    )
    assert service.max_output_tokens == 32768
