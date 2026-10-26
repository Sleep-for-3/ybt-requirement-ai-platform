"""authority 排序策略的回归测试（boost 与 strict 的差异）。

真实事故：``authority_rank`` 曾是排序键第一位，技术证据（rank=1）永远排在监管资料
（rank=6）之后，导致"字段来源系统/加工逻辑"这类靠技术证据回答的问题 Recall=0。
这里用最小数据锁死两种策略的差异，避免以后又被改回硬排序。
"""

from __future__ import annotations

from app.services.retrieval.hybrid_retriever import _order_items


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
