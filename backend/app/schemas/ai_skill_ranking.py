"""Bounded, non-executable field recall, reranker proposal and model-rerank contracts."""
from typing import Annotated

from pydantic import Field, StringConstraints

from app.schemas.ai_skill import ContractModel, PositiveId, SkillInputEnvelope

CandidateId = Annotated[str, StringConstraints(pattern=r"^catalog:[1-9][0-9]*$")]


class FieldCandidateQuery(ContractModel):
    project_id: PositiveId
    target_field_id: PositiveId
    datasource_ids: list[PositiveId] = Field(default_factory=list, max_length=30)
    query: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    top_k: Annotated[int, Field(strict=True, ge=1, le=50)] = 20


class CandidateRank(ContractModel):
    candidate_id: Annotated[str, StringConstraints(pattern=r"^catalog:[1-9][0-9]*$")]
    score: Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
    rationale: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class FieldRankProposal(ContractModel):
    input: FieldCandidateQuery
    context_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    ranking: list[CandidateRank] = Field(max_length=50)


class FieldCandidatePrepare(ContractModel):
    input: FieldCandidateQuery
    context_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    candidate_id: Annotated[str, StringConstraints(pattern=r"^catalog:[1-9][0-9]*$")]
    scenario_id: PositiveId


class RankedCandidate(ContractModel):
    """One model-proposed position; the score is a rank value, never a business probability."""

    candidate_id: CandidateId
    score: Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
    rationale: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    evidence_refs: list[CandidateId] = Field(default_factory=list, max_length=50)


class FieldRankingCandidate(ContractModel):
    """A complete, duplicate-free permutation of the server-provided candidate whitelist."""

    ranking: list[RankedCandidate] = Field(min_length=1, max_length=50)


def validate_field_ranking(candidate: FieldRankingCandidate, envelope: SkillInputEnvelope) -> None:
    """The model may only reorder the supplied candidates, exactly once each.

    Missing, duplicate, unknown and format-invalid identifiers are all rejected here so a
    model can never widen the candidate universe or invent a reason reference.
    """

    expected = {item.id for item in envelope.facts if item.kind == "catalog_field"}
    ids = [item.candidate_id for item in candidate.ranking]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate candidate reference")
    if set(ids) != expected:
        raise ValueError("ranking must cover the provided candidate whitelist exactly")
    for item in candidate.ranking:
        if not set(item.evidence_refs).issubset(expected):
            raise ValueError("unknown candidate evidence reference")


class FieldRerankRequest(ContractModel):
    """Explicit user request to rerank one existing recall snapshot. No skill key is accepted."""

    input: FieldCandidateQuery
    context_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
