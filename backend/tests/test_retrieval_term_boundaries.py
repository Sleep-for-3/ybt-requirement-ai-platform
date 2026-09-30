from types import SimpleNamespace

import pytest

from app.services.retrieval.keyword_index import tokenize, weighted_tokens
from app.services.retrieval.hybrid_retriever import _keyword_score


@pytest.mark.parametrize("query,forbidden", [
    ("forecast", {"east", "一表通"}),
    ("imbalance", {"balance", "余额"}),
    ("subcontractor", {"contract", "合同"}),
    ("110400", {"1104", "一表通"}),
])
def test_embedded_english_substrings_do_not_expand_regulatory_concepts(query, forbidden):
    assert not forbidden.intersection(tokenize(query, expand_synonyms=True))
    assert not forbidden.intersection(weighted_tokens(None, query))


@pytest.mark.parametrize("query,expected", [
    ("BALANCE_AMT", {"balance", "余额"}),
    ("T.DUE_BILL", {"due_bill", "借据"}),
    ("执行利率", {"interest_rate", "执行利率"}),
    ("EAST", {"east", "一表通"}),
])
def test_explicit_concepts_and_field_identifiers_keep_cross_language_recall(query, expected):
    assert expected.issubset(tokenize(query, expand_synonyms=True))


def test_expanded_token_order_is_stable_when_synonym_set_iteration_changes(monkeypatch):
    from app.services.retrieval import keyword_index
    monkeypatch.setattr(keyword_index, "get_banking_synonyms", lambda _: ["zebra", "alpha"])
    first = tokenize("balance", expand_synonyms=True)
    monkeypatch.setattr(keyword_index, "get_banking_synonyms", lambda _: ["alpha", "zebra"])
    assert tokenize("balance", expand_synonyms=True) == first


def test_ranking_does_not_count_substring_as_exact_english_concept():
    false_match = SimpleNamespace(title="forecast imbalance", normalized_content="subcontractor 110400")
    assert _keyword_score(false_match, ["east", "balance", "contract", "1104"], None, None) == 0
    actual_match = SimpleNamespace(title="ACCOUNT_BALANCE_AMT", normalized_content="余额")
    assert _keyword_score(actual_match, ["balance", "余额"], None, None) > 0
