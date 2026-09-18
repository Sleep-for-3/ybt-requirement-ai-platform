from types import SimpleNamespace

import pytest

from app.models import ScenarioBusinessMapping, ScenarioTechnicalLineage
from app.services.mapping.scenario_draft_generator import _apply_business_output, _apply_technical_output


def suggestion(**fields):
    return SimpleNamespace(output_fields={"final_content_draft": "新的待采用建议", **fields},
                           merged_questions=SimpleNamespace(text="人工问题\n[AI] 模型提出的问题"),
                           confidence_level="low")


def test_business_regeneration_preserves_human_facts_and_questions():
    row = ScenarioBusinessMapping(final_content="人工业务口径", business_definition="人工定义",
                                  open_questions="人工问题", confidence_level="high", remarks="审核依据")
    _apply_business_output(row, suggestion(business_definition="模型定义", remarks="模型备注"), scenario_name=None)
    assert row.final_content == "人工业务口径"
    assert row.business_definition == "人工定义"
    assert row.open_questions == "人工问题\n[AI] 模型提出的问题"
    assert row.confidence_level == "low"
    assert row.remarks == "审核依据"
    assert row.ai_generated_content == "新的待采用建议"


def test_technical_regeneration_preserves_human_sources_and_rules():
    row = ScenarioTechnicalLineage(final_content="人工技术口径", source_table_english_name="CUSTOMER",
        source_field_english_name="CUSTOMER_ID", processing_logic="c.status='ACTIVE'",
        open_questions="人工问题", confidence_level="high", remarks="人工依据")
    _apply_technical_output(row, suggestion(source_table_english_name="OTHER",
        source_field_english_name="OTHER_ID", processing_logic="1=1", remarks="模型备注"), scenario_name=None)
    assert row.final_content == "人工技术口径"
    assert row.source_table_english_name == "CUSTOMER"
    assert row.source_field_english_name == "CUSTOMER_ID"
    assert row.processing_logic == "c.status='ACTIVE'"
    assert row.open_questions == "人工问题\n[AI] 模型提出的问题"
    assert row.confidence_level == "low"
    assert row.remarks == "人工依据"
    assert row.ai_generated_content == "新的待采用建议"


@pytest.mark.parametrize("final_content", [None, "", "   "])
def test_unedited_draft_can_still_receive_structured_generation(final_content):
    row = ScenarioBusinessMapping(final_content=final_content)
    _apply_business_output(row, suggestion(business_definition="生成定义"), scenario_name=None)
    assert row.business_definition == "生成定义"
    assert "[AI] 模型提出的问题" in row.open_questions
