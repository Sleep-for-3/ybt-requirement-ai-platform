"""authority 排序策略的回归测试（boost 与 strict 的差异）。

真实事故：``authority_rank`` 曾是排序键第一位，技术证据（rank=1）永远排在监管资料
（rank=6）之后，导致"字段来源系统/加工逻辑"这类靠技术证据回答的问题 Recall=0。
这里用最小数据锁死两种策略的差异，避免以后又被改回硬排序。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.retrieval.hybrid_retriever import (
    _content_identifier_matches,
    _order_items,
    _query_sql_identifiers,
)
from app.services.code_extraction import extract_sql_identifiers
from app.core.settings import Settings


def _item(unit_id: int, authority_rank: int) -> dict:
    return {"knowledge_unit_id": unit_id, "authority_rank": authority_rank}


def test_boost_ranks_by_score_before_authority() -> None:
    items = [_item(1, 6), _item(2, 1), _item(3, 6)]
    ranking = {1: 0.60, 2: 0.95, 3: 0.70}

    ordered = _order_items(items, ranking, "boost")

    assert [item["knowledge_unit_id"] for item in ordered] == [2, 3, 1]


def test_strict_keeps_authority_as_primary_key() -> None:
    items = [_item(1, 6), _item(2, 1), _item(3, 6)]
    ranking = {1: 0.60, 2: 0.95, 3: 0.70}

    ordered = _order_items(items, ranking, "strict")

    assert [item["knowledge_unit_id"] for item in ordered] == [3, 1, 2]


def test_boost_uses_authority_as_tiebreaker() -> None:
    items = [_item(1, 1), _item(2, 6), _item(3, 3)]
    ranking = {1: 0.80, 2: 0.80, 3: 0.80}

    ordered = _order_items(items, ranking, "boost")

    assert [item["knowledge_unit_id"] for item in ordered] == [2, 3, 1]


def test_unknown_mode_falls_back_to_boost() -> None:
    items = [_item(1, 6), _item(2, 1)]
    ranking = {1: 0.30, 2: 0.90}

    ordered = _order_items(items, ranking, "")

    assert [item["knowledge_unit_id"] for item in ordered] == [2, 1]


def test_explicit_field_codes_match_only_complete_identifiers() -> None:
    matches = _content_identifier_matches(
        "CASE WHEN F090029 = '06' AND H040037 = '01' THEN 1 END F0900290",
        {"F090029", "H040037"},
    )
    assert matches == {"F090029", "H040037"}


def test_explicit_sql_identifiers_are_extracted_with_complete_boundaries() -> None:
    query = "HYF_BK_TERMINAL_INFO中DEV_EXT和DEV_STATUS如何判断，DEV_STATUS2不参与"
    assert extract_sql_identifiers(query) == {
        "HYF_BK_TERMINAL_INFO", "DEV_EXT", "DEV_STATUS", "DEV_STATUS2"
    }


def test_sql_identifier_body_match_does_not_accept_prefix_or_substring() -> None:
    matches = _content_identifier_matches(
        "CASE WHEN DEV_STATUS2 = '0' THEN END; START_DT",
        {"DEV_STATUS", "START_DT"},
    )
    assert matches == {"START_DT"}


def test_sql_identifier_ranking_experiment_is_disabled_by_default() -> None:
    assert Settings(_env_file=None).retrieval_sql_identifier_boost_enabled is False


def test_sql_identifier_experiment_is_independent_of_query_expansion() -> None:
    query = "HYF_BK_TERMINAL_INFO 的 DEV_STATUS 如何判断"
    settings = SimpleNamespace(
        query_expansion_enabled=False,
        retrieval_sql_identifier_boost_enabled=True,
    )
    assert _query_sql_identifiers(query, settings) == {
        "HYF_BK_TERMINAL_INFO", "DEV_STATUS"
    }


def test_sql_identifier_experiment_remains_opt_in() -> None:
    settings = SimpleNamespace(
        query_expansion_enabled=True,
        retrieval_sql_identifier_boost_enabled=False,
    )
    assert _query_sql_identifiers("DEV_STATUS", settings) == set()
