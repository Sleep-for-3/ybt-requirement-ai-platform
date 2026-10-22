"""P1-B: row-limit / CTE attribution and the honest unattributed fallback.

The SQL semantic comparator used to cover 36 of 39 declared families: `top_limit` and
`cte` changes only surfaced as an unattributed AST fallback, and `order_by` still does.
This module pins the new behaviour:

* a row-limit (or limit+order-by) rewrite is attributed to `top_limit_changed` and is
  marked caliber-affecting;
* a CTE-internal projection or predicate rewrite is attributed to `cte_changed` even
  when the outer projection text is identical;
* a pure CTE rename and a formatting-only rewrite stay silent, and an unattributed
  fallback never claims a caliber impact (no invented conclusion);
* an unparseable side reports `parse_quality_changed`, never a fabricated row-limit or
  CTE attribution;
* `order_by` remains the single declared limitation and is documented as such.

Nothing here asserts a business truth: every interpretation remains human-gated.
"""

from __future__ import annotations

import pytest

from app.services.lineage.sql_semantic_diff import (
    SEMANTIC_FAMILIES,
    SEMANTIC_LABELS,
    STRUCTURAL_ATTRIBUTION,
    UNATTRIBUTED_ATTRIBUTION,
    semantic_changes,
)


def _categories(diff: dict) -> set[str]:
    return {fact["category"] for fact in diff["facts"]}


def _attributions(diff: dict) -> set[str]:
    return {fact["attribution"] for fact in diff["facts"]}


def _items(diff: dict, category: str) -> list[dict]:
    return [item for item in diff["semantic_items"] if item["category"] == category]


# ---------------------------------------------------------------- row limits


def test_row_limit_change_is_structural_and_caliber_affecting():
    diff = semantic_changes(
        "insert into tgt select amt from t limit 10",
        "insert into tgt select amt from t limit 100",
    )

    assert diff["semantic_changed"] is True
    assert "top_limit_changed" in _categories(diff)
    assert _attributions(diff) == {STRUCTURAL_ATTRIBUTION}
    fact = next(fact for fact in diff["facts"] if fact["category"] == "top_limit_changed")
    assert fact["entity_type"] == "top_limit"
    assert "10" in fact["before"] and "100" in fact["after"]

    item = _items(diff, "top_limit_changed")[0]
    assert item["affects_caliber"] is True
    assert item["label"] == SEMANTIC_LABELS["top_limit_changed"]
    assert diff["caliber_affecting_count"] >= 1
    assert all(entry["requires_human_confirmation"] for entry in diff["interpretations"])


def test_row_limit_removal_is_detected():
    diff = semantic_changes(
        "insert into tgt select amt from t limit 10",
        "insert into tgt select amt from t",
    )

    assert diff["semantic_changed"] is True
    assert "top_limit_changed" in _categories(diff)


def test_order_by_alone_stays_unattributed_and_claims_no_caliber():
    diff = semantic_changes(
        "insert into tgt select amt from t order by dt",
        "insert into tgt select amt from t order by amt",
    )

    assert diff["semantic_changed"] is True
    # A statement-level ORDER BY only decides presentation: no structural attribution, so
    # no family may claim it and no caliber conclusion may be derived from it.
    assert _attributions(diff) == {UNATTRIBUTED_ATTRIBUTION}
    assert "top_limit_changed" not in _categories(diff)
    assert diff["caliber_affecting_count"] == 0
    item = diff["semantic_items"][0]
    assert item["affects_caliber"] is False
    assert "未归因" in item["label"]
    assert "未能把该变化归因" in item["statement"]


def test_order_by_with_limit_is_one_row_range_change():
    diff = semantic_changes(
        "insert into tgt select amt from t order by dt limit 10",
        "insert into tgt select amt from t order by amt limit 10",
    )

    # The ordering decides which rows survive a limit, so the pair is one row-range fact
    # rather than a separate (and misleading) "transformation" conclusion.
    assert _categories(diff) == {"top_limit_changed"}
    assert _attributions(diff) == {STRUCTURAL_ATTRIBUTION}
    fact = next(fact for fact in diff["facts"] if fact["category"] == "top_limit_changed")
    assert fact["before"] != fact["after"]
    item = _items(diff, "top_limit_changed")[0]
    assert item["label"] == SEMANTIC_LABELS["top_limit_changed"]


# ---------------------------------------------------------------- CTE


def test_cte_predicate_rewrite_keeps_filter_and_cte_attribution():
    diff = semantic_changes(
        "insert into tgt with c as (select amt from t1 where dt > '2024-01-01') select amt from c",
        "insert into tgt with c as (select amt from t1 where dt > '2025-01-01') select amt from c",
    )

    categories = _categories(diff)
    assert "cte_changed" in categories
    assert "filter_changed" in categories
    cte_fact = next(fact for fact in diff["facts"] if fact["category"] == "cte_changed")
    assert cte_fact["entity_type"] == "cte"
    assert "2024-01-01" in cte_fact["before"]
    assert "2025-01-01" in cte_fact["after"]
    assert all(item["affects_caliber"] for item in _items(diff, "filter_changed"))
    assert all(item["affects_caliber"] for item in _items(diff, "cte_changed"))


def test_cte_projection_rewrite_is_attributed_when_outer_projection_is_identical():
    old_sql = "insert into tgt with c as (select amt from t1) select amt from c"
    new_sql = "insert into tgt with c as (select amt * 2 as amt from t1) select amt from c"

    diff = semantic_changes(old_sql, new_sql)

    # The outer projection text is byte-identical, so the edge comparator finds nothing;
    # the CTE signature is the only structural handle on this real processing change.
    assert _categories(diff) == {"cte_changed"}
    assert _attributions(diff) == {STRUCTURAL_ATTRIBUTION}
    fact = next(fact for fact in diff["facts"] if fact["category"] == "cte_changed")
    assert fact["before"] != fact["after"]
    assert "amt * 2" in fact["after"].lower()


def test_cte_rename_is_equivalent_and_claims_no_caliber():
    diff = semantic_changes(
        "insert into tgt with c as (select amt from t1) select amt from c",
        "insert into tgt with x as (select amt from t1) select amt from x",
    )

    # Renaming a CTE consistently is an equivalent rewrite: no structural dimension may
    # claim it, and the unattributed fallback must not claim a caliber impact.
    assert STRUCTURAL_ATTRIBUTION not in _attributions(diff)
    assert diff["caliber_affecting_count"] == 0
    assert "cte_changed" not in _categories(diff)
    assert all(item["affects_caliber"] is False for item in diff["semantic_items"])


def test_cte_formatting_only_is_non_semantic():
    diff = semantic_changes(
        "insert into tgt with c as (select amt from t1) select amt from c",
        "INSERT INTO tgt\nWITH c AS (SELECT   amt FROM t1)\nSELECT amt FROM c",
    )

    assert diff["semantic_changed"] is False
    assert diff["facts"] == []
    assert diff["categories"] == ["non_semantic"]
    assert diff["caliber_affecting_count"] == 0


# ---------------------------------------------------------------- degradation


@pytest.mark.parametrize(
    "old_sql, new_sql",
    [
        ("insert into tgt select amt from (", "insert into tgt select amt from t"),
        ("insert into tgt select amt from t", "insert into tgt select amt from ("),
    ],
)
def test_unparseable_side_does_not_invent_rowlimit_or_cte_attribution(old_sql, new_sql):
    diff = semantic_changes(old_sql, new_sql)

    assert diff["semantic_changed"] is True
    assert "parse_quality_changed" in _categories(diff)
    assert "top_limit_changed" not in _categories(diff)
    assert "cte_changed" not in _categories(diff)


def test_multi_statement_script_attributes_the_changed_limit():
    diff = semantic_changes(
        "insert into t1 select a from s; insert into tgt select amt from t limit 10",
        "insert into t1 select a from s; insert into tgt select amt from t limit 100",
    )

    # Unchanged statements must not add noise: only the limit dimension is reported.
    assert _categories(diff) == {"top_limit_changed"}
    assert _attributions(diff) == {STRUCTURAL_ATTRIBUTION}


# ---------------------------------------------------------------- declared boundary


def test_only_order_by_remains_a_declared_limitation():
    remaining = {
        code for code, spec in SEMANTIC_FAMILIES.items() if spec.detection != "comparator"
    }
    assert remaining == {"order_by"}
    reason = SEMANTIC_FAMILIES["order_by"].note
    assert "top_limit_changed" in reason, "the limitation must point at the real consequence"

    diff = semantic_changes("select 1", "select 1")
    assert diff["family_coverage"] == {"detected": 38, "total": 39}
    assert {entry["code"] for entry in diff["unsupported_families"]} == {"order_by"}
