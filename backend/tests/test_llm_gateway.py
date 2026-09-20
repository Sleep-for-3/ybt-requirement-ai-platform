import json

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


@pytest.mark.asyncio
async def test_mock_lineage_explanation_uses_structured_payload_not_editable_prompt_wording():
    service = get_llm_service(provider="mock")
    payload = {
        "relation": {
            "source": {"business_name": "来源客户标识"},
            "target": {"business_name": "监管客户标识"},
        },
        "facts": [
            {"id": "source_entity"},
            {"id": "target_entity"},
            {"id": "edge_type"},
            {"id": "transformation"},
        ],
        "regulatory_evidence": [],
    }

    response = await service.chat_json(
        system_prompt="仅依据固定脚本事实和制度证据解释。",
        user_prompt=json.dumps(payload, ensure_ascii=False),
    )

    assert response["business_summary"]
    assert response["regulatory_status"] == "missing_basis"
    assert response["plain_language_steps"]
