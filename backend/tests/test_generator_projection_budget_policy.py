from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.mapping import context_adapters as adapters
from app.services.semantic.context_authority import AuthorityRank


def _fact(authority: str, fact_type: str, source_type: str, source_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        authority=AuthorityRank(authority),
        fact_type=fact_type,
        source_type=source_type,
        source_id=source_id,
    )


def _ordered() -> list[SimpleNamespace]:
    candidates = [
        _fact("inferred", "source_mart_candidate", "resolver_candidate", 200 + index)
        for index in range(29)
    ]
    knowledge = [
        _fact("retrieved", "retrieved_knowledge", "retrieved_knowledge", 6881 + index)
        for index in range(22)
    ]
    metadata = [_fact("metadata", "target_field_metadata", "target_metadata", 23)]
    mapping = [_fact("inferred", "mapping_candidate", "resolver_candidate", 42)]
    facts = [*candidates, *knowledge, *metadata, *mapping]
    return sorted(facts, key=adapters._fact_sort_key)


def test_projection_limits_are_configurable() -> None:
    class FakeSettings:
        generation_projection_char_limit = 4096
        generation_projection_fact_limit = 7

    provider = SimpleNamespace(get_settings=lambda: FakeSettings())
    assert adapters.projection_char_limit.__module__ == adapters.__name__

    original = adapters.get_settings
    adapters.get_settings = provider.get_settings  # type: ignore[assignment]
    try:
        assert adapters.projection_char_limit() == 4096
        assert adapters.projection_fact_limit() == 7
    finally:
        adapters.get_settings = original  # type: ignore[assignment]


def test_fact_cap_never_drops_a_fact_class_wholesale() -> None:
    ordered = _ordered()
    admitted = adapters._admit_facts(ordered, 30)

    assert len(admitted) == 30
    classes = {(fact.authority.value, fact.fact_type) for fact in admitted}
    # A plain authority-ordered slice would have dropped every candidate beyond
    # the first few; the cap must keep at least one fact of each class.
    assert classes == {
        ("metadata", "target_field_metadata"),
        ("retrieved", "retrieved_knowledge"),
        ("inferred", "source_mart_candidate"),
        ("inferred", "mapping_candidate"),
    }


def test_fact_cap_still_bounds_the_total_and_keeps_authority_order() -> None:
    ordered = _ordered()
    admitted = adapters._admit_facts(ordered, 11)

    assert len(admitted) == 11
    assert admitted == sorted(admitted, key=adapters._fact_sort_key)
    assert admitted[0].authority.value == "metadata"


def test_fact_cap_is_identity_when_everything_fits() -> None:
    ordered = _ordered()

    assert adapters._admit_facts(ordered, len(ordered)) == ordered
    assert adapters._admit_facts(ordered, 10_000) == ordered


@pytest.mark.parametrize("limit", [0, -1])
def test_fact_cap_rejects_a_non_positive_budget(limit: int) -> None:
    assert adapters._admit_facts(_ordered(), limit) == []
