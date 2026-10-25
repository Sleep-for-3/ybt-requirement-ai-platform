"""Tests for the P1-D long-knowledge-unit fragment planner.

The planner is pure: these tests use ``SimpleNamespace`` fakes instead of
database rows and never call an embedding provider.
"""

import copy
import hashlib
from types import SimpleNamespace

import pytest

from app.services.semantic_index.chunking import (
    DEFAULT_MAX_TOKENS,
    FRAGMENT_BOUNDARY_SEPARATORS,
    FRAGMENT_STRATEGY_VERSION,
    MIN_FRAGMENT_CHARS,
    FragmentBudget,
    audit_units,
    build_fragment_vector_records,
    estimate_tokens,
    plan_fragments,
    resolve_fragment_hit,
)


HEAD_SIGNAL = "SIGNAL_HEAD_7f3a"
MID_SIGNAL = "SIGNAL_MID_2c9e"
TAIL_SIGNAL = "SIGNAL_TAIL_9d41"
SIGNALS = (HEAD_SIGNAL, MID_SIGNAL, TAIL_SIGNAL)


def _block(index: int) -> str:
    return (
        f"字段代码：F{index:03d}；字段名称：客户编号字段{index:03d}；"
        "口径：按开户机构维度统计对公客户编号；来源系统：核心系统；"
        "数据类型：VARCHAR(32)；加工逻辑：取最新有效记录；"
    )


def _long_row() -> str:
    """One wide-table row of ~3400 chars with unique signals at head/mid/tail."""
    blocks = [_block(index) for index in range(40)]
    blocks[0] += f"备注：{HEAD_SIGNAL}；"
    blocks[len(blocks) // 2] += f"备注：{MID_SIGNAL}；"
    blocks[-1] += f"备注：{TAIL_SIGNAL}；"
    return "".join(blocks)


def _unit(
    content: str,
    *,
    unit_id: int = 101,
    metadata_json: dict | None = None,
    source_sheet_name: str = "宽表",
    source_cell_range: str = "A2:Z2",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=unit_id,
        project_id=1,
        document_id=2,
        document_version_id=3,
        knowledge_type="field_definition",
        knowledge_scope="project",
        institution_name="示例银行",
        target_field_code="CUST_NO",
        scenario_id=None,
        confidentiality_level="internal",
        content=content,
        normalized_content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        source_sheet_name=source_sheet_name,
        source_cell_range=source_cell_range,
        source_page_no=None,
        source_heading=None,
        metadata_json=metadata_json if metadata_json is not None else {},
    )


def _truncate_to_budget(text: str, max_tokens: int) -> str:
    """Simulate today's provider truncation of one whole unit text."""
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_tokens(text[:middle]) <= max_tokens:
            low = middle
        else:
            high = middle - 1
    return text[:low]


def test_estimate_tokens_is_an_estimate_not_a_dimension() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("知识单元") == 4  # CJK ideograph = 1 token
    assert estimate_tokens("abcd") == 1  # ASCII = ~4 chars per token
    assert estimate_tokens("abcde") == 2  # rounded up
    assert estimate_tokens("knowledge") == 3
    assert estimate_tokens("字段A：abcde") == 5
    assert estimate_tokens("字段：值\n") == 5


def test_fragment_budget_records_the_counter_for_audit() -> None:
    default = FragmentBudget()
    assert default.max_tokens == DEFAULT_MAX_TOKENS == 480
    assert default.counter_name == "estimate-tokens"
    assert default.counter_version == "estimate-tokens-v1"
    assert default.count("贷款余额") == 4
    assert default.fits("贷款余额") is True
    assert default.descriptor == {
        "max_tokens": 480,
        "token_counter": "estimate-tokens",
        "token_counter_version": "estimate-tokens-v1",
    }

    custom = FragmentBudget(
        max_tokens=120, counter=len, counter_name="char-count", counter_version="test-v1"
    )
    assert custom.count("abcdef") == 6
    assert custom.descriptor["token_counter"] == "char-count"

    with pytest.raises(ValueError):
        FragmentBudget(max_tokens=0)
    with pytest.raises(TypeError):
        FragmentBudget(counter=object())


def test_short_unit_returns_single_whole_fragment() -> None:
    content = "短知识：贷款余额按日终余额取值，口径为对公客户。"
    unit = _unit(content)

    fragments = plan_fragments(unit)

    assert len(fragments) == 1
    fragment = fragments[0]
    assert fragment.parent_unit_id == unit.id
    assert fragment.fragment_index == 0
    assert fragment.char_start == 0
    assert fragment.char_end == len(content)
    assert fragment.text == content
    assert fragment.estimated_tokens == estimate_tokens(content)
    assert fragment.strategy_version == FRAGMENT_STRATEGY_VERSION
    assert fragment.locator["fragment_char_range"] == [0, len(content)]
    assert fragment.locator["source_sheet_name"] == "宽表"
    assert fragment.locator["source_cell_range"] == "A2:Z2"


def test_head_mid_tail_signals_land_in_distinct_fragments() -> None:
    content = _long_row()
    assert 2800 <= len(content) <= 3600, "fixture should model a ~3000-char wide row"
    unit = _unit(content)

    fragments = plan_fragments(unit)

    assert len(fragments) > 1
    fragment_indexes = []
    for signal in SIGNALS:
        owners = [fragment.fragment_index for fragment in fragments if signal in fragment.text]
        assert len(owners) == 1, f"{signal} must be searchable inside exactly one fragment"
        fragment_indexes.append(owners[0])
    assert len(set(fragment_indexes)) == 3
    assert fragment_indexes == sorted(fragment_indexes)


def test_boundaries_never_cut_a_field_name_from_its_value() -> None:
    unit = _unit(_long_row())

    fragments = plan_fragments(unit)

    for fragment in fragments:
        assert fragment.text
        assert not fragment.text.endswith("：")
        assert not fragment.text.rstrip().endswith("：")
    for fragment in fragments[:-1]:
        assert fragment.text[-1] in FRAGMENT_BOUNDARY_SEPARATORS
        assert len(fragment.text) >= MIN_FRAGMENT_CHARS


def test_fragments_respect_budget_and_cover_content_exactly() -> None:
    content = _long_row()
    unit = _unit(content)

    fragments = plan_fragments(unit)

    assert fragments[0].char_start == 0
    assert fragments[-1].char_end == len(content)
    for fragment in fragments:
        assert fragment.estimated_tokens <= DEFAULT_MAX_TOKENS
        assert fragment.estimated_tokens == estimate_tokens(fragment.text)
        assert content[fragment.char_start:fragment.char_end] == fragment.text
    for index in range(1, len(fragments)):
        assert fragments[index].char_start == fragments[index - 1].char_end
    assert "".join(fragment.text for fragment in fragments) == content


def test_fragment_locator_preserves_parent_coordinates_without_mutation() -> None:
    content = _long_row()
    unit = _unit(content, metadata_json={"locator": {"page": 3, "row": 9, "bbox": [1, 2, 3, 4]}})
    snapshot = copy.deepcopy(vars(unit))

    fragments = plan_fragments(unit)

    assert vars(unit) == snapshot
    assert unit.metadata_json == {"locator": {"page": 3, "row": 9, "bbox": [1, 2, 3, 4]}}
    for fragment in fragments:
        locator = fragment.locator
        assert locator["page"] == 3
        assert locator["row"] == 9
        assert locator["bbox"] == [1, 2, 3, 4]
        assert locator["source_sheet_name"] == "宽表"
        assert locator["source_cell_range"] == "A2:Z2"
        assert locator["fragment_char_range"] == [fragment.char_start, fragment.char_end]
    fragments[0].locator["page"] = 99
    assert unit.metadata_json["locator"]["page"] == 3


def test_plan_fragments_accepts_an_injected_counter() -> None:
    content = _long_row()
    unit = _unit(content)

    fragments = plan_fragments(unit, max_tokens=120, counter=len)

    assert len(fragments) > 1
    assert "".join(fragment.text for fragment in fragments) == content
    for fragment in fragments:
        assert fragment.estimated_tokens == len(fragment.text)
        assert len(fragment.text) <= 120
    assert max(len(fragment.text) for fragment in fragments) > 60


def test_empty_content_plans_no_fragments() -> None:
    unit = _unit("")

    assert plan_fragments(unit) == []
    assert build_fragment_vector_records(unit, [], []) == []


def test_build_fragment_vector_records_keeps_parent_citation() -> None:
    unit = _unit(_long_row())
    fragments = plan_fragments(unit)
    embeddings = [[0.1, 0.2, 0.3] for _ in fragments]

    records = build_fragment_vector_records(
        unit,
        embeddings,
        fragments,
        index_version_id=42,
        model_fingerprint="bge-small-zh-v1.5-512",
        institution_id=7,
    )

    assert len(records) == len(fragments)
    assert len({record.id for record in records}) == len(records)
    for record, fragment in zip(records, fragments, strict=True):
        metadata = record.metadata
        assert record.content == ""
        assert metadata["knowledge_unit_id"] == unit.id
        assert metadata["chunk_id"] == unit.id
        assert metadata["citation_id"] == f"knowledge-unit-{unit.id}"
        assert metadata["parent_unit_id"] == unit.id
        assert metadata["fragment_index"] == fragment.fragment_index
        assert metadata["fragment_char_start"] == fragment.char_start
        assert metadata["fragment_char_end"] == fragment.char_end
        assert metadata["fragment_strategy_version"] == FRAGMENT_STRATEGY_VERSION
        assert metadata["estimated_tokens"] == fragment.estimated_tokens
        assert metadata["content_hash"] == unit.content_hash
        assert metadata["embedding_model_fingerprint"] == "bge-small-zh-v1.5-512"
        assert metadata["embedding_index_version_id"] == 42
        assert metadata["institution_id"] == 7

    unversioned = build_fragment_vector_records(unit, embeddings, fragments)
    assert [record.metadata["citation_id"] for record in unversioned] == [
        f"knowledge-unit-{unit.id}" for _ in fragments
    ]
    assert len({record.id for record in unversioned}) == len(fragments)


def test_fragment_record_ids_are_deterministic() -> None:
    unit = _unit(_long_row())
    fragments = plan_fragments(unit)
    embeddings = [[0.5, 0.25] for _ in fragments]
    kwargs = {
        "index_version_id": 42,
        "model_fingerprint": "bge-small-zh-v1.5-512",
        "institution_id": 7,
    }

    first = build_fragment_vector_records(unit, embeddings, fragments, **kwargs)
    second = build_fragment_vector_records(unit, embeddings, fragments, **kwargs)

    assert [record.id for record in first] == [record.id for record in second]
    assert all(len(record.id) == 64 for record in first)

    other_version = build_fragment_vector_records(
        unit, embeddings, fragments, **{**kwargs, "index_version_id": 43}
    )
    assert {record.id for record in first}.isdisjoint({record.id for record in other_version})


def test_build_fragment_vector_records_rejects_length_mismatch() -> None:
    unit = _unit(_long_row())
    fragments = plan_fragments(unit)
    embeddings = [[0.1] for _ in fragments]

    with pytest.raises(ValueError, match="embedding count"):
        build_fragment_vector_records(unit, embeddings[:-1], fragments)
    with pytest.raises(ValueError, match="embedding count"):
        build_fragment_vector_records(unit, [*embeddings, [0.1]], fragments)


def test_resolve_fragment_hit_maps_back_to_the_parent_unit() -> None:
    unit = _unit(_long_row())
    fragments = plan_fragments(unit)
    records = build_fragment_vector_records(
        unit,
        [[0.1] for _ in fragments],
        fragments,
        index_version_id=42,
        model_fingerprint="fp",
    )

    hit = resolve_fragment_hit(records[0].metadata)

    assert hit == {
        "parent_unit_id": unit.id,
        "citation_id": f"knowledge-unit-{unit.id}",
        "fragment_index": fragments[0].fragment_index,
        "char_range": [fragments[0].char_start, fragments[0].char_end],
    }


@pytest.mark.parametrize(
    "field",
    [
        "parent_unit_id",
        "citation_id",
        "fragment_index",
        "fragment_char_start",
        "fragment_char_end",
    ],
)
def test_resolve_fragment_hit_raises_when_a_field_is_missing(field: str) -> None:
    unit = _unit("短知识：贷款余额按日终余额取值。")
    fragments = plan_fragments(unit)
    metadata = build_fragment_vector_records(unit, [[0.1]], fragments)[0].metadata
    broken = dict(metadata)
    broken.pop(field)

    with pytest.raises(ValueError, match=field):
        resolve_fragment_hit(broken)


def test_resolve_fragment_hit_rejects_an_inconsistent_citation() -> None:
    unit = _unit("短知识：贷款余额按日终余额取值。")
    fragments = plan_fragments(unit)
    metadata = dict(build_fragment_vector_records(unit, [[0.1]], fragments)[0].metadata)
    metadata["citation_id"] = "knowledge-unit-999"

    with pytest.raises(ValueError, match="citation_id"):
        resolve_fragment_hit(metadata)


def test_audit_units_counts_over_budget_and_truncation_risk() -> None:
    long_unit = _unit(_long_row(), unit_id=11)
    short_unit = _unit("短知识：贷款余额按日终余额取值。", unit_id=12)

    audit = audit_units([long_unit, short_unit])

    long_fragments = plan_fragments(long_unit)
    assert audit["unit_count"] == 2
    assert audit["over_budget_count"] == 1
    assert audit["truncated_risk_count"] == 1
    assert audit["fragment_count"] == len(long_fragments) + 1
    assert audit["max_estimated_tokens"] == estimate_tokens(long_unit.content)
    assert audit["max_tokens"] == DEFAULT_MAX_TOKENS
    assert audit["fragment_strategy_version"] == FRAGMENT_STRATEGY_VERSION
    assert audit["token_counter"] == "estimate-tokens"
    assert audit["token_counter_version"] == "estimate-tokens-v1"


def test_audit_units_is_empty_safe() -> None:
    audit = audit_units([])

    assert audit["unit_count"] == 0
    assert audit["over_budget_count"] == 0
    assert audit["truncated_risk_count"] == 0
    assert audit["fragment_count"] == 0
    assert audit["max_estimated_tokens"] == 0


def test_truncation_loses_tail_signals_while_fragments_keep_them() -> None:
    """Honest baseline-vs-fragment comparison.

    Today the pipeline embeds the whole unit text with one call, so the
    provider truncates everything after ~512 tokens. This test asserts only
    that truncation drops the middle/tail signal text while fragmenting keeps
    every signal. It is *not* a retrieval/recall evaluation.
    """
    content = _long_row()
    unit = _unit(content)

    truncated = _truncate_to_budget(content, DEFAULT_MAX_TOKENS)

    assert len(truncated) < len(content)
    assert HEAD_SIGNAL in truncated
    assert MID_SIGNAL not in truncated
    assert TAIL_SIGNAL not in truncated

    fragments = plan_fragments(unit)
    joined = "".join(fragment.text for fragment in fragments)

    assert joined == content
    owners = {}
    for signal in SIGNALS:
        matches = [fragment for fragment in fragments if signal in fragment.text]
        assert len(matches) == 1, f"{signal} was lost or duplicated by fragmenting"
        owners[signal] = matches[0].fragment_index
    assert len(set(owners.values())) == len(SIGNALS)
