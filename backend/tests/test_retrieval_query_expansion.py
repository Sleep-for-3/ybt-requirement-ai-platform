"""Tests for scenario-aware query expansion (round 76 G2)."""

from __future__ import annotations

from app.services.retrieval.query_expansion import (
    INTENT_RULES,
    INTENT_TYPES,
    SYNONYM_GROUPS,
    detect_intent,
    expand_query,
    matched_scenarios,
)


def test_expand_query_keeps_original_first_and_is_bounded():
    variants = expand_query("E010001 产品ID 的加工逻辑是什么", max_variants=3)
    assert variants[0] == "E010001 产品ID 的加工逻辑是什么"
    assert len(variants) <= 3
    assert len(variants) == len(set(variants))


def test_expand_query_adds_processing_synonyms():
    joined = " ".join(expand_query("E010005 的加工逻辑", max_variants=5))
    # 处理逻辑/脚本规则/处理逻辑类型 都应出现在某个变体里，供关键词索引命中。
    assert "处理逻辑" in joined
    assert "脚本规则" in joined


def test_expand_query_adds_field_terms_for_codes():
    joined = " ".join(expand_query("E010010 怎么算", max_variants=5))
    assert "数据项" in joined
    assert "E010010" in joined


def test_expand_query_without_trigger_returns_original_only():
    assert expand_query("T_5_1 表有哪些字段", max_variants=3) == ["T_5_1 表有哪些字段"]


def test_expand_query_handles_empty_query():
    assert expand_query("", max_variants=3) == [""]


def test_matched_scenarios_requires_exact_name_in_query():
    names = ["借记卡", "信用卡", "代销理财"]
    assert matched_scenarios("借记卡场景下 E010001 的业务口径", names) == {"借记卡"}
    assert matched_scenarios("信用卡和借记卡都要", names) == {"借记卡", "信用卡"}
    assert matched_scenarios("贷款场景", names) == set()


def test_synonym_groups_have_unique_canonical_terms():
    canonicals = [canonical for canonical, _ in SYNONYM_GROUPS]
    assert len(canonicals) == len(set(canonicals))
    for canonical, aliases in SYNONYM_GROUPS:
        assert canonical
        assert aliases


def test_detect_intent_prefers_processing_over_regulatory():
    assert detect_intent("E010005 科目类型 的加工逻辑是什么") == "processing"
    assert detect_intent("这个字段来自哪个系统、哪张表") == "lineage"
    assert detect_intent("借记卡场景下这个字段的业务口径") == "scenario"
    assert detect_intent("产品ID 的监管口径原文") == "regulatory"
    assert detect_intent("T_5_1 有哪些字段") is None


def test_intent_types_cover_every_rule():
    assert set(INTENT_TYPES) == {intent for intent, _ in INTENT_RULES}
    assert {kind for kind, _ in INTENT_TYPES.values()} <= {
        "field_explanation",
        "business_research",
        "technical_research",
    }
