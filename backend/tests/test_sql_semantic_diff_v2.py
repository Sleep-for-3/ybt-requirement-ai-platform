"""Acceptance tests for the SQL semantic diff v2 fact / interpretation split.

Every family declared ``detection="comparator"`` is proven by one real, small SQL
pair whose changed construct *is* that family.  Every family declared
``unsupported`` is demonstrated to produce only the comparator's script-level
fallback (``attribution == "unattributed_ast_change"``), so the coverage gap is
explicit instead of hidden.

Small real pairs are written as ``insert into tgt ... select ...`` on purpose: the
comparator only builds lineage edges for statements with a write target, so a bare
``select`` cannot prove anything about a family.
"""
from __future__ import annotations

import json

import pytest

from app.services.lineage.sql_semantic_diff import (
    DETECTION_COMPARATOR,
    DETECTION_UNSUPPORTED,
    FACT_FIELDS,
    SEMANTIC_FAMILIES,
    SEMANTIC_LABELS,
    STRUCTURAL_ATTRIBUTION,
    UNATTRIBUTED_ATTRIBUTION,
    semantic_changes,
)

# family code -> (old SQL, new SQL, the comparator category that must be reported)
SUPPORTED_CASES: dict[str, tuple[str, str, str]] = {
    "window_function": (
        "insert into tgt select row_number() over (partition by acct order by dt) as rn from t",
        "insert into tgt select row_number() over (partition by acct order by amt) as rn from t",
        "transformation_changed",
    ),
    "partition_by": (
        "insert into tgt select row_number() over (partition by acct order by dt) as rn from t",
        "insert into tgt select row_number() over (partition by branch order by dt) as rn from t",
        "transformation_changed",
    ),
    "row_number_order": (
        "insert into tgt select row_number() over (order by dt) as rn from t",
        "insert into tgt select rank() over (order by dt) as rn from t",
        "transformation_changed",
    ),
    "date_boundary": (
        "insert into tgt select amt from t where dt >= '2024-01-01'",
        "insert into tgt select amt from t where dt >= '2024-07-01'",
        "filter_changed",
    ),
    "gt_vs_ge": (
        "insert into tgt select amt from t where amt > 100",
        "insert into tgt select amt from t where amt >= 100",
        "filter_changed",
    ),
    "lt_vs_le": (
        "insert into tgt select amt from t where amt < 100",
        "insert into tgt select amt from t where amt <= 100",
        "filter_changed",
    ),
    "between_boundary": (
        "insert into tgt select amt from t where amt between 100 and 200",
        "insert into tgt select amt from t where amt between 100 and 300",
        "filter_changed",
    ),
    "null_predicate": (
        "insert into tgt select amt from t where amt is null",
        "insert into tgt select amt from t where amt is not null",
        "filter_changed",
    ),
    "nvl": (
        "insert into tgt select nvl(amt, 0) as x from t",
        "insert into tgt select nvl(amt, 1) as x from t",
        "transformation_changed",
    ),
    "coalesce": (
        "insert into tgt select coalesce(amt, fee, 0) as x from t",
        "insert into tgt select coalesce(amt, 0) as x from t",
        "transformation_changed",
    ),
    "cast": (
        "insert into tgt select cast(amt as varchar(32)) as x from t",
        "insert into tgt select cast(amt as int) as x from t",
        "transformation_changed",
    ),
    "decimal_precision_scale": (
        "insert into tgt select cast(amt as decimal(18,2)) as x from t",
        "insert into tgt select cast(amt as decimal(20,4)) as x from t",
        "transformation_changed",
    ),
    "case_when_order": (
        "insert into tgt select case when dt < '2024-01-01' then 'A' "
        "when dt < '2024-06-01' then 'B' else 'C' end as x from t",
        "insert into tgt select case when dt < '2024-06-01' then 'B' "
        "when dt < '2024-01-01' then 'A' else 'C' end as x from t",
        "code_mapping_changed",
    ),
    "case_else": (
        "insert into tgt select case when dt < '2024-01-01' then 'A' else 'C' end as x from t",
        "insert into tgt select case when dt < '2024-01-01' then 'A' else 'D' end as x from t",
        "code_mapping_changed",
    ),
    "sign_flip": (
        "insert into tgt select -amt as x from t",
        "insert into tgt select amt as x from t",
        "transformation_changed",
    ),
    "plus_minus": (
        "insert into tgt select amt + fee as x from t",
        "insert into tgt select amt - fee as x from t",
        "transformation_changed",
    ),
    "amount_unit": (
        "insert into tgt select amt / 10000 as x from t",
        "insert into tgt select amt as x from t",
        "transformation_changed",
    ),
    "ratio_scale": (
        "insert into tgt select amt * 100 as x from t",
        "insert into tgt select amt as x from t",
        "transformation_changed",
    ),
    "currency": (
        "insert into tgt select amt from t where ccy = 'CNY'",
        "insert into tgt select amt from t where ccy = 'USD'",
        "filter_changed",
    ),
    "abs": (
        "insert into tgt select abs(amt) as x from t",
        "insert into tgt select amt as x from t",
        "transformation_changed",
    ),
    "round": (
        "insert into tgt select round(amt, 2) as x from t",
        "insert into tgt select round(amt, 4) as x from t",
        "transformation_changed",
    ),
    "trunc": (
        "insert into tgt select trunc(amt, 2) as x from t",
        "insert into tgt select trunc(amt, 3) as x from t",
        "transformation_changed",
    ),
    "date_part": (
        "insert into tgt select date_trunc('month', dt) as m from t",
        "insert into tgt select date_trunc('quarter', dt) as m from t",
        "transformation_changed",
    ),
    "subquery": (
        "insert into tgt select amt from t where amt > (select avg(amt) from t2)",
        "insert into tgt select amt from t where amt > (select max(amt) from t2)",
        "filter_changed",
    ),
    "exists": (
        "insert into tgt select amt from t where amt > 0",
        "insert into tgt select amt from t where amt > 0 "
        "and exists (select 1 from t2 where t2.id = t.id)",
        "filter_changed",
    ),
    "not_exists": (
        "insert into tgt select amt from t where not exists (select 1 from t2 where t2.id = t.id)",
        "insert into tgt select amt from t where exists (select 1 from t2 where t2.id = t.id)",
        "filter_changed",
    ),
    "in_predicate": (
        "insert into tgt select amt from t where status in ('A','B')",
        "insert into tgt select amt from t where status in ('A','B','C')",
        "filter_changed",
    ),
    "not_in_predicate": (
        "insert into tgt select amt from t where status not in ('A')",
        "insert into tgt select amt from t where status in ('A')",
        "filter_changed",
    ),
    "join_key": (
        "insert into tgt select a.id, b.amt as x from a join b on a.id = b.id",
        "insert into tgt select a.id, b.amt as x from a join b on a.id = b.aid",
        "join_changed",
    ),
}

# family code -> (old SQL, new SQL): the family's own construct changes, yet the
# comparator can only emit its unattributed script-level fallback.
UNSUPPORTED_CASES: dict[str, tuple[str, str]] = {
    "group_by_granularity": (
        "insert into tgt select dt, count(*) as c from t group by dt",
        "insert into tgt select dt, count(*) as c from t group by dt, branch",
    ),
    "distinct_toggle": (
        "insert into tgt select distinct branch from t",
        "insert into tgt select branch from t",
    ),
    "union_vs_union_all": (
        "insert into tgt select a from t1 union all select a from t2",
        "insert into tgt select a from t1 union select a from t2",
    ),
    "having": (
        "insert into tgt select dt, sum(amt) as c from t group by dt having sum(amt) > 100",
        "insert into tgt select dt, sum(amt) as c from t group by dt having sum(amt) > 0",
    ),
    "order_by": (
        "insert into tgt select amt from t order by dt",
        "insert into tgt select amt from t order by amt",
    ),
    "top_limit": (
        "insert into tgt select amt from t limit 10",
        "insert into tgt select amt from t limit 100",
    ),
    "cte": (
        "insert into tgt with c as (select amt from t1) select amt from c",
        "insert into tgt with c as (select amt * 2 as amt from t1) select amt from c",
    ),
    "left_vs_inner_join": (
        "insert into tgt select a.id, b.amt as x from a left join b on a.id = b.id",
        "insert into tgt select a.id, b.amt as x from a join b on a.id = b.id",
    ),
    "full_join": (
        "insert into tgt select a.id, b.amt as x from a left join b on a.id = b.id",
        "insert into tgt select a.id, b.amt as x from a full outer join b on a.id = b.id",
    ),
    "multi_table_aggregation_granularity": (
        "insert into tgt select a.id, sum(b.amt) as c from a join b on a.id = b.id group by a.id",
        "insert into tgt select a.id, sum(b.amt) as c from a join b on a.id = b.id "
        "group by a.id, b.dt",
    ),
}

FORBIDDEN_IN_FACTS = ("interpretation", "人工确认", "口径", "建议")


def _declared(detection: str) -> set[str]:
    return {spec.code for spec in SEMANTIC_FAMILIES.values() if spec.detection == detection}


def test_family_table_enumerates_every_product_spec_family():
    # The brief says "38 families" but its list enumerates 39 distinct items; all of
    # them are present and each code appears exactly once.
    assert len(SEMANTIC_FAMILIES) == 39
    for code, spec in SEMANTIC_FAMILIES.items():
        assert spec.code == code
        assert spec.label
        assert spec.note
        assert isinstance(spec.caliber_impact, bool)
        assert spec.detection in {DETECTION_COMPARATOR, DETECTION_UNSUPPORTED}
        if spec.detection == DETECTION_COMPARATOR:
            assert spec.comparator_category in SEMANTIC_LABELS, code
        else:
            assert spec.comparator_category is None, code


def test_every_family_is_either_proven_by_a_case_or_declared_unsupported():
    assert set(SUPPORTED_CASES) == _declared(DETECTION_COMPARATOR)
    assert set(UNSUPPORTED_CASES) == _declared(DETECTION_UNSUPPORTED)
    assert not (set(SUPPORTED_CASES) & set(UNSUPPORTED_CASES))


@pytest.mark.parametrize("code", sorted(SUPPORTED_CASES))
def test_supported_family_is_detected_by_a_real_sql_pair(code: str):
    old_sql, new_sql, expected_category = SUPPORTED_CASES[code]
    assert SEMANTIC_FAMILIES[code].comparator_category == expected_category

    diff = semantic_changes(old_sql, new_sql)
    assert diff["semantic_changed"] is True, code

    facts = diff["facts"]
    assert facts, code
    # the family's real change is attributed to a structural comparator dimension
    assert all(fact["attribution"] == STRUCTURAL_ATTRIBUTION for fact in facts), code
    proven = [fact for fact in facts if fact["category"] == expected_category]
    assert proven, (code, [fact["category"] for fact in facts])
    assert any(fact["before"] != fact["after"] for fact in proven), code

    # fact / interpretation split holds for this family
    assert len(diff["interpretations"]) == len(facts), code
    for fact, interpretation in zip(facts, diff["interpretations"]):
        assert set(fact) == set(FACT_FIELDS), code
        assert fact["evidence_ref"] == fact["fact_id"], code
        assert interpretation["evidence_ref"] == fact["evidence_ref"], code
        assert interpretation["category"] == fact["category"], code
        assert interpretation["requires_human_confirmation"] is True, code
        assert "interpretation" in interpretation["statement"], code
        assert "人工确认" in interpretation["statement"], code


@pytest.mark.parametrize("code", sorted(UNSUPPORTED_CASES))
def test_unsupported_family_is_reported_and_never_claimed(code: str):
    old_sql, new_sql = UNSUPPORTED_CASES[code]
    diff = semantic_changes(old_sql, new_sql)

    # the change is seen as an AST change ...
    assert diff["semantic_changed"] is True, code
    facts = diff["facts"]
    assert facts, code
    # ... but nothing is attributed to a structural dimension
    assert all(fact["attribution"] == UNATTRIBUTED_ATTRIBUTION for fact in facts), code
    assert not [fact for fact in facts if fact["attribution"] == STRUCTURAL_ATTRIBUTION], code

    # and the family is listed as an explicit gap
    assert code in {entry["code"] for entry in diff["unsupported_families"]}, code
    entry = next(item for item in diff["unsupported_families"] if item["code"] == code)
    assert entry["label"] and entry["reason"], code

    # the gap candidate is still human-gated business language
    for interpretation in diff["interpretations"]:
        assert interpretation["requires_human_confirmation"] is True, code
        assert "interpretation" in interpretation["statement"], code
        assert "人工确认" in interpretation["statement"], code


def test_unsupported_family_set_is_explicit_and_counted():
    diff = semantic_changes(*SUPPORTED_CASES["gt_vs_ge"][:2])
    declared = {entry["code"] for entry in diff["unsupported_families"]}
    assert declared == {
        "group_by_granularity",
        "distinct_toggle",
        "union_vs_union_all",
        "having",
        "order_by",
        "top_limit",
        "cte",
        "left_vs_inner_join",
        "full_join",
        "multi_table_aggregation_granularity",
    }
    assert diff["family_coverage"] == {"detected": 29, "total": 39}
    assert diff["family_coverage"]["detected"] == 39 - len(declared)


def test_identical_sql_reports_no_semantic_change():
    sql = "insert into tgt select amt from t where dt >= '2024-01-01'"
    diff = semantic_changes(sql, sql)
    assert diff["semantic_changed"] is False
    assert diff["categories"] == ["non_semantic"]
    assert diff["semantic_items"] == []
    assert diff["facts"] == []
    assert diff["interpretations"] == []
    assert diff["caliber_affecting_count"] == 0


def test_comment_and_whitespace_only_change_is_non_semantic_only():
    old_sql = (
        "insert into tgt\n"
        "  select amt, fee\n"
        "  from t\n"
        "  where dt >= '2024-01-01'"
    )
    new_sql = (
        "-- 仅注释与格式调整\n"
        "INSERT INTO tgt SELECT amt,   fee\n"
        "FROM t WHERE dt >= '2024-01-01'\n"
    )
    diff = semantic_changes(old_sql, new_sql)
    assert diff["semantic_changed"] is False
    assert diff["categories"] == ["non_semantic"]
    assert diff["facts"] == []
    assert diff["interpretations"] == []
    assert diff["unsupported_families"], "the gap list is reported for a non-semantic diff too"
    assert diff["family_coverage"] == {"detected": 29, "total": 39}


def test_facts_carry_no_business_conclusion_for_any_covered_pair():
    for code, (old_sql, new_sql, _) in SUPPORTED_CASES.items():
        diff = semantic_changes(old_sql, new_sql)
        assert diff["facts"], code
        for fact in diff["facts"]:
            assert set(fact) == set(FACT_FIELDS), code
            payload = json.dumps(fact, ensure_ascii=False)
            for forbidden in FORBIDDEN_IN_FACTS:
                assert forbidden not in payload, (code, forbidden)
            assert fact["category"] in SEMANTIC_LABELS, code
            assert fact["attribution"] in {STRUCTURAL_ATTRIBUTION, UNATTRIBUTED_ATTRIBUTION}, code
        for interpretation in diff["interpretations"]:
            assert interpretation["requires_human_confirmation"] is True, code
            assert "interpretation" in interpretation["statement"], code
            assert "人工确认" in interpretation["statement"], code


def test_evidence_refs_are_stable_and_link_every_fact_to_an_interpretation():
    old_sql, new_sql, _ = SUPPORTED_CASES["case_else"]
    first = semantic_changes(old_sql, new_sql)
    second = semantic_changes(old_sql, new_sql)
    assert first["facts"] == second["facts"]
    assert first["interpretations"] == second["interpretations"]

    refs = [fact["evidence_ref"] for fact in first["facts"]]
    assert refs and len(set(refs)) == len(refs)
    assert all(ref.startswith("sql_diff:") for ref in refs)
    assert [item["evidence_ref"] for item in first["interpretations"]] == refs


def test_legacy_consumer_contract_is_preserved():
    old_sql, new_sql = SUPPORTED_CASES["gt_vs_ge"][:2]
    diff = semantic_changes(old_sql, new_sql)

    for key in (
        "semantic_changed", "severity", "items", "semantic_items",
        "caliber_affecting_count", "categories", "summary", "authority",
        "requires_human_confirmation",
    ):
        assert key in diff, key

    assert diff["authority"] == "interpretation"
    assert diff["requires_human_confirmation"] is True
    caliber_items = [item for item in diff["items"] if item["affects_caliber"]]
    assert caliber_items
    for item in caliber_items:
        assert item["semantic"] is True
        assert "人工确认" in item["statement"]
        assert "interpretation" in item["statement"]
    assert diff["caliber_affecting_count"] == len(caliber_items)
    assert diff["semantic_items"] == [item for item in diff["items"] if item["semantic"]]
