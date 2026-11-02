# -*- coding: utf-8 -*-
"""候选收敛：编造物理引用/跨章节主张被剔除并记 gap，而不是整条阻断。"""
from app.services.requirement_generation_worker import _sanitize_candidate


def test_sanitize_drops_unknown_physical_reference_and_mismatched_claims():
    context = {
        "physical_sources": [],
        "mapping_sources": [{"kind": "mart", "table_id": 3722, "field_id": 134134}],
    }
    candidate = {
        "business_definition": "机构ID口径",
        "physical_references": [
            {"kind": "mart", "table_id": 3722, "field_id": 134134},
            {"kind": "mart", "table_id": 9999, "field_id": 1},
        ],
        "claims": [
            {"claim_id": "F040001-C1", "section": "business", "text": "机构ID来自机构表"},
            {"claim_id": "F040001-C2", "section": "lineage", "text": "跨章节主张"},
        ],
        "policy_comparisons": [{"rule_ids": ["F040001-C2"], "unit_id": "u1"}],
        "gaps": [],
    }
    result = _sanitize_candidate(context, candidate)
    assert result["physical_references"] == [{"kind": "mart", "table_id": 3722, "field_id": 134134}]
    assert [claim["claim_id"] for claim in result["claims"]] == ["F040001-C1"]
    assert result["policy_comparisons"] == []
    assert any("物理引用" in gap for gap in result["gaps"])
    assert any("章节" in gap for gap in result["gaps"])


def test_sanitize_keeps_valid_candidate_untouched():
    context = {"physical_sources": [], "mapping_sources": [{"kind": "source", "table_id": 1, "field_id": 2}]}
    candidate = {
        "processing_logic": "来源路径",
        "physical_references": [{"kind": "source", "table_id": 1, "field_id": 2}],
        "claims": [{"claim_id": "C1", "section": "lineage", "text": "来源"}],
        "gaps": [],
    }
    result = _sanitize_candidate(context, candidate)
    assert result["physical_references"] == candidate["physical_references"]
    assert result["claims"] == candidate["claims"]
    assert result["gaps"] == []
