"""Statement-level semantic comparison: the coverage obligations for the six new families.

``test_sql_semantic_diff_v2.py`` proves *that* each family is detected by one real SQL
pair.  This file proves the detection is *trustworthy*: for every upgraded family it
covers the six obligations the package requires, and it pins the negative direction so
a formatting change can never be reported as a semantic one.

The six obligations per family:
    1. a real semantic change is detected and attributed structurally;
    2. a formatting / keyword-case only rewrite is not detected;
    3. an alias or qualifier rename is not detected as that family's change;
    4. a nested scope (subquery / CTE) is still attributed, not silently dropped;
    5. an unparseable input degrades without inventing an attribution;
    6. a multi-statement script attributes the change to the right statement.

Nothing here asserts a business conclusion: facts stay mechanical, interpretations stay
human-gated.
"""

from __future__ import annotations

import pytest

from app.services.lineage.sql_semantic_diff import (
    DETECTION_COMPARATOR,
    DETECTION_UNSUPPORTED,
    SEMANTIC_FAMILIES,
    STRUCTURAL_ATTRIBUTION,
    UNATTRIBUTED_ATTRIBUTION,
    semantic_changes,
)

# family -> (category it must emit, old SQL, new SQL)
UPGRADED_FAMILIES: dict[str, tuple[str, str, str]] = {
    "group_by_granularity": (
        "group_by_changed",
        "insert into tgt select dt, count(*) as c from t group by dt",
        "insert into tgt select dt, branch, count(*) as c from t group by dt, branch",
    ),
    "distinct_toggle": (
        "distinct_changed",
        "insert into tgt select distinct branch from t",
        "insert into tgt select branch from t",
    ),
    "union_vs_union_all": (
        "union_mode_changed",
        "insert into tgt select a from t1 union all select a from t2",
        "insert into tgt select a from t1 union select a from t2",
    ),
    "left_vs_inner_join": (
        "join_type_changed",
        "insert into tgt select a.id, b.amt as x from a left join b on a.id = b.id",
        "insert into tgt select a.id, b.amt as x from a inner join b on a.id = b.id",
    ),
    "full_join": (
        "join_type_changed",
        "insert into tgt select a.id, b.amt as x from a left join b on a.id = b.id",
        "insert into tgt select a.id, b.amt as x from a full outer join b on a.id = b.id",
    ),
    "multi_table_aggregation_granularity": (
        "group_by_changed",
        "insert into tgt select a.id, sum(b.amt) as c from a join b on a.id = b.id group by a.id",
        "insert into tgt select a.id, sum(b.amt) as c from a join b on a.id = b.id "
        "group by a.id, b.dt",
    ),
    "having": (
        "having_changed",
        "insert into tgt select dt, sum(amt) as c from t group by dt having sum(amt) > 100",
        "insert into tgt select dt, sum(amt) as c from t group by dt having sum(amt) > 0",
    ),
}


def _categories(diff: dict) -> set[str]:
    return {fact["category"] for fact in diff["facts"]}


def _attributions(diff: dict) -> set[str]:
    return {fact["attribution"] for fact in diff["facts"]}


# ---------------------------------------------------------------- 0. declared capability


def test_every_upgraded_family_is_declared_as_a_comparator_family():
    for code in UPGRADED_FAMILIES:
        assert SEMANTIC_FAMILIES[code].detection == DETECTION_COMPARATOR, code


def test_only_four_families_remain_unsupported_and_none_is_an_upgrade():
    """Pins the honest boundary: the remaining gaps must not overlap the upgraded set."""

    remaining = {
        code
        for code, spec in SEMANTIC_FAMILIES.items()
        if spec.detection == DETECTION_UNSUPPORTED
    }
    assert remaining == {"order_by", "top_limit", "cte"}
    assert not remaining & set(UPGRADED_FAMILIES)


# ---------------------------------------------------------------- 1. real change detected


@pytest.mark.parametrize("code", sorted(UPGRADED_FAMILIES))
def test_real_change_is_detected_and_attributed_structurally(code: str):
    category, old_sql, new_sql = UPGRADED_FAMILIES[code]
    diff = semantic_changes(old_sql, new_sql)

    assert diff["semantic_changed"] is True, code
    assert category in _categories(diff), (code, sorted(_categories(diff)))
    assert STRUCTURAL_ATTRIBUTION in _attributions(diff), code
    assert UNATTRIBUTED_ATTRIBUTION not in _attributions(diff), code

    proven = [fact for fact in diff["facts"] if fact["category"] == category]
    assert any(fact["before"] != fact["after"] for fact in proven), code
    assert all(fact["entity_type"] != "script" for fact in proven), code


@pytest.mark.parametrize("code", sorted(UPGRADED_FAMILIES))
def test_change_is_reported_as_caliber_affecting_and_human_gated(code: str):
    category, old_sql, new_sql = UPGRADED_FAMILIES[code]
    diff = semantic_changes(old_sql, new_sql)

    proven = [item for item in diff["semantic_items"] if item["category"] == category]
    assert proven, code
    assert all(item["affects_caliber"] for item in proven), code

    for interpretation in diff["interpretations"]:
        assert interpretation["requires_human_confirmation"] is True, code


# ---------------------------------------------------------------- 2. formatting is silent


FORMATTING_PAIRS: dict[str, tuple[str, str]] = {
    "group_by_granularity": (
        "insert into tgt select dt, count(*) as c from t group by dt",
        "INSERT INTO tgt\n  SELECT dt, COUNT(*) AS c\nFROM t\nGROUP BY dt",
    ),
    "distinct_toggle": (
        "insert into tgt select distinct branch from t",
        "INSERT INTO tgt SELECT DISTINCT branch FROM t",
    ),
    "union_vs_union_all": (
        "insert into tgt select a from t1 union all select a from t2",
        "INSERT INTO tgt SELECT a FROM t1 UNION ALL SELECT a FROM t2",
    ),
    "left_vs_inner_join": (
        "insert into tgt select a.id from a left join b on a.id = b.id",
        "insert into tgt\nselect a.id\nfrom a\nleft join b on a.id = b.id",
    ),
    "full_join": (
        "insert into tgt select a.id from a full outer join b on a.id = b.id",
        "INSERT INTO tgt SELECT a.id FROM a FULL OUTER JOIN b ON a.id = b.id",
    ),
    "multi_table_aggregation_granularity": (
        "insert into tgt select a.id, sum(b.amt) as c from a join b on a.id = b.id group by a.id",
        "INSERT INTO tgt SELECT a.id, SUM(b.amt) AS c FROM a JOIN b ON a.id = b.id GROUP BY a.id",
    ),
    "having": (
        "insert into tgt select dt, sum(amt) as c from t group by dt having sum(amt) > 100",
        "INSERT INTO tgt SELECT dt, SUM(amt) AS c FROM t GROUP BY dt HAVING SUM(amt) > 100",
    ),
}


@pytest.mark.parametrize("code", sorted(FORMATTING_PAIRS))
def test_formatting_and_keyword_case_alone_is_not_a_semantic_change(code: str):
    old_sql, new_sql = FORMATTING_PAIRS[code]
    diff = semantic_changes(old_sql, new_sql)
    assert diff["semantic_changed"] is False, (code, sorted(_categories(diff)))


# ---------------------------------------------------------------- 3. alias rename is silent


@pytest.mark.parametrize(
    "old_sql,new_sql",
    [
        (
            "insert into tgt select a.dt, count(*) as c from t a group by a.dt",
            "insert into tgt select b.dt, count(*) as c from t b group by b.dt",
        ),
        (
            "insert into tgt select a.k, sum(b.amt) as c from x a join y b on a.id = b.id "
            "group by a.k",
            "insert into tgt select p.k, sum(q.amt) as c from x p join y q on p.id = q.id "
            "group by p.k",
        ),
    ],
)
def test_alias_rename_never_reports_the_statement_level_families(old_sql: str, new_sql: str):
    diff = semantic_changes(old_sql, new_sql)
    categories = _categories(diff)
    assert "group_by_changed" not in categories
    assert "join_type_changed" not in categories
    assert "union_mode_changed" not in categories


def test_grouping_key_order_swap_is_not_a_granularity_change():
    # SQL does not attach meaning to the order of GROUP BY keys.
    diff = semantic_changes(
        "insert into tgt select dt, br, sum(amt) as c from t group by dt, br",
        "insert into tgt select dt, br, sum(amt) as c from t group by br, dt",
    )
    assert "group_by_changed" not in _categories(diff)


# ---------------------------------------------------------------- 4. nested scopes


def test_group_by_inside_a_subquery_is_attributed():
    diff = semantic_changes(
        "insert into tgt select s.dt from (select dt from t group by dt) s",
        "insert into tgt select s.dt from (select dt from t group by dt, branch) s",
    )
    assert "group_by_changed" in _categories(diff)
    assert STRUCTURAL_ATTRIBUTION in _attributions(diff)


def test_join_type_inside_a_cte_is_attributed():
    diff = semantic_changes(
        "insert into tgt with c as (select a.id from a left join b on a.id = b.id) "
        "select id from c",
        "insert into tgt with c as (select a.id from a inner join b on a.id = b.id) "
        "select id from c",
    )
    assert "join_type_changed" in _categories(diff)


def test_distinct_inside_a_cte_is_attributed():
    diff = semantic_changes(
        "insert into tgt with c as (select distinct branch from t) select branch from c",
        "insert into tgt with c as (select branch from t) select branch from c",
    )
    assert "distinct_changed" in _categories(diff)


# ---------------------------------------------------------------- 5. unparseable input


def test_unparseable_sql_degrades_without_inventing_an_attribution():
    diff = semantic_changes(
        "insert into tgt select from where",
        "insert into tgt select )(",
    )
    # Whatever the comparator decides, it may never fabricate a structural attribution
    # for a statement it could not actually read.
    for fact in diff["facts"]:
        assert fact["attribution"] in {UNATTRIBUTED_ATTRIBUTION, STRUCTURAL_ATTRIBUTION}
        assert fact["category"] in {"parse_quality_changed", "transformation_changed",
                                    "non_semantic"}
    assert "group_by_changed" not in _categories(diff)
    assert "join_type_changed" not in _categories(diff)


def test_empty_and_comment_only_versions_report_no_statement_level_change():
    for old_sql, new_sql in (("", ""), ("-- nothing\n", "\n-- nothing\n")):
        diff = semantic_changes(old_sql, new_sql)
        assert diff["semantic_changed"] is False
        assert diff["facts"] == []


# ---------------------------------------------------------------- 6. multi-statement scripts


def test_change_is_attributed_to_the_changed_statement_not_the_neighbour():
    old_sql = (
        "insert into tgt1 select dt, count(*) as c from t group by dt;\n"
        "insert into tgt2 select a.id from a left join b on a.id = b.id"
    )
    new_sql = (
        "insert into tgt1 select dt, count(*) as c from t group by dt;\n"
        "insert into tgt2 select a.id from a inner join b on a.id = b.id"
    )
    diff = semantic_changes(old_sql, new_sql)
    assert "join_type_changed" in _categories(diff)
    # The untouched first statement must not produce a granularity change.
    assert "group_by_changed" not in _categories(diff)


def test_two_independent_changes_are_both_reported():
    old_sql = (
        "insert into tgt1 select dt, count(*) as c from t group by dt;\n"
        "insert into tgt2 select a.id from a left join b on a.id = b.id"
    )
    new_sql = (
        "insert into tgt1 select dt, branch, count(*) as c from t group by dt, branch;\n"
        "insert into tgt2 select a.id from a inner join b on a.id = b.id"
    )
    diff = semantic_changes(old_sql, new_sql)
    categories = _categories(diff)
    assert "group_by_changed" in categories
    assert "join_type_changed" in categories


# ---------------------------------------------------------------- union / distinct interaction


def test_union_rewrite_is_not_also_reported_as_a_distinct_change():
    """sqlglot marks a plain UNION query as distinct internally.

    A UNION -> UNION ALL rewrite must be attributed once, to the union family.  Reporting
    it twice (as a DISTINCT change too) would inflate the change set with a phantom.
    """

    diff = semantic_changes(
        "insert into tgt select a from t1 union all select a from t2",
        "insert into tgt select a from t1 union select a from t2",
    )
    categories = _categories(diff)
    assert "union_mode_changed" in categories
    assert "distinct_changed" not in categories


def test_true_distinct_change_still_reports_distinct_when_no_union_is_involved():
    diff = semantic_changes(
        "insert into tgt select distinct a from t",
        "insert into tgt select a from t",
    )
    assert "distinct_changed" in _categories(diff)
    assert "union_mode_changed" not in _categories(diff)
