"""Deterministic, offline fragment planning for long knowledge units.

The embedding model used by the platform (bge-small-zh) returns a
512-dimensional vector, but its *input* limit is about 512 tokens. Dimension
and token count are unrelated quantities: this module never derives a token
budget from the vector dimension, and every size decision goes through a
pluggable counter (:func:`estimate_tokens` by default).

The module is intentionally pure and side-effect free. It does not read the
database, does not call an embedding provider, and is not wired into
``reindex_project_knowledge`` yet. A caller can plan fragments, embed every
fragment text, and build metadata-only vector records that still cite the full
parent knowledge unit, so a fragment hit resolves back to the complete
evidence text.

Every number produced here is a *shape* statistic (content length, fragment
count, budget usage). It is not a retrieval/recall measurement; any recall
claim requires a measured retrieval benchmark.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from app.services.vector.base import VectorRecord
from app.services.vector.knowledge_record import build_knowledge_vector_record


FRAGMENT_STRATEGY_VERSION = "knowledge-fragment-v1"
DEFAULT_MAX_TOKENS = 480
MIN_FRAGMENT_CHARS = 40

# Structural separators tried before a hard character cut. ``：`` is
# deliberately absent: breaking there would split ``字段名：值`` in half.
FRAGMENT_BOUNDARY_SEPARATORS: tuple[str, ...] = (
    "\n",
    "；",
    ";",
    "。",
    "|",
    "，",
    ",",
)

_DANGLING_SUFFIXES = frozenset("：:")

_CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x20000, 0x2FA1F),
)


def _is_cjk_ideograph(char: str) -> bool:
    code_point = ord(char)
    for low, high in _CJK_RANGES:
        if low <= code_point <= high:
            return True
    return False


def estimate_tokens(text: str) -> int:
    """Conservatively estimate the token cost of ``text``.

    CJK ideographs count as 1 token each, ASCII characters as roughly 4
    characters per token (rounded up), and every other character as 1 token.
    This is an **estimate**, not a real tokenizer: BPE vocabularies differ per
    model and may merge common ASCII words more aggressively than 4:1.

    The name is ``estimate_tokens`` (and every persisted field repeats the
    wording) precisely so a 512-dimensional embedding cannot be mistaken for a
    512-token input budget. Feed this counter, or a model-specific tokenizer,
    into :class:`FragmentBudget`/``plan_fragments`` rather than comparing
    characters or dimensions against the token limit.
    """
    if not text:
        return 0
    cjk = 0
    ascii_chars = 0
    other = 0
    for char in text:
        if _is_cjk_ideograph(char):
            cjk += 1
        elif ord(char) < 0x80:
            ascii_chars += 1
        else:
            other += 1
    return cjk + (ascii_chars + 3) // 4 + other


@dataclass(frozen=True)
class FragmentBudget:
    """Auditable token budget: limit plus the counter that produced it."""

    max_tokens: int = DEFAULT_MAX_TOKENS
    counter: Callable[[str], int] = estimate_tokens
    counter_name: str | None = None
    counter_version: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.max_tokens, bool) or not isinstance(self.max_tokens, int):
            raise TypeError("max_tokens must be an int")
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if not callable(self.counter):
            raise TypeError("counter must be callable")
        if self.counter_name is None:
            name = "estimate-tokens" if self.counter is estimate_tokens else getattr(
                self.counter, "__name__", "custom-counter"
            )
            object.__setattr__(self, "counter_name", name)
        if self.counter_version is None:
            version = "estimate-tokens-v1" if self.counter is estimate_tokens else "custom"
            object.__setattr__(self, "counter_version", version)

    def count(self, text: str) -> int:
        return int(self.counter(text))

    def fits(self, text: str) -> bool:
        return self.count(text) <= self.max_tokens

    @property
    def descriptor(self) -> dict[str, Any]:
        """Audit descriptor suitable for ``config_json``/``validation_json``."""
        return {
            "max_tokens": self.max_tokens,
            "token_counter": self.counter_name,
            "token_counter_version": self.counter_version,
        }


@dataclass(frozen=True)
class Fragment:
    """One contiguous, non-overlapping slice of a parent knowledge unit."""

    parent_unit_id: int | None
    fragment_index: int
    char_start: int
    char_end: int
    text: str
    estimated_tokens: int
    strategy_version: str
    locator: dict[str, Any] = field(default_factory=dict)


def plan_fragments(
    unit: Any,
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    counter: Callable[[str], int] = estimate_tokens,
) -> list[Fragment]:
    """Plan non-overlapping fragments for ``unit.content``.

    A unit that fits the budget yields exactly one fragment covering
    ``[0, len(content)]``, so short units behave exactly like the current
    one-unit-one-vector pipeline. Long units are split on structural
    separators first and only hard-cut when no separator fits near the budget.
    Fragments never overlap and their concatenation is the original content.

    The incoming ``unit`` is never mutated.
    """
    budget = FragmentBudget(max_tokens=max_tokens, counter=counter)
    content = getattr(unit, "content", None)
    if not content:
        return []
    if not isinstance(content, str):
        raise TypeError("unit.content must be a string")
    unit_id = getattr(unit, "id", None)

    if budget.fits(content):
        spans = [(0, len(content))]
    else:
        spans = _plan_spans(content, budget)

    fragments: list[Fragment] = []
    for index, (start, end) in enumerate(spans):
        text = content[start:end]
        fragments.append(
            Fragment(
                parent_unit_id=unit_id,
                fragment_index=index,
                char_start=start,
                char_end=end,
                text=text,
                estimated_tokens=budget.count(text),
                strategy_version=FRAGMENT_STRATEGY_VERSION,
                locator=_fragment_locator(unit, start, end),
            )
        )
    return fragments


def build_fragment_vector_records(
    unit: Any,
    embeddings: Sequence[Sequence[float]],
    fragments: Sequence[Fragment],
    *,
    index_version_id: int | None = None,
    model_fingerprint: str | None = None,
    institution_id: int | None = None,
) -> list[VectorRecord]:
    """Build metadata-only vector records for the given fragments.

    Metadata mirrors :func:`build_knowledge_vector_record` and appends the
    fragment coordinates. ``citation_id`` still points at the parent unit
    (``knowledge-unit-<id>``), so a fragment hit cites the complete evidence.

    Record ids are deterministic SHA-256 digests over the strategy version,
    index version, document version, unit id, fragment index, fragment char
    range, content hash, and model fingerprint: re-running an index build for
    the same inputs reproduces the same ids.
    """
    fragment_list = list(fragments)
    embedding_list = list(embeddings)
    if len(embedding_list) != len(fragment_list):
        raise ValueError(
            "embedding count does not match fragment count: "
            f"{len(embedding_list)} != {len(fragment_list)}"
        )
    if not fragment_list:
        return []

    unit_id = getattr(unit, "id", None)
    if unit_id is None:
        raise ValueError("unit.id is required to build fragment vector records")
    content_hash = getattr(unit, "content_hash", None)
    if not content_hash:
        raise ValueError("unit.content_hash is required to build fragment vector records")
    document_version_id = getattr(unit, "document_version_id", None)
    citation_id = f"knowledge-unit-{unit_id}"

    seen_indexes: set[int] = set()
    for fragment in fragment_list:
        if fragment.parent_unit_id != unit_id:
            raise ValueError(
                f"fragment {fragment.fragment_index} belongs to unit "
                f"{fragment.parent_unit_id}, not {unit_id}"
            )
        if fragment.fragment_index in seen_indexes:
            raise ValueError(f"duplicate fragment_index {fragment.fragment_index}")
        seen_indexes.add(fragment.fragment_index)

    records: list[VectorRecord] = []
    for fragment, embedding in zip(fragment_list, embedding_list, strict=True):
        base = build_knowledge_vector_record(
            unit,
            embedding,
            index_version_id=index_version_id,
            model_fingerprint=model_fingerprint,
            institution_id=institution_id,
        )
        metadata = dict(base.metadata)
        metadata["citation_id"] = citation_id
        metadata.update(
            {
                "parent_unit_id": unit_id,
                "fragment_index": fragment.fragment_index,
                "fragment_char_start": fragment.char_start,
                "fragment_char_end": fragment.char_end,
                "fragment_strategy_version": fragment.strategy_version,
                "estimated_tokens": fragment.estimated_tokens,
            }
        )
        material = (
            f"{fragment.strategy_version}:{index_version_id}:{document_version_id}:"
            f"{unit_id}:{fragment.fragment_index}:{fragment.char_start}:"
            f"{fragment.char_end}:{content_hash}:{model_fingerprint}"
        )
        record_id = hashlib.sha256(material.encode("utf-8")).hexdigest()
        records.append(
            VectorRecord(id=record_id, embedding=embedding, content="", metadata=metadata)
        )
    return records


_REQUIRED_HIT_FIELDS = (
    "parent_unit_id",
    "citation_id",
    "fragment_index",
    "fragment_char_start",
    "fragment_char_end",
)


def resolve_fragment_hit(metadata: dict[str, Any]) -> dict[str, Any]:
    """Map a fragment vector hit back to its parent knowledge unit.

    Raises ``ValueError`` when the metadata is not a fragment record or is
    incomplete; there is no silent ``None`` fallback, because a fragment that
    cannot be resolved must not be cited.
    """
    if not isinstance(metadata, dict):
        raise ValueError("fragment hit metadata must be a dict")
    missing = [key for key in _REQUIRED_HIT_FIELDS if metadata.get(key) is None]
    if missing:
        raise ValueError(
            "fragment hit metadata is missing required fields: " + ", ".join(missing)
        )

    parent_unit_id = metadata["parent_unit_id"]
    citation_id = metadata["citation_id"]
    expected_citation = f"knowledge-unit-{parent_unit_id}"
    if citation_id != expected_citation:
        raise ValueError(
            f"fragment hit citation_id {citation_id!r} does not match parent unit "
            f"{parent_unit_id!r} (expected {expected_citation!r})"
        )

    fragment_index = metadata["fragment_index"]
    char_start = metadata["fragment_char_start"]
    char_end = metadata["fragment_char_end"]
    for name, value in (
        ("fragment_index", fragment_index),
        ("fragment_char_start", char_start),
        ("fragment_char_end", char_end),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"fragment hit {name} must be an int, got {value!r}")
    if char_start < 0 or char_end < char_start:
        raise ValueError(
            f"fragment hit char range is invalid: [{char_start}, {char_end}]"
        )

    return {
        "parent_unit_id": parent_unit_id,
        "citation_id": citation_id,
        "fragment_index": fragment_index,
        "char_range": [char_start, char_end],
    }


def audit_units(
    units: Iterable[Any],
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    counter: Callable[[str], int] = estimate_tokens,
) -> dict[str, Any]:
    """Report corpus shape statistics for fragment planning.

    ``over_budget_count`` counts units whose whole content exceeds the budget.
    ``truncated_risk_count`` counts units whose whole-content embedding would
    silently lose text because today's pipeline embeds ``unit.content`` as one
    vector and the provider truncates at its token limit; with the current
    estimator those two counts coincide, and they are kept separate so a
    future budget model can differ.

    This function reports *shape* only. It deliberately does not claim a
    recall improvement: that requires a measured retrieval evaluation.
    """
    budget = FragmentBudget(max_tokens=max_tokens, counter=counter)
    unit_list = list(units)
    over_budget_count = 0
    truncated_risk_count = 0
    fragment_count = 0
    max_estimated_tokens = 0
    for unit in unit_list:
        content = getattr(unit, "content", None) or ""
        tokens = budget.count(content) if content else 0
        max_estimated_tokens = max(max_estimated_tokens, tokens)
        if tokens > budget.max_tokens:
            over_budget_count += 1
            if _max_prefix_end(content, 0, budget) < len(content):
                truncated_risk_count += 1
        fragment_count += len(
            plan_fragments(unit, max_tokens=budget.max_tokens, counter=budget.counter)
        )
    return {
        "unit_count": len(unit_list),
        "over_budget_count": over_budget_count,
        "fragment_count": fragment_count,
        "max_estimated_tokens": max_estimated_tokens,
        "truncated_risk_count": truncated_risk_count,
        "max_tokens": budget.max_tokens,
        "fragment_strategy_version": FRAGMENT_STRATEGY_VERSION,
        "token_counter": budget.counter_name,
        "token_counter_version": budget.counter_version,
    }


def _plan_spans(content: str, budget: FragmentBudget) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    position = 0
    while position < len(content):
        hard_end = _max_prefix_end(content, position, budget)
        if hard_end >= len(content):
            spans.append((position, len(content)))
            break
        end = _boundary_end(content, position, hard_end, budget)
        end = _avoid_dangling_suffix(content, position, end)
        if end <= position:
            end = hard_end
        spans.append((position, end))
        position = end

    return _rebalance_tail(content, spans, budget)


def _rebalance_tail(
    content: str, spans: list[tuple[int, int]], budget: FragmentBudget
) -> list[tuple[int, int]]:
    """Avoid a tiny trailing fragment: merge it, or split the tail in half."""
    if len(spans) < 2:
        return spans
    last_start, last_end = spans[-1]
    if last_end - last_start >= MIN_FRAGMENT_CHARS:
        return spans
    combined_start = spans[-2][0]
    combined_end = last_end
    combined_tokens = budget.count(content[combined_start:combined_end])
    if combined_tokens <= budget.max_tokens:
        spans[-2:] = [(combined_start, combined_end)]
        return spans
    target = combined_tokens // 2
    cut = _max_prefix_end(content, combined_start, budget, target)
    boundary = _boundary_end(content, combined_start, cut, budget)
    if boundary > combined_start:
        cut = boundary
    if cut <= combined_start or combined_end - cut < MIN_FRAGMENT_CHARS:
        return spans
    if budget.count(content[combined_start:cut]) > budget.max_tokens:
        return spans
    if budget.count(content[cut:combined_end]) > budget.max_tokens:
        return spans
    spans[-2:] = [(combined_start, cut), (cut, combined_end)]
    return spans


def _max_prefix_end(
    content: str, start: int, budget: FragmentBudget, limit: int | None = None
) -> int:
    limit = budget.max_tokens if limit is None else limit
    if budget.count(content[start:]) <= limit:
        return len(content)
    low, high = start, len(content)
    best = start
    while low <= high:
        middle = (low + high) // 2
        if budget.count(content[start:middle]) <= limit:
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    return best


def _boundary_end(
    content: str, start: int, hard_end: int, budget: FragmentBudget
) -> int:
    window = content[start:hard_end]
    best = -1
    for separator in FRAGMENT_BOUNDARY_SEPARATORS:
        index = window.rfind(separator)
        if index > best:
            best = index
    if best < 0:
        return hard_end
    candidate = start + best + 1
    minimum_tokens = max(1, budget.max_tokens // 2)
    if budget.count(content[start:candidate]) < minimum_tokens:
        return hard_end
    return candidate


def _avoid_dangling_suffix(content: str, start: int, end: int) -> int:
    while end > start + 1 and content[end - 1] in _DANGLING_SUFFIXES:
        end -= 1
    return end


def _fragment_locator(unit: Any, start: int, end: int) -> dict[str, Any]:
    metadata = getattr(unit, "metadata_json", None)
    locator: dict[str, Any] = {}
    if isinstance(metadata, dict):
        parent_locator = metadata.get("locator")
        if isinstance(parent_locator, dict):
            locator.update(deepcopy(parent_locator))
    locator.update(
        {
            "source_sheet_name": getattr(unit, "source_sheet_name", None),
            "source_cell_range": getattr(unit, "source_cell_range", None),
            "source_page_no": getattr(unit, "source_page_no", None),
            "source_heading": getattr(unit, "source_heading", None),
            "fragment_char_range": [start, end],
        }
    )
    return locator


__all__ = [
    "DEFAULT_MAX_TOKENS",
    "FRAGMENT_BOUNDARY_SEPARATORS",
    "FRAGMENT_STRATEGY_VERSION",
    "Fragment",
    "FragmentBudget",
    "MIN_FRAGMENT_CHARS",
    "audit_units",
    "build_fragment_vector_records",
    "estimate_tokens",
    "plan_fragments",
    "resolve_fragment_hit",
]
