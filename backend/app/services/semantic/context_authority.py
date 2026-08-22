"""Stable authority and fact-state policy for RegulatoryContext facts.

Authority describes how much weight a source is allowed to carry.  Fact state
describes the source row's governed lifecycle or observation state.  The two
vocabularies intentionally remain independent: ranking a retrieved or inferred
fact never confirms it.
"""

from enum import Enum
from types import MappingProxyType
from typing import Mapping


class AuthorityRank(str, Enum):
    FORMAL = "formal"
    HUMAN_CONFIRMED = "human_confirmed"
    REGULATORY = "regulatory"
    SEMANTIC = "semantic"
    MAPPING = "mapping"
    LINEAGE = "lineage"
    METADATA = "metadata"
    HISTORICAL = "historical"
    RETRIEVED = "retrieved"
    INFERRED = "inferred"


class FactState(str, Enum):
    CONFIRMED = "confirmed"
    APPROVED = "approved"
    VERIFIED = "verified"
    OBSERVED = "observed"
    DRAFT = "draft"
    AI_SUGGESTED = "ai_suggested"
    HISTORICAL = "historical"
    RETRIEVED = "retrieved"
    INFERRED = "inferred"
    UNVERIFIED = "unverified"
    FLAGGED = "flagged"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"


# Formal and explicitly human-confirmed sources share the highest tier.  The
# numeric values are an implementation detail; callers compare through the
# public helper rather than depending on Enum declaration order.
AUTHORITY_RANKS: Mapping[AuthorityRank, int] = MappingProxyType({
    AuthorityRank.FORMAL: 900,
    AuthorityRank.HUMAN_CONFIRMED: 900,
    AuthorityRank.REGULATORY: 850,
    AuthorityRank.SEMANTIC: 800,
    AuthorityRank.MAPPING: 700,
    AuthorityRank.LINEAGE: 600,
    AuthorityRank.METADATA: 500,
    AuthorityRank.HISTORICAL: 400,
    AuthorityRank.RETRIEVED: 300,
    AuthorityRank.INFERRED: 200,
})


_SOURCE_AUTHORITIES: Mapping[str, AuthorityRank] = MappingProxyType({
    "formal": AuthorityRank.FORMAL,
    "formal_regulation": AuthorityRank.FORMAL,
    "formal_regulatory": AuthorityRank.FORMAL,
    "human_confirmed": AuthorityRank.HUMAN_CONFIRMED,
    "human_review": AuthorityRank.HUMAN_CONFIRMED,
    "regulatory": AuthorityRank.REGULATORY,
    "regulatory_knowledge": AuthorityRank.REGULATORY,
    "regulatory_knowledge_item": AuthorityRank.REGULATORY,
    "semantic": AuthorityRank.SEMANTIC,
    "semantic_concept": AuthorityRank.SEMANTIC,
    "semantic_concept_version": AuthorityRank.SEMANTIC,
    "approved_mapping": AuthorityRank.MAPPING,
    "mapping": AuthorityRank.MAPPING,
    "source_to_mart_mapping": AuthorityRank.MAPPING,
    "mart_to_ybt_mapping": AuthorityRank.MAPPING,
    "scenario_business_mapping": AuthorityRank.MAPPING,
    "verified_lineage": AuthorityRank.LINEAGE,
    "lineage": AuthorityRank.LINEAGE,
    "scenario_technical_lineage": AuthorityRank.LINEAGE,
    "metadata": AuthorityRank.METADATA,
    "target_metadata": AuthorityRank.METADATA,
    "source_metadata": AuthorityRank.METADATA,
    "mart_metadata": AuthorityRank.METADATA,
    "historical": AuthorityRank.HISTORICAL,
    "historical_caliber": AuthorityRank.HISTORICAL,
    "retrieved": AuthorityRank.RETRIEVED,
    "retrieved_knowledge": AuthorityRank.RETRIEVED,
    "knowledge_retrieval": AuthorityRank.RETRIEVED,
    "inferred": AuthorityRank.INFERRED,
    "ai_inference": AuthorityRank.INFERRED,
    "resolver_candidate": AuthorityRank.INFERRED,
})


def _normalize_source_type(source_type: str) -> str:
    normalized = "_".join(str(source_type).strip().lower().replace("-", " ").split())
    if not normalized:
        raise ValueError("source_type must not be blank")
    return normalized


def _coerce_authority(value: AuthorityRank | str) -> AuthorityRank:
    if isinstance(value, AuthorityRank):
        return value
    try:
        return AuthorityRank(str(value))
    except ValueError as exc:
        raise ValueError(f"Unsupported authority rank: {value}") from exc


def authority_for_source(source_type: str) -> AuthorityRank:
    """Return the explicit authority assigned to a normalized source type.

    Unknown sources fail closed instead of being silently promoted to metadata,
    retrieved, or inferred authority.  A future collector must deliberately add
    its source vocabulary here before it can emit a ContextFact.
    """

    normalized = _normalize_source_type(source_type)
    try:
        return _SOURCE_AUTHORITIES[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported context source_type: {source_type}") from exc


def compare_authority(left: AuthorityRank | str, right: AuthorityRank | str) -> int:
    """Compare two authority values without consulting or changing fact state."""

    left_rank = AUTHORITY_RANKS[_coerce_authority(left)]
    right_rank = AUTHORITY_RANKS[_coerce_authority(right)]
    return (left_rank > right_rank) - (left_rank < right_rank)


def is_confirmed_state(state: FactState | str) -> bool:
    """Return whether the lifecycle state is explicitly human-confirmed."""

    if isinstance(state, FactState):
        return state is FactState.CONFIRMED
    try:
        return FactState(str(state)) is FactState.CONFIRMED
    except ValueError:
        return False


__all__ = [
    "AUTHORITY_RANKS",
    "AuthorityRank",
    "FactState",
    "authority_for_source",
    "compare_authority",
    "is_confirmed_state",
]
