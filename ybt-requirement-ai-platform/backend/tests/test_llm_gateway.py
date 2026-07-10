import pytest

from app.services.llm.factory import get_llm_service


@pytest.mark.asyncio
async def test_mock_llm_gateway_returns_mapping_json():
    service = get_llm_service(provider="mock")

    response = await service.chat_json(
        system_prompt="你是银行监管报送需求分析助手。",
        user_prompt="生成客户证件类型口径",
    )

    assert response["business_to_mart_rule"]
    assert response["confidence_level"] in {"high", "medium", "low"}
    assert isinstance(response["questions_for_human"], list)
