"""Deterministic, task-aware readiness and confidence policy for generators."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.regulatory_context import RegulatoryContext
from app.services.semantic.context_conflicts import (
    CONFLICTING_AUTHORITATIVE_FACTS,
    HISTORICAL_ONLY_DEFINITION,
    MISSING_CONFIRMED_SEMANTIC_BINDING,
    MISSING_CONFIRMED_SEMANTIC_VERSION,
    MISSING_EVIDENCE,
    MISSING_KNOWLEDGE,
    MISSING_LINEAGE,
    MISSING_MART_TO_YBT_MAPPING,
    MISSING_SOURCE_MAPPING,
    STALE_LINEAGE,
)


GenerationTaskType = Literal[
    "source_to_mart",
    "mart_to_ybt",
    "scenario_business",
    "scenario_technical",
]
ConfidenceLevel = Literal["low", "medium", "high"]

_CONFIDENCE_ORDER: dict[ConfidenceLevel, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
}
_SPARSE_CONTEXT_CODES = {
    HISTORICAL_ONLY_DEFINITION,
    MISSING_CONFIRMED_SEMANTIC_BINDING,
    MISSING_CONFIRMED_SEMANTIC_VERSION,
    MISSING_EVIDENCE,
    MISSING_KNOWLEDGE,
    MISSING_LINEAGE,
    MISSING_MART_TO_YBT_MAPPING,
    MISSING_SOURCE_MAPPING,
}


class GenerationReadiness(BaseModel):
    """Strict internal policy result evaluated before model execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    can_generate: bool
    confidence_cap: ConfidenceLevel
    blocking_reasons: list[str]
    warnings: list[str]


def evaluate_generation_readiness(
    context: RegulatoryContext,
    task_type: GenerationTaskType,
    *,
    scope_matches: bool = True,
    governance_allowed: bool = True,
) -> GenerationReadiness:
    """Evaluate typed Context state without issuing I/O or asking the model to decide."""

    blocking: set[str] = set()
    warnings: set[str] = set()

    if not scope_matches:
        blocking.add("GENERATION_SCOPE_MISMATCH")
    if not governance_allowed:
        blocking.add("GENERATION_GOVERNANCE_PROHIBITED")

    for conflict in context.conflicts:
        if conflict.resolution_state == "resolved":
            continue
        if (
            conflict.code == CONFLICTING_AUTHORITATIVE_FACTS
            and conflict.severity == "error"
        ):
            blocking.add(CONFLICTING_AUTHORITATIVE_FACTS)
        else:
            warnings.add(conflict.code)

    question_codes = {
        question.question_code
        for question in context.open_questions
        if question.resolution_state == "open"
    }
    warnings.update(question_codes)

    # These gaps describe the work performed by their matching generator. They
    # remain visible warnings but never block the generator that can fill them.
    if task_type == "source_to_mart":
        blocking.discard(MISSING_SOURCE_MAPPING)
    if task_type == "mart_to_ybt":
        blocking.discard(MISSING_MART_TO_YBT_MAPPING)

    if blocking:
        confidence_cap: ConfidenceLevel = "low"
    elif question_codes & _SPARSE_CONTEXT_CODES:
        confidence_cap = "low"
    elif warnings or any(
        conflict.code == STALE_LINEAGE for conflict in context.conflicts
    ):
        confidence_cap = "medium"
    else:
        confidence_cap = "high"

    return GenerationReadiness(
        can_generate=not blocking,
        confidence_cap=confidence_cap,
        blocking_reasons=sorted(blocking),
        warnings=sorted(warnings),
    )


def normalize_confidence(value: object) -> ConfidenceLevel:
    normalized = str(value or "").strip().casefold()
    if normalized in _CONFIDENCE_ORDER:
        return normalized  # type: ignore[return-value]
    return "low"


def apply_confidence_cap(
    value: object,
    cap: ConfidenceLevel,
) -> ConfidenceLevel:
    normalized = normalize_confidence(value)
    return min((normalized, cap), key=_CONFIDENCE_ORDER.__getitem__)


__all__ = [
    "ConfidenceLevel",
    "GenerationReadiness",
    "GenerationTaskType",
    "apply_confidence_cap",
    "evaluate_generation_readiness",
    "normalize_confidence",
]
